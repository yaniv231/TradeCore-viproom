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
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY') or "demo"

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
                df = df.sort_index()
                return df.tail(30)
            else:
                logger.error(f"No data for {symbol}: {data}")
                return None
                
        except Exception as e:
            logger.error(f"Alpha Vantage error for {symbol}: {e}")
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
            
            ax.plot(data.index, data['Close'], color='white', linewidth=3, label=f'{symbol} Price', alpha=0.9)
            ax.fill_between(data.index, data['Low'], data['High'], alpha=0.2, color='gray', label='Daily Range')
            
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
            
            ax.fill_between(data.index, entry_price, target2, alpha=0.15, color='green', label='אזור רווח')
            ax.fill_between(data.index, stop_loss, entry_price, alpha=0.15, color='red', label='אזור סיכון')
            
            ax.set_title(f'{symbol} - PeakTrade VIP Analysis', color='white', fontsize=20, fontweight='bold', pad=20)
            ax.set_ylabel('מחיר ($)', color='white', fontsize=16, fontweight='bold')
            ax.set_xlabel('תאריך', color='white', fontsize=16, fontweight='bold')
            
            ax.grid(True, alpha=0.4, color='gray', linestyle='-', linewidth=0.5)
            ax.legend(loc='upper left', fontsize=13, framealpha=0.9, fancybox=True, shadow=True)
            
            ax.set_facecolor('#0a0a0a')
            fig.patch.set_facecolor('#1a1a1a')
            
            ax.text(0.02, 0.98, 'PeakTrade VIP', transform=ax.transAxes, 
                    fontsize=18, color='cyan', fontweight='bold', 
                    verticalalignment='top', alpha=0.9)
            
            ax.text(0.02, 0.02, 'Alpha Vantage Data', transform=ax.transAxes, 
                    fontsize=14, color='lime', fontweight='bold', 
                    verticalalignment='bottom', alpha=0.9)
            
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight', 
                       facecolor='#1a1a1a', edgecolor='none')
            buffer.seek(0)
            plt.close()
            
            logger.info(f"✅ Professional chart created for {symbol}")
            return buffer
            
        except Exception as e:
            logger.error(f"❌ Error creating chart: {e}")
            return None

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת התחלה עם disclaimer"""
        user = update.effective_user
        logger.info(f"User {user.id} ({user.username}) started PeakTrade bot")
        
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
your-email@example.com מאשר"""
        
        await update.message.reply_text(disclaimer_message)
        return WAITING_FOR_EMAIL

    async def log_disclaimer_sent(self, user):
        """רישום שליחת disclaimer ב-Google Sheets"""
        try:
            if not self.sheet:
                return
                
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            new_row = [
                user.id,
                user.username or "N/A",
                "",
                current_time,
                "pending",
                "",
                "",
                "trial_pending",
                "",
                "",
                current_time
            ]
            self.sheet.append_row(new_row)
            logger.info(f"✅ Disclaimer logged for user {user.id}")
            
        except Exception as e:
            logger.error(f"❌ Error logging disclaimer: {e}")

    async def handle_email_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """טיפול באישור האימייל"""
        user = update.effective_user
        message_text = update.message.text.strip()
        
        if "מאשר" not in message_text:
            await update.message.reply_text(
                "❌ אנא שלח את האימייל בפורמט הנכון:\n"
                "your-email@example.com מאשר"
            )
            return WAITING_FOR_EMAIL
        
        email = message_text.replace("מאשר", "").strip()
        
        if "@" not in email or "." not in email:
            await update.message.reply_text(
                "❌ כתובת האימייל לא תקינה. אנא נסה שוב:\n"
                "your-email@example.com מאשר"
            )
            return WAITING_FOR_EMAIL
        
        processing_msg = await update.message.reply_text(
            "⏳ מעבד את הרישום לתקופת ניסיון..."
        )
        
        try:
            invite_link = await context.bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                expire_date=int((datetime.now() + timedelta(days=8)).timestamp()),
                name=f"Trial_{user.id}_{email.split('@')[0]}"
            )
            
            success_message = f"""✅ ברוך הבא ל-PeakTrade VIP!

📧 האימייל שלך: {email}
👤 משתמש: @{user.username or 'לא זמין'}

🔗 קישור הצטרפות לערוץ הפרמיום:
{invite_link.invite_link}

⏰ תקופת ניסיון: 7 ימים
📅 מתחיל: {datetime.now().strftime("%d/%m/%Y")}

🎯 מה תקבל בערוץ:
• הודעות כל 30 דקות בין 10:00-22:00
• ניתוחים טכניים מתקדמים
• גרפי נרות בזמן אמת עם סטופלוס

לחץ על הקישור והצטרף עכשיו! 🚀"""
            
            await processing_msg.edit_text(
                success_message,
                disable_web_page_preview=True
            )
            
            logger.info(f"✅ Trial registration successful for user {user.id}")
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"❌ Error in trial registration: {e}")
            await processing_msg.edit_text(
                f"❌ שגיאה ברישום לתקופת ניסיון\n\n"
                f"אנא פנה לתמיכה."
            )
            return ConversationHandler.END

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת עזרה"""
        help_text = f"""🆘 PeakTrade VIP Bot - עזרה

📋 פקודות זמינות:
/start - התחלת תהליך רישום
/help - הצגת עזרה זו

⏰ תקופת ניסיון: 7 ימים חינם
💰 מחיר מנוי: {MONTHLY_PRICE}₪/חודש"""
        
        await update.message.reply_text(help_text)

    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ביטול תהליך"""
        await update.message.reply_text(
            "❌ התהליך בוטל. שלח /start כדי להתחיל מחדש."
        )
        return ConversationHandler.END

    def setup_handlers(self):
        """הגדרת handlers"""
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', self.start_command)],
            states={
                WAITING_FOR_EMAIL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_email_confirmation)
                ],
            },
            fallbacks=[
                CommandHandler('cancel', self.cancel_command),
                CommandHandler('start', self.start_command)
            ],
        )
        
        self.application.add_handler(conv_handler)
        self.application.add_handler(CommandHandler('help', self.help_command))
        
        logger.info("✅ All handlers configured")

    async def send_guaranteed_stock_content(self):
        """שליחת תוכן מניה מקצועי עם Alpha Vantage"""
        try:
            logger.info("📈 Preparing stock content with Alpha Vantage...")
            
            premium_stocks = [
                {'symbol': 'AAPL', 'type': '🇺🇸 אמריקאית', 'sector': 'טכנולוגיה'},
                {'symbol': 'MSFT', 'type': '🇺🇸 אמריקאית', 'sector': 'טכנולוגיה'},
                {'symbol': 'GOOGL', 'type': '🇺🇸 אמריקאית', 'sector': 'טכנולוגיה'},
                {'symbol': 'TSLA', 'type': '🇺🇸 אמריקאית', 'sector': 'רכב חשמלי'},
                {'symbol': 'NVDA', 'type': '🇺🇸 אמריקאית', 'sector': 'AI/שבבים'}
            ]
            
            selected = random.choice(premium_stocks)
            symbol = selected['symbol']
            stock_type = selected['type']
            sector = selected['sector']
            
            data = self.alpha_api.get_stock_data(symbol)
            
            if data is None or data.empty:
                logger.warning(f"No Alpha Vantage data for {symbol}")
                await self.send_text_analysis(symbol, stock_type)
                return
            
            await asyncio.sleep(2)
            
            current_price = data['Close'][-1]
            change = data['Close'][-1] - data['Close'][-2] if len(data) > 1 else 0
            change_percent = (change / data['Close'][-2] * 100) if len(data) > 1 and data['Close'][-2] != 0 else 0
            volume = data['Volume'][-1] if len(data) > 0 else 0
            
            high_30d = data['High'].max()
            low_30d = data['Low'].min()
            avg_volume = data['Volume'].mean()
            
            entry_price = current_price * 1.02
            stop_loss = current_price * 0.95
            profit_target_1 = current_price * 1.08
            profit_target_2 = current_price * 1.15
            
            risk = entry_price - stop_loss
            reward = profit_target_1 - entry_price
            risk_reward = reward / risk if risk > 0 else 0
            
            chart_buffer = self.create_professional_chart_with_prices(symbol, data, current_price, entry_price, stop_loss, profit_target_1, profit_target_2)
            
            caption = f"""🔥 {stock_type} {symbol} - המלצת השקעה בלעדית

💎 סקטור: {sector} | מחיר נוכחי: ${current_price:.2f}

📊 ניתוח טכני Alpha Vantage (30 ימים):
• טווח: ${low_30d:.2f} - ${high_30d:.2f}
• נפח ממוצע: {avg_volume:,.0f} | היום: {volume:,.0f}
• מומנטום: {'חיובי 📈' if change_percent > 0 else 'שלילי 📉'} ({change_percent:+.2f}%)

🎯 אסטרטגיית כניסה LIVE:
🟢 כניסה: ${entry_price:.2f}
🔴 סטופלוס: ${stop_loss:.2f}
🎯 יעד ראשון: ${profit_target_1:.2f}
🚀 יעד שני: ${profit_target_2:.2f}

⚖️ יחס סיכון/תשואה: 1:{risk_reward:.1f}

💰 פוטנציאל רווח: ${reward:.2f} למניה
💸 סיכון מקסימלי: ${risk:.2f} למניה

⚠️ זוהי המלצה בלעדית לחברי PeakTrade VIP בלבד
🚀 עסקה אחת ואתה משלש את ההשקעה!!
📊 נתונים מ-Alpha Vantage

#PeakTradeVIP #{symbol} #AlphaVantage"""
            
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

    async def send_text_analysis(self, symbol, asset_type):
        """שליחת ניתוח טקסט אם הגרף נכשל"""
        try:
            message = f"""{asset_type} 📈 {symbol} - המלצה בלעדית

💰 מחיר נוכחי: מעודכן בזמן אמת
📊 ניתוח טכני מתקדם

🎯 המלצות מסחר בלעדיות:
🟢 כניסה: +2% מהמחיר הנוכחי
🔴 סטופלוס: -5% מהמחיר הנוכחי
🎯 יעד ראשון: +8% רווח
🚀 יעד שני: +15% רווח

⚠️ זוהי המלצה בלעדית לחברי VIP בלבד
🚀 עסקה אחת ואתה משלש את ההשקעה!!

#PeakTradeVIP #{symbol.replace('-USD', '').replace('.TA', '')} #ExclusiveSignal"""
            
            await self.application.bot.send_message(
                chat_id=CHANNEL_ID,
                text=message
            )
            
            logger.info(f"✅ Text analysis sent for {symbol}")
            
        except Exception as e:
            logger.error(f"❌ Error sending text analysis: {e}")

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
                            await self.send_guaranteed_stock_content()
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
