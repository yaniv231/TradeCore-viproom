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
            
            ax.text(0.02, 0.02, 'Professional Analysis', transform=ax.transAxes, 
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
        
        disclaimer_message = f"""🏔️ PeakTrade VIP | הצטרפות לערוץ הפרמיום

שלום {user.first_name}! 👋

📈 מה תקבל בערוץ PeakTrade VIP:
• ניתוחים טכניים מתקדמים עם גרפים מקצועיים
• המלצות מניות חמות בזמן אמת
• אותות קנייה ומכירה מדויקים
• המלצות מניות אמריקאיות וישראליות
• המלצות קריפטו מובילות
• תוכן ייחודי ומקצועי

⏰ תקופת ניסיון: 7 ימים חינם
💰 מחיר מנוי: 120₪/חודש

✅ להמשך, אנא שלח את המילה: מאשר

המידע המוצג בערוץ הוא לצרכי מידע בלבד • כל השקעה כרוכה בסיכון"""
        
        await update.message.reply_text(disclaimer_message)
        return WAITING_FOR_EMAIL

    async def log_disclaimer_sent(self, user):
        """רישום שליחת disclaimer ב-Google Sheets"""
        try:
            if not self.sheet:
                return
                
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            trial_end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
            
            new_row = [
                user.id,
                user.username or "N/A",
                "",
                current_time,
                "confirmed",
                current_time,
                trial_end,
                "trial_active",
                "",
                "",
                current_time
            ]
            self.sheet.append_row(new_row)
            logger.info(f"✅ User {user.id} registered for trial")
            
        except Exception as e:
            logger.error(f"❌ Error logging disclaimer: {e}")

    async def handle_email_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """טיפול באישור - רק המילה מאשר"""
        user = update.effective_user
        message_text = update.message.text.strip()
        
        if message_text.lower() != "מאשר":
            await update.message.reply_text(
                "❌ אנא שלח את המילה: מאשר"
            )
            return WAITING_FOR_EMAIL
        
        processing_msg = await update.message.reply_text(
            "⏳ מכין עבורך את הקישור לערוץ הפרמיום..."
        )
        
        try:
            await self.log_disclaimer_sent(user)
            
            invite_link = await context.bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                expire_date=int((datetime.now() + timedelta(days=8)).timestamp()),
                name=f"Trial_{user.id}_{user.username or 'user'}"
            )
            
            success_message = f"""🎉 ברוך הבא ל-PeakTrade VIP!

👤 שם משתמש: @{user.username or 'לא זמין'}

🔗 הקישור שלך לערוץ הפרמיום:
{invite_link.invite_link}

⏰ תקופת הניסיון שלך: 7 ימים מלאים
📅 מתחיל היום: {datetime.now().strftime("%d/%m/%Y")}
📅 מסתיים: {(datetime.now() + timedelta(days=7)).strftime("%d/%m/%Y")}

🎯 מה מחכה לך בערוץ:
• המלצות מניות חמות כל 30 דקות
• גרפים מקצועיים עם נקודות כניסה ויציאה
• ניתוחים טכניים מתקדמים
• קהילת משקיעים פעילה

לחץ על הקישור והצטרף עכשיו! 🚀

בהצלחה במסחר! 💪"""
            
            await processing_msg.edit_text(
                success_message,
                disable_web_page_preview=True
            )
            
            logger.info(f"✅ Trial registration successful for user {user.id}")
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"❌ Error in trial registration: {e}")
            await processing_msg.edit_text(
                "❌ אופס! משהו השתבש ברישום\n\nאנא נסה שוב או פנה לתמיכה."
            )
            return ConversationHandler.END

    async def send_trial_expiry_reminder(self, user_id):
        """שליחת תזכורת תשלום יום לפני סיום תקופת הניסיון"""
        try:
            keyboard = [
                [InlineKeyboardButton("💎 כן - אני רוצה להמשיך!", callback_data="pay_yes")],
                [InlineKeyboardButton("❌ לא תודה", callback_data="pay_no")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            reminder_message = f"""⏰ תקופת הניסיון שלך מסתיימת מחר!

שלום! תקופת הניסיון שלך בערוץ PeakTrade VIP מסתיימת מחר.

💎 רוצה להמשיך ליהנות מהתוכן המקצועי?
• המלצות מניות חמות יומיות
• גרפים מקצועיים עם אותות מדויקים
• קהילת משקיעים מנצחת
• תוכן בלעדי שמניב רווחים

💰 מחיר מנוי: {MONTHLY_PRICE}₪/חודש בלבד
💳 תשלום מאובטח דרך PayPal

⚠️ מי שלא יחדש – יוסר מהערוץ אוטומטית מחר.
📸 אחרי התשלום שלח צילום מסך

🚀 עסקה אחת ואתה משלש את ההשקעה!

מה תבחר?"""
            
            await self.application.bot.send_message(
                chat_id=user_id,
                text=reminder_message,
                reply_markup=reply_markup
            )
            
            logger.info(f"✅ Payment reminder sent to user {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Error sending payment reminder to user {user_id}: {e}")

    async def remove_user_after_trial(self, user_id, row_index=None):
        """הסרת משתמש מהערוץ לאחר סיום תקופת ניסיון ללא תשלום"""
        try:
            # הסרת המשתמש מהערוץ
            await self.application.bot.ban_chat_member(
                chat_id=CHANNEL_ID,
                user_id=user_id
            )
            
            # שליחת הודעת פרידה
            goodbye_message = """👋 תקופת הניסיון שלך הסתיימה

הוסרת מערוץ PeakTrade VIP מכיוון שלא חידשת את המנוי.

💡 תמיד אפשר לחזור ולהירשם שוב!
שלח /start כדי להתחיל מחדש.

תודה שניסית את השירות שלנו! 🙏
בהצלחה במסחר! 💪"""
            
            try:
                await self.application.bot.send_message(
                    chat_id=user_id,
                    text=goodbye_message
                )
            except:
                pass  # אם לא ניתן לשלוח הודעה פרטית
            
            # עדכון סטטוס ב-Google Sheets
            if row_index and self.sheet:
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                try:
                    self.sheet.update_cell(row_index, 8, "expired_no_payment")
                    self.sheet.update_cell(row_index, 11, current_time)
                except Exception as update_error:
                    logger.error(f"Error updating expiry status: {update_error}")
            
            logger.info(f"✅ User {user_id} removed after trial expiry")
            
        except Exception as e:
            logger.error(f"❌ Error removing user {user_id}: {e}")

    async def check_trial_expiry(self):
        """בדיקה יומית של סיום תקופת ניסיון"""
        try:
            if not self.sheet:
                return
            
            records = self.sheet.get_all_records()
            current_time = datetime.now()
            
            for i, record in enumerate(records):
                if record.get('payment_status') == 'trial_active':
                    trial_end_str = record.get('trial_end_date')
                    if trial_end_str:
                        try:
                            trial_end = datetime.strptime(trial_end_str, "%Y-%m-%d %H:%M:%S")
                            user_id = record.get('telegram_user_id')
                            
                            # יום לפני סיום הניסיון - שליחת תזכורת
                            if (trial_end - current_time).days == 1:
                                await self.send_trial_expiry_reminder(user_id)
                            
                            # יום אחרי סיום הניסיון - הסרת משתמש אם לא שילם
                            elif current_time > trial_end:
                                await self.remove_user_after_trial(user_id, i + 2)
                                
                        except ValueError:
                            logger.error(f"Invalid date format: {trial_end_str}")
            
            logger.info("✅ Trial expiry check completed")
            
        except Exception as e:
            logger.error(f"❌ Error checking trial expiry: {e}")

    async def handle_payment_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """טיפול בבחירת תשלום"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        choice = query.data
        
        if choice == "pay_yes":
            # המשתמש בחר לשלם
            keyboard = [
                [InlineKeyboardButton("💳 PayPal", url=PAYPAL_PAYMENT_LINK)],
                [InlineKeyboardButton("📱 Google Pay", callback_data="gpay_payment")],
                [InlineKeyboardButton("❌ ביטול", callback_data="pay_cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            payment_message = f"""💳 תשלום PeakTrade VIP

💰 מחיר: {MONTHLY_PRICE}₪/חודש
⏰ חיוב חודשי אוטומטי

📸 אחרי התשלום שלח צילום מסך
🚀 עסקה אחת ואתה משלש את ההשקעה!!

🔒 תשלום מאובטח דרך:

לחץ על אחת מהאפשרויות למטה:"""
            
            await query.edit_message_text(
                text=payment_message,
                reply_markup=reply_markup
            )
            
        elif choice == "pay_no":
            # המשתמש בחר לא לשלם
            goodbye_message = """👋 תודה שניסית את PeakTrade VIP!

הבנו שאתה לא מעוניין להמשיך כרגע.
תוסר מהערוץ הפרמיום מחר.

💡 תמיד אפשר לחזור ולהירשם שוב!
שלח /start כדי להתחיל מחדש.

תודה ובהצלחה! 🙏"""
            
            await query.edit_message_text(text=goodbye_message)
            
        elif choice == "gpay_payment":
            # Google Pay (לעתיד - כרגע הפניה ל-PayPal)
            await query.edit_message_text(
                text=f"📱 Google Pay זמין בקרוב!\n\nבינתיים אפשר לשלם דרך PayPal:\n{PAYPAL_PAYMENT_LINK}"
            )
            
        elif choice == "pay_cancel":
            # ביטול התשלום
            await query.edit_message_text(
                text="❌ התשלום בוטל.\n\nתקבל תזכורת נוספת מחר."
            )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת עזרה"""
        help_text = f"""🆘 PeakTrade VIP Bot - מדריך מהיר

📋 פקודות זמינות:
/start - הצטרפות לערוץ הפרמיום
/help - מדריך זה

💎 מה מיוחד בערוץ שלנו:
• המלצות מניות מנצחות
• גרפים מקצועיים בזמן אמת
• קהילת משקיעים פעילה

⏰ תקופת ניסיון: 7 ימים חינם
💰 מחיר מנוי: 120₪/חודש

🚀 הצטרף עכשיו ותתחיל להרוויח!"""
        
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
        self.application.add_handler(CallbackQueryHandler(self.handle_payment_choice))
        
        logger.info("✅ All handlers configured")

    async def send_guaranteed_stock_content(self):
        """שליחת תוכן מניה מקצועי"""
        try:
            logger.info("📈 Preparing stock content...")
            
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
                logger.warning(f"No data for {symbol}")
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
            
            # הודעה ידידותית ומקצועית
            caption = f"""🔥 {stock_type} {symbol} - המלצת השקעה חמה!

💎 סקטור: {sector} | מחיר נוכחי: ${current_price:.2f}

📊 ניתוח טכני מקצועי (30 ימים):
• טווח מחירים: ${low_30d:.2f} - ${high_30d:.2f}
• נפח מסחר ממוצע: {avg_volume:,.0f}
• נפח היום: {volume:,.0f}
• מומנטום: {'חיובי 📈' if change_percent > 0 else 'שלילי 📉'} ({change_percent:+.2f}%)

🎯 אסטרטגיית המסחר שלנו:
🟢 נקודת כניסה: ${entry_price:.2f}
🔴 סטופלוס מומלץ: ${stop_loss:.2f}
🎯 יעד ראשון: ${profit_target_1:.2f}
🚀 יעד שני: ${profit_target_2:.2f}

⚖️ יחס סיכון לתשואה: 1:{risk_reward:.1f}

💰 פוטנציאל רווח: ${reward:.2f} למניה
💸 סיכון מקסימלי: ${risk:.2f} למניה

🔥 זוהי המלצה בלעדית לחברי PeakTrade VIP!
🚀 עסקה אחת ואתה משלש את ההשקעה!

#PeakTradeVIP #{symbol} #HotStock

המידע לצרכי מידע בלבד • השקעה כרוכה בסיכון"""
            
            if chart_buffer:
                await self.application.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=chart_buffer,
                    caption=caption
                )
                logger.info(f"✅ Stock content sent for {symbol}")
            else:
                await self.application.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=caption
                )
                logger.info(f"✅ Stock content (text) sent for {symbol}")
            
        except Exception as e:
            logger.error(f"❌ Error sending stock content: {e}")

    async def send_text_analysis(self, symbol, asset_type):
        """שליחת ניתוח טקסט אם הגרף נכשל"""
        try:
            message = f"""{asset_type} 📈 {symbol} - המלצה חמה!

💰 מחיר נוכחי: מעודכן בזמן אמת
📊 ניתוח טכני מקצועי

🎯 המלצות המסחר שלנו:
🟢 כניסה מומלצת: +2% מהמחיר הנוכחי
🔴 סטופלוס חכם: -5% מהמחיר הנוכחי
🎯 יעד ראשון: +8% רווח יפה
🚀 יעד שני: +15% רווח מקסימלי

🔥 זוהי המלצה בלעדית לחברי VIP!
🚀 עסקה אחת ואתה משלש את ההשקעה!

#PeakTradeVIP #{symbol.replace('-USD', '').replace('.TA', '')} #HotStock

המידע לצרכי מידע בלבד • השקעה כרוכה בסיכון"""
            
            await self.application.bot.send_message(
                chat_id=CHANNEL_ID,
                text=message
            )
            
            logger.info(f"✅ Text analysis sent for {symbol}")
            
        except Exception as e:
            logger.error(f"❌ Error sending text analysis: {e}")

    async def run(self):
        """הפעלת הבוט עם שליחה מאולצת"""
        logger.info("🚀 Starting PeakTrade VIP Bot...")
        
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.setup_handlers()
        
        # הגדרת scheduler לבדיקת תפוגת ניסיונות
        self.scheduler = AsyncIOScheduler(timezone="Asia/Jerusalem")
        
        # בדיקה יומית בשעה 9:00 בבוקר
        self.scheduler.add_job(
            self.check_trial_expiry,
            CronTrigger(hour=9, minute=0),
            id='check_trial_expiry'
        )
        
        self.scheduler.start()
        logger.info("✅ Trial expiry scheduler configured")
        
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            logger.info("✅ PeakTrade VIP Bot is running successfully!")
            logger.info("📊 Content: Every 30 minutes between 10:00-22:00")
            logger.info("⏰ Trial expiry check: Daily at 9:00 AM")
            logger.info(f"💰 Monthly subscription: {MONTHLY_PRICE}₪")
            
            # שליחת הודעת בדיקה מיידית
            await asyncio.sleep(10)
            try:
                await self.send_guaranteed_stock_content()
                logger.info("✅ Immediate test sent")
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
                            logger.info(f"🕐 Forcing content at {current_time.strftime('%H:%M')}")
                            await self.send_guaranteed_stock_content()
                            last_send_time = current_time
                            logger.info("✅ Forced content sent successfully!")
                        except Exception as e:
                            logger.error(f"❌ Error in forced send: {e}")
                
                await asyncio.sleep(60)  # בדוק כל דקה
                
        except Exception as e:
            logger.error(f"❌ Bot error: {e}")
        finally:
            if self.scheduler:
                self.scheduler.shutdown()
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
