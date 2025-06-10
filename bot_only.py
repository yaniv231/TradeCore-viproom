import logging
import os
import asyncio
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
from telegram.error import TelegramError
import gspread
from google.oauth2.service_account import Credentials
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import matplotlib.pyplot as plt
import io
import random
import requests
import pandas as pd

# הגדרת לוגינג
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# הגדרות המערכת
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or "7619055199:AAEL28DJ-E1Xl7iEfdPqTXJ0in1Lps0VOtM"
CHANNEL_ID = os.getenv('CHANNEL_ID') or "-1002886874719"
GOOGLE_CREDENTIALS = os.getenv('GOOGLE_CREDENTIALS')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY') or "demo"  # החלף ב-API key אמיתי

# הגדרות תשלום
PAYPAL_PAYMENT_LINK = "https://paypal.me/yourpaypal/120"
MONTHLY_PRICE = 120

# מצבי השיחה
WAITING_FOR_EMAIL = 1

class AlphaVantageAPI:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://www.alphavantage.co/query"
    
    def get_stock_data(self, symbol):
        """קבלת נתוני מניה מ-Alpha Vantage"""
        try:
            params = {
                'function': 'TIME_SERIES_DAILY',
                'symbol': symbol,
                'apikey': self.api_key,
                'outputsize': 'compact'
            }
            
            response = requests.get(self.base_url, params=params)
            data = response.json()
            
            if 'Time Series (Daily)' in data:
                time_series = data['Time Series (Daily)']
                df = pd.DataFrame.from_dict(time_series, orient='index')
                df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
                df.index = pd.to_datetime(df.index)
                df = df.astype(float)
                df = df.sort_index()  # מיון לפי תאריך
                return df.tail(30)  # 30 ימים אחרונים
            else:
                logger.error(f"No data for {symbol}: {data}")
                return None
                
        except Exception as e:
            logger.error(f"Alpha Vantage error for {symbol}: {e}")
            return None
    
    def get_crypto_data(self, symbol):
        """קבלת נתוני קריפטו מ-Alpha Vantage"""
        try:
            # המרת סמל קריפטו (BTC-USD -> BTC)
            crypto_symbol = symbol.replace('-USD', '')
            
            params = {
                'function': 'DIGITAL_CURRENCY_DAILY',
                'symbol': crypto_symbol,
                'market': 'USD',
                'apikey': self.api_key
            }
            
            response = requests.get(self.base_url, params=params)
            data = response.json()
            
            if 'Time Series (Digital Currency Daily)' in data:
                time_series = data['Time Series (Digital Currency Daily)']
                df = pd.DataFrame.from_dict(time_series, orient='index')
                
                # שימוש בעמודות הנכונות לקריפטו
                df_clean = pd.DataFrame()
                df_clean['Open'] = df['1a. open (USD)'].astype(float)
                df_clean['High'] = df['2a. high (USD)'].astype(float)
                df_clean['Low'] = df['3a. low (USD)'].astype(float)
                df_clean['Close'] = df['4a. close (USD)'].astype(float)
                df_clean['Volume'] = df['5. volume'].astype(float)
                df_clean.index = pd.to_datetime(df_clean.index)
                df_clean = df_clean.sort_index()
                return df_clean.tail(30)
            else:
                logger.error(f"No crypto data for {symbol}: {data}")
                return None
                
        except Exception as e:
            logger.error(f"Alpha Vantage crypto error for {symbol}: {e}")
            return None

class PeakTradeBot:
    def __init__(self):
        self.application = None
        self.scheduler = None
        self.google_client = None
        self.sheet = None
        self.alpha_api = AlphaVantageAPI(ALPHA_VANTAGE_API_KEY)
        self.setup_google_sheets()
        
    def setup_google_sheets(self):
        """הגדרת חיבור ל-Google Sheets"""
        try:
            if GOOGLE_CREDENTIALS:
                creds_dict = json.loads(GOOGLE_CREDENTIALS)
                scope = [
                    'https://spreadsheets.google.com/feeds',
                    'https://www.googleapis.com/auth/drive'
                ]
                creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
                self.google_client = gspread.authorize(creds)
                self.sheet = self.google_client.open_by_key(SPREADSHEET_ID).sheet1
                logger.info("✅ Google Sheets connected successfully")
            else:
                logger.warning("⚠️ Google Sheets credentials not found")
        except Exception as e:
            logger.error(f"❌ Error setting up Google Sheets: {e}")

    def check_user_exists(self, user_id):
        """בדיקה אם משתמש כבר קיים ב-Google Sheets"""
        try:
            if not self.sheet:
                return False
            
            records = self.sheet.get_all_records()
            for record in records:
                if str(record.get('telegram_user_id')) == str(user_id):
                    status = record.get('payment_status', '')
                    if status in ['trial_active', 'paid_subscriber']:
                        return True
            return False
        except Exception as e:
            logger.error(f"❌ Error checking user existence: {e}")
            return False

    def create_professional_chart_with_prices(self, symbol, data, current_price, entry_price, stop_loss, target1, target2):
        """יצירת גרף מקצועי עם מחירים ספציפיים מסומנים"""
        try:
            plt.style.use('dark_background')
            fig, ax = plt.subplots(figsize=(14, 10))
            
            # גרף קו פשוט של המחיר
            ax.plot(data.index, data['Close'], color='white', linewidth=3, label=f'{symbol} Price', alpha=0.9)
            ax.fill_between(data.index, data['Low'], data['High'], alpha=0.2, color='gray', label='Daily Range')
            
            # קווי המלצות בצבעים בולטים עם מחירים ספציפיים
            ax.axhline(current_price, color='yellow', linestyle='-', linewidth=4, 
                      label=f'💰 מחיר נוכחי: ${current_price:.2f}', alpha=1.0)
            ax.axhline(entry_price, color='lime', linestyle='-', linewidth=3, 
                      label=f'🟢 כניסה: ${entry_price:.2f}', alpha=0.9)
            ax.axhline(stop_loss, color='red', linestyle='--', linewidth=3, 
                      label=f'🔴 סטופלוס: ${stop_loss:.2f}', alpha=0.9)
            ax.axhline(target1, color='gold', linestyle=':', linewidth=3, 
                      label=f'🎯 יעד 1: ${target1:.2f}', alpha=0.9)
            ax.axhline(target2, color='cyan', linestyle=':', linewidth=3, 
                      label=f'🚀 יעד 2: ${target2:.2f}', alpha=0.9)
            
            # אזורי רווח והפסד
            ax.fill_between(data.index, entry_price, target2, alpha=0.15, color='green', label='אזור רווח')
            ax.fill_between(data.index, stop_loss, entry_price, alpha=0.15, color='red', label='אזור סיכון')
            
            # עיצוב מקצועי
            ax.set_title(f'{symbol} - PeakTrade VIP Analysis', color='white', fontsize=20, fontweight='bold', pad=20)
            ax.set_ylabel('מחיר ($)', color='white', fontsize=16, fontweight='bold')
            ax.set_xlabel('תאריך', color='white', fontsize=16, fontweight='bold')
            
            # רשת ולגנדה
            ax.grid(True, alpha=0.4, color='gray', linestyle='-', linewidth=0.5)
            ax.legend(loc='upper left', fontsize=13, framealpha=0.9, fancybox=True, shadow=True)
            
            # צבעי רקע מקצועיים
            ax.set_facecolor('#0a0a0a')
            fig.patch.set_facecolor('#1a1a1a')
            
            # הוספת טקסט מקצועי
            ax.text(0.02, 0.98, 'PeakTrade VIP', transform=ax.transAxes, 
                    fontsize=18, color='cyan', fontweight='bold', 
                    verticalalignment='top', alpha=0.9)
            
            ax.text(0.02, 0.02, 'Exclusive Signal - Alpha Vantage Data', transform=ax.transAxes, 
                    fontsize=14, color='lime', fontweight='bold', 
                    verticalalignment='bottom', alpha=0.9)
            
            # הוספת מחירים על הגרף
            ax.annotate(f'${current_price:.2f}', xy=(data.index[-1], current_price), 
                       xytext=(10, 0), textcoords='offset points', 
                       color='yellow', fontsize=14, fontweight='bold',
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.7))
            
            ax.annotate(f'${entry_price:.2f}', xy=(data.index[-1], entry_price), 
                       xytext=(10, 0), textcoords='offset points', 
                       color='lime', fontsize=12, fontweight='bold',
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.7))
            
            # שמירה
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight', 
                       facecolor='#1a1a1a', edgecolor='none')
            buffer.seek(0)
            plt.close()
            
            logger.info(f"✅ Professional chart created for {symbol} with Alpha Vantage data")
            return buffer
            
        except Exception as e:
            logger.error(f"❌ Error creating professional chart: {e}")
            return None

    # [כל הפונקציות הקיימות של start_command, log_disclaimer_sent, וכו' נשארות זהות]
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת התחלה עם disclaimer"""
        user = update.effective_user
        logger.info(f"User {user.id} ({user.username}) started PeakTrade bot")
        
        if self.check_user_exists(user.id):
            existing_user_message = f"""🔄 שלום {user.first_name}!

נראה שאתה כבר רשום במערכת שלנו! 

✅ הסטטוס שלך: פעיל בערוץ PeakTrade VIP

🎯 מה תוכל לעשות:
• להמשיך ליהנות מהתוכן הפרמיום
• לקבל ניתוחים טכניים יומיים
• לראות גרפי נרות בזמן אמת

💬 יש שאלות? פנה למנהל הערוץ

תודה שאתה חלק מקהילת PeakTrade VIP! 🚀"""
            
            await update.message.reply_text(existing_user_message)
            return ConversationHandler.END
        
        disclaimer_message = f"""🏔️ PeakTrade VIP | הצהרת אחריות

שלום {user.first_name}! 👋

⚠️ הצהרת ויתור אחריות:
• המידע המוצג בערוץ הוא לצרכי חינוך בלבד
• אין זו המלצה להשקעה או ייעוץ פיננסי
• כל השקעה כרוכה בסיכון והפסדים אפשריים
• אתה נושא באחריות המלאה להחלטותיך

📈 מה תקבל בערוץ PeakTrade VIP:
• ניתוחים טכניים מתקדמים עם נתוני Alpha Vantage
• גרפי נרות בזמן אמת עם סטופלוס מומלץ
• המלצות מניות דינמיות - אמריקאיות וישראליות
• המלצות קריפטו מובילות
• תוכן ייחודי ומקצועי

⏰ תקופת ניסיון: 7 ימים חינם
💰 מחיר מנוי: {MONTHLY_PRICE}₪/חודש

✅ להמשך, אנא שלח את כתובת האימייל שלך בפורמט:
your-email@example.com מאשר

💡 דוגמה:
john.doe@gmail.com מאשר"""
        
        await update.message.reply_text(disclaimer_message)
        
        await self.log_disclaimer_sent(user)
        return WAITING_FOR_EMAIL

    # [שאר הפונקציות נשארות זהות עד לפונקציות השליחה]

    async def send_guaranteed_stock_content(self):
        """שליחת תוכן מניה מקצועי עם Alpha Vantage"""
        try:
            logger.info("📈 Preparing stock content with Alpha Vantage...")
            
            # מניות פופולריות שעובדות עם Alpha Vantage
            premium_stocks = [
                {'symbol': 'AAPL', 'type': '🇺🇸 אמריקאית', 'sector': 'טכנולוגיה'},
                {'symbol': 'MSFT', 'type': '🇺🇸 אמריקאית', 'sector': 'טכנולוגיה'},
                {'symbol': 'GOOGL', 'type': '🇺🇸 אמריקאית', 'sector': 'טכנולוגיה'},
                {'symbol': 'TSLA', 'type': '🇺🇸 אמריקאית', 'sector': 'רכב חשמלי'},
                {'symbol': 'NVDA', 'type': '🇺🇸 אמריקאית', 'sector': 'AI/שבבים'},
                {'symbol': 'AMZN', 'type': '🇺🇸 אמריקאית', 'sector': 'מסחר אלקטרוני'},
                {'symbol': 'META', 'type': '🇺🇸 אמריקאית', 'sector': 'רשתות חברתיות'}
            ]
            
            selected = random.choice(premium_stocks)
            symbol = selected['symbol']
            stock_type = selected['type']
            sector = selected['sector']
            
            # קבלת נתונים מ-Alpha Vantage
            data = self.alpha_api.get_stock_data(symbol)
            
            if data is None or data.empty:
                logger.warning(f"No Alpha Vantage data for {symbol}")
                await self.send_text_analysis(symbol, stock_type)
                return
            
            # השהייה קצרה כדי לא לעבור על מגבלות API
            await asyncio.sleep(2)
            
            current_price = data['Close'][-1]
            change = data['Close'][-1] - data['Close'][-2] if len(data) > 1 else 0
            change_percent = (change / data['Close'][-2] * 100) if len(data) > 1 and data['Close'][-2] != 0 else 0
            volume = data['Volume'][-1] if len(data) > 0 else 0
            
            # חישובי המלצות מקצועיות
            high_30d = data['High'].max()
            low_30d = data['Low'].min()
            avg_volume = data['Volume'].mean()
            
            # נקודות כניסה ויציאה מקצועיות עם מחירים ספציפיים
            entry_price = current_price * 1.02  # כניסה 2% מעל המחיר הנוכחי
            stop_loss = current_price * 0.95   # סטופלוס 5% מתחת
            profit_target_1 = current_price * 1.08  # יעד ראשון 8%
            profit_target_2 = current_price * 1.15  # יעד שני 15%
            
            # חישוב יחס סיכון/תשואה
            risk = entry_price - stop_loss
            reward = profit_target_1 - entry_price
            risk_reward = reward / risk if risk > 0 else 0
            
            # יצירת גרף מקצועי עם מחירים ספציפיים
            chart_buffer = self.create_professional_chart_with_prices(symbol, data, current_price, entry_price, stop_loss, profit_target_1, profit_target_2)
            
            # תוכן בלעדי ומקצועי עם מחירים ספציפיים
            caption = f"""🔥 {stock_type} {symbol} - המלצת השקעה בלעדית

💎 סקטור: {sector} | מחיר נוכחי: ${current_price:.2f}

📊 ניתוח טכני מתקדם Alpha Vantage (30 ימים):
• טווח: ${low_30d:.2f} - ${high_30d:.2f}
• נפח ממוצע: {avg_volume:,.0f} | היום: {volume:,.0f}
• מומנטום: {'חיובי 📈' if change_percent > 0 else 'שלילי 📉'} ({change_percent:+.2f}%)

🎯 אסטרטגיית כניסה LIVE - מחירים ספציפיים:
🟢 כניסה: ${entry_price:.2f} (מעל המחיר הנוכחי)
🔴 סטופלוס: ${stop_loss:.2f} (הגנה מפני הפסדים)
🎯 יעד ראשון: ${profit_target_1:.2f} (רווח ראשון)
🚀 יעד שני: ${profit_target_2:.2f} (רווח מקסימלי)

⚖️ יחס סיכון/תשואה: 1:{risk_reward:.1f}

💡 המלצה בלעדית PeakTrade:
{"🔥 כניסה מומלצת - מגמה חזקה!" if change_percent > 2 else "⚡ המתן לפריצה מעל נקודת הכניסה" if change_percent > 0 else "⏳ המתן לייצוב לפני כניסה"}

📈 אסטרטגיית יציאה:
• מכור 50% ב-${profit_target_1:.2f} (יעד ראשון)
• מכור 50% ב-${profit_target_2:.2f} (יעד שני)
• הזז סטופלוס ל-${entry_price:.2f} אחרי יעד ראשון

💰 פוטנציאל רווח: ${reward:.2f} למניה
💸 סיכון מקסימלי: ${risk:.2f} למניה

⚠️ זוהי המלצה בלעדית לחברי PeakTrade VIP בלבד
🚀 עסקה אחת ואתה משלש את ההשקעה!!
📊 נתונים מ-Alpha Vantage - המקור המהימן ביותר

#PeakTradeVIP #{symbol} #ExclusiveSignal #AlphaVantage"""
            
            if chart_buffer:
                await self.application.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=chart_buffer,
                    caption=caption
                )
                logger.info(f"✅ Alpha Vantage stock content sent for {symbol}")
            else:
                await self.application.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=caption
                )
                logger.info(f"✅ Alpha Vantage stock content (text) sent for {symbol}")
            
        except Exception as e:
            logger.error(f"❌ Error sending Alpha Vantage stock content: {e}")

    async def send_guaranteed_crypto_content(self):
        """שליחת תוכן קריפטו מקצועי עם Alpha Vantage"""
        try:
            logger.info("🪙 Preparing crypto content with Alpha Vantage...")
            
            # קריפטו שעובד עם Alpha Vantage
            premium_crypto = [
                {'symbol': 'BTC-USD', 'name': 'Bitcoin', 'type': '👑 מלך הקריפטו'},
                {'symbol': 'ETH-USD', 'name': 'Ethereum', 'type': '⚡ פלטפורמת חכמה'},
                {'symbol': 'LTC-USD', 'name': 'Litecoin', 'type': '🥈 כסף דיגיטלי'},
                {'symbol': 'XRP-USD', 'name': 'Ripple', 'type': '🏦 תשלומים בנקאיים'}
            ]
            
            selected = random.choice(premium_crypto)
            symbol = selected['symbol']
            crypto_name = selected['name']
            crypto_type = selected['type']
            
            # קבלת נתונים מ-Alpha Vantage
            data = self.alpha_api.get_crypto_data(symbol)
            
            if data is None or data.empty:
                logger.warning(f"No Alpha Vantage crypto data for {symbol}")
                await self.send_text_analysis(symbol, '🪙 קריפטו')
                return
            
            # השהייה קצרה כדי לא לעבור על מגבלות API
            await asyncio.sleep(2)
            
            current_price = data['Close'][-1]
            change = data['Close'][-1] - data['Close'][-2] if len(data) > 1 else 0
            change_percent = (change / data['Close'][-2] * 100) if len(data) > 1 and data['Close'][-2] != 0 else 0
            volume = data['Volume'][-1] if len(data) > 0 else 0
            
            # חישובי המלצות מקצועיות לקריפטו
            high_30d = data['High'].max()
            low_30d = data['Low'].min()
            
            # נקודות כניסה ויציאה אגרסיביות לקריפטו עם מחירים ספציפיים
            entry_price = current_price * 1.03  # כניסה 3% מעל
            stop_loss = current_price * 0.92   # סטופלוס 8% מתחת
            profit_target_1 = current_price * 1.12  # יעד ראשון 12%
            profit_target_2 = current_price * 1.25  # יעד שני 25%
            
            # חישוב יחס סיכון/תשואה
            risk = entry_price - stop_loss
            reward = profit_target_1 - entry_price
            risk_reward = reward / risk if risk > 0 else 0
            
            # יצירת גרף מקצועי עם מחירים ספציפיים
            chart_buffer = self.create_professional_chart_with_prices(symbol, data, current_price, entry_price, stop_loss, profit_target_1, profit_target_2)
            
            caption = f"""🔥 {crypto_type} {crypto_name} - אות קנייה בלעדי

💎 מטבע: {symbol.replace('-USD', '')} | מחיר נוכחי: ${current_price:.4f}

📊 ניתוח קריפטו Alpha Vantage (30 ימים):
• טווח: ${low_30d:.4f} - ${high_30d:.4f}
• נפח 24H: {volume:,.0f}
• מומנטום: {'🚀 חזק' if change_percent > 3 else '📈 חיובי' if change_percent > 0 else '📉 שלילי'} ({change_percent:+.2f}%)

🎯 אסטרטגיית קריפטו LIVE - מחירים ספציפיים:
🟢 כניסה: ${entry_price:.4f} (פריצה מעל המחיר הנוכחי)
🔴 סטופלוס: ${stop_loss:.4f} (הגנה מפני הפסדים)
🎯 יעד ראשון: ${profit_target_1:.4f} (רווח ראשון)
🚀 יעד שני: ${profit_target_2:.4f} (רווח מקסימלי)

⚖️ יחס סיכון/תשואה: 1:{risk_reward:.1f}

💡 אות בלעדי PeakTrade:
{"🔥 כניסה חזקה - מומנטום חיובי!" if change_percent > 5 else "⚡ המתן לפריצה מעל התנגדות" if change_percent > 0 else "⏳ זהירות - המתן לאישור מגמה"}

📈 אסטרטגיית יציאה מתקדמת:
• מכור 40% ב-${profit_target_1:.4f} (יעד ראשון)
• מכור 60% ב-${profit_target_2:.4f} (יעד שני)
• הזז סטופלוס ל-${entry_price:.4f} אחרי יעד ראשון

💰 פוטנציאל רווח: ${reward:.4f} ליחידה
💸 סיכון מקסימלי: ${risk:.4f} ליחידה

⚠️ קריפטו - סיכון גבוה, פוטנציאל רווח גבוה
🔥 המלצה בלעדית לחברי VIP בלבד
🚀 עסקה אחת ואתה משלש את ההשקעה!!
📊 נתונים מ-Alpha Vantage - המקור המהימן ביותר

#PeakTradeVIP #{crypto_name} #CryptoSignal #AlphaVantage"""
            
            if chart_buffer:
                await self.application.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=chart_buffer,
                    caption=caption
                )
                logger.info(f"✅ Alpha Vantage crypto content sent for {symbol}")
            else:
                await self.application.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=caption
                )
                logger.info(f"✅ Alpha Vantage crypto content (text) sent for {symbol}")
            
        except Exception as e:
            logger.error(f"❌ Error sending Alpha Vantage crypto content: {e}")

    # [שאר הפונקציות נשארות זהות]

    async def run(self):
        """הפעלת הבוט עם שליחה מאולצת ו-Alpha Vantage"""
        logger.info("🚀 Starting PeakTrade VIP Bot with Alpha Vantage...")
        
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.setup_handlers()
        
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            logger.info("✅ PeakTrade VIP Bot is running successfully!")
            logger.info("📊 Alpha Vantage API integrated")
            logger.info("📊 Content: Every 30 minutes between 10:00-22:00")
            logger.info(f"💰 Monthly subscription: {MONTHLY_PRICE}₪")
            
            # שליחת הודעת בדיקה מיידית
            await asyncio.sleep(10)
            try:
                await self.send_guaranteed_stock_content()
                logger.info("✅ Immediate Alpha Vantage test sent")
            except Exception as e:
                logger.error(f"❌ Test error: {e}")
            
            # לולאה עם שליחה מאולצת כל 30 דקות
            last_send_time = datetime.now()
            
            while True:
                current_time = datetime.now()
                
                # בדוק אם עברו 30 דקות מההודעה האחרונה
                if (current_time - last_send_time).total_seconds() >= 1800:  # 30 דקות
                    # בדוק אם השעה בין 10:00-22:00
                    if 10 <= current_time.hour < 22:
                        try:
                            logger.info(f"🕐 Forcing Alpha Vantage content at {current_time.strftime('%H:%M')}")
                            
                            # בחירה אקראית בין מניה לקריפטו
                            content_type = random.choice(['stock', 'crypto'])
                            
                            if content_type == 'stock':
                                await self.send_guaranteed_stock_content()
                            else:
                                await self.send_guaranteed_crypto_content()
                                
                            last_send_time = current_time
                            logger.info("✅ Forced Alpha Vantage content sent successfully!")
                        except Exception as e:
                            logger.error(f"❌ Error in forced Alpha Vantage send: {e}")
                
                await asyncio.sleep(60)  # בדוק כל דקה
                
        except Exception as e:
            logger.error(f"❌ Bot error: {e}")
        finally:
            if self.application:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()

if __name__ == "__main__":
    bot = PeakTradeBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
