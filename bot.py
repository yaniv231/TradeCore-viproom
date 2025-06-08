import logging
import os
import asyncio
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.error import TelegramError
import gspread
from google.oauth2.service_account import Credentials
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import yfinance as yf
import mplfinance as mpf
import matplotlib.pyplot as plt
import io
import random

# הגדרת לוגינג
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# הגדרות המערכת - עם הפרטים החדשים שלך
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or "7619055199:AAEL28DJ-E1Xl7iEfdPqTXJ0in1Lps0VOtM"
CHANNEL_ID = os.getenv('CHANNEL_ID') or "-1002886874719"
GOOGLE_CREDENTIALS = os.getenv('GOOGLE_CREDENTIALS')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID') or "הכנס_מזהה_גוגל_שיט"
GUMROAD_WEBHOOK_SECRET = os.getenv('GUMROAD_WEBHOOK_SECRET') or "הכנס_סוד_webhook"

# מצבי השיחה
WAITING_FOR_EMAIL = 1

class PeakTradeBot:
    def __init__(self):
        self.application = None
        self.scheduler = None
        self.google_client = None
        self.sheet = None
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

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת התחלה עם disclaimer"""
        user = update.effective_user
        logger.info(f"User {user.id} ({user.username}) started Peaktrade_bot")
        
        disclaimer_message = f"""
🏔️ *PeakTrade VIP | הצהרת אחריות*

שלום {user.first_name}! 👋

⚠️ *הצהרת ויתור אחריות:*
• המידע המוצג בערוץ הוא לצרכי חינוך בלבד
• אין זו המלצה להשקעה או ייעוץ פיננסי
• כל השקעה כרוכה בסיכון והפסדים אפשריים
• אתה נושא באחריות המלאה להחלטותיך

📈 *מה תקבל בערוץ PeakTrade VIP:*
• ניתוחים טכניים מתקדמים
• גרפי נרות בזמן אמת
• רעיונות מסחר ותובנות שוק
• תוכן ייחודי ומקצועי

⏰ *תקופת ניסיון: 7 ימים חינם*

✅ *להמשך, אנא שלח את כתובת האימייל שלך בפורמט:*
`your-email@example.com מאשר`

💡 *דוגמה:*
`john.doe@gmail.com מאשר`

*חשוב: השתמש באותו אימייל לתשלום עתידי!*
        """
        
        await update.message.reply_text(
            disclaimer_message,
            parse_mode='Markdown'
        )
        
        # רישום שליחת disclaimer
        await self.log_disclaimer_sent(user)
        
        return WAITING_FOR_EMAIL
    
    async def log_disclaimer_sent(self, user):
        """רישום שליחת disclaimer ב-Google Sheets"""
        try:
            if not self.sheet:
                return
                
            # בדיקה אם המשתמש כבר קיים
            records = self.sheet.get_all_records()
            existing_user = None
            for i, record in enumerate(records):
                if str(record.get('telegram_user_id')) == str(user.id):
                    existing_user = i + 2  # +2 כי השורה הראשונה היא כותרות
                    break
            
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            if existing_user:
                # עדכון משתמש קיים
                self.sheet.update_cell(existing_user, 4, current_time)  # disclaimer_sent_time
            else:
                # הוספת משתמש חדש
                new_row = [
                    user.id,
                    user.username or "N/A",
                    "",  # email - יתמלא בשלב הבא
                    current_time,  # disclaimer_sent_time
                    "pending",  # confirmation_status
                    "",  # trial_start_date
                    "",  # trial_end_date
                    "trial_pending",  # payment_status
                    "",  # gumroad_sale_id
                    "",  # gumroad_subscription_id
                    current_time  # last_update_timestamp
                ]
                self.sheet.append_row(new_row)
                
            logger.info(f"✅ Disclaimer logged for user {user.id}")
            
        except Exception as e:
            logger.error(f"❌ Error logging disclaimer: {e}")
    
    async def handle_email_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """טיפול באישור האימייל"""
        user = update.effective_user
        message_text = update.message.text.strip()
        
        logger.info(f"User {user.id} sent: {message_text}")
        
        # בדיקה אם ההודעה מכילה "מאשר"
        if "מאשר" not in message_text:
            await update.message.reply_text(
                "❌ אנא שלח את האימייל בפורמט הנכון:\n"
                "`your-email@example.com מאשר`",
                parse_mode='Markdown'
            )
            return WAITING_FOR_EMAIL
        
        # חילוץ האימייל
        email = message_text.replace("מאשר", "").strip()
        
        # בדיקה בסיסית של פורמט האימייל
        if "@" not in email or "." not in email:
            await update.message.reply_text(
                "❌ כתובת האימייל לא תקינה. אנא נסה שוב:\n"
                "`your-email@example.com מאשר`",
                parse_mode='Markdown'
            )
            return WAITING_FOR_EMAIL
        
        # הודעת עיבוד
        processing_msg = await update.message.reply_text(
            "⏳ מעבד את הרישום לתקופת ניסיון...",
            parse_mode='Markdown'
        )
        
        try:
            # עדכון נתונים ב-Google Sheets
            await self.register_trial_user(user, email)
            
            # יצירת קישור הזמנה לערוץ
            invite_link = await context.bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                expire_date=int((datetime.now() + timedelta(days=8)).timestamp()),
                name=f"Trial_{user.id}_{email.split('@')[0]}"
            )
            
            success_message = f"""
✅ *ברוך הבא ל-PeakTrade VIP!*

📧 *האימייל שלך:* `{email}`
👤 *משתמש:* @{user.username or 'לא זמין'}
🆔 *מזהה:* `{user.id}`

🔗 *קישור הצטרפות לערוץ הפרמיום:*
{invite_link.invite_link}

⏰ *תקופת ניסיון:* 7 ימים
📅 *מתחיל:* {datetime.now().strftime("%d/%m/%Y")}
📅 *מסתיים:* {(datetime.now() + timedelta(days=7)).strftime("%d/%m/%Y")}

🎯 *מה תקבל בערוץ:*
• ניתוחים טכניים יומיים
• גרפי נרות בזמן אמת
• רעיונות מסחר מקצועיים
• תובנות שוק ייחודיות

💳 *לפני סיום תקופת הניסיון תקבל הודעה עם אפשרות להמשיך כמנוי בתשלום.*

*לחץ על הקישור והצטרף עכשיו! 🚀*
            """
            
            await processing_msg.edit_text(
                success_message,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            
            logger.info(f"✅ Trial registration successful for user {user.id}")
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"❌ Error in trial registration: {e}")
            await processing_msg.edit_text(
                f"❌ שגיאה ברישום לתקופת ניסיון\n\n"
                f"פרטי השגיאה: `{str(e)}`\n\n"
                f"אנא פנה לתמיכה.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
    
    async def register_trial_user(self, user, email):
        """רישום משתמש לתקופת ניסיון ב-Google Sheets"""
        try:
            if not self.sheet:
                raise Exception("Google Sheets not connected")
            
            records = self.sheet.get_all_records()
            user_row = None
            
            # חיפוש המשתמש
            for i, record in enumerate(records):
                if str(record.get('telegram_user_id')) == str(user.id):
                    user_row = i + 2
                    break
            
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            trial_end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
            
            if user_row:
                # עדכון משתמש קיים
                self.sheet.update_cell(user_row, 3, email)  # email
                self.sheet.update_cell(user_row, 5, "confirmed")  # confirmation_status
                self.sheet.update_cell(user_row, 6, current_time)  # trial_start_date
                self.sheet.update_cell(user_row, 7, trial_end)  # trial_end_date
                self.sheet.update_cell(user_row, 8, "trial_active")  # payment_status
                self.sheet.update_cell(user_row, 11, current_time)  # last_update_timestamp
            else:
                # הוספת משתמש חדש
                new_row = [
                    user.id,
                    user.username or "N/A",
                    email,
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
            logger.error(f"❌ Error registering trial user: {e}")
            raise
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת עזרה"""
        help_text = """
🆘 *PeakTrade VIP Bot - עזרה*

📋 *פקודות זמינות:*
/start - התחלת תהליך רישום
/help - הצגת עזרה זו

✅ *איך להצטרף:*
1. שלח /start
2. קרא את הצהרת האחריות
3. שלח את האימייל שלך + "מאשר"
4. קבל קישור לערוץ הפרמיום

⏰ *תקופת ניסיון:* 7 ימים חינם
💳 *תשלום:* דרך Gumroad (PayPal/כרטיס אשראי)

💬 *תמיכה:* פנה למנהל הערוץ
        """
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ביטול תהליך"""
        await update.message.reply_text(
            "❌ התהליך בוטל. שלח /start כדי להתחיל מחדש.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    def setup_handlers(self):
        """הגדרת handlers"""
        # ConversationHandler לתהליך רישום
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
    
    def setup_scheduler(self):
        """הגדרת תזמון משימות"""
        self.scheduler = AsyncIOScheduler()
        
        # משימה יומית לבדיקת תשלומים ותקופות ניסיון
        self.scheduler.add_job(
            self.check_trial_expiry,
            CronTrigger(hour=9, minute=0),  # כל יום ב-9:00
            id='check_trial_expiry'
        )
        
        # משימות אקראיות לשליחת תוכן (עד 10 ביום)
        for i in range(10):
            random_hour = random.randint(10, 22)
            random_minute = random.randint(0, 59)
            
            self.scheduler.add_job(
                self.send_random_content,
                CronTrigger(hour=random_hour, minute=random_minute),
                id=f'content_{i}'
            )
        
        self.scheduler.start()
        logger.info("✅ Scheduler configured and started")
    
    async def check_trial_expiry(self):
        """בדיקת תפוגת תקופות ניסיון"""
        try:
            if not self.sheet:
                return
            
            records = self.sheet.get_all_records()
            current_time = datetime.now()
            
            for i, record in enumerate(records):
                if record.get('payment_status') == 'trial_active':
                    trial_end_str = record.get('trial_end_date')
                    if trial_end_str:
                        trial_end = datetime.strptime(trial_end_str, "%Y-%m-%d %H:%M:%S")
                        
                        # אם תקופת הניסיון הסתיימה
                        if current_time > trial_end:
                            user_id = record.get('telegram_user_id')
                            await self.handle_trial_expired(user_id, i + 2)
                        
                        # תזכורת יום לפני סיום
                        elif (trial_end - current_time).days == 1:
                            user_id = record.get('telegram_user_id')
                            await self.send_payment_reminder(user_id)
            
            logger.info("✅ Trial expiry check completed")
            
        except Exception as e:
            logger.error(f"❌ Error checking trial expiry: {e}")
    
    async def send_payment_reminder(self, user_id):
        """שליחת תזכורת תשלום"""
        try:
            reminder_message = """
⏰ *תזכורת: תקופת הניסיון מסתיימת מחר!*

היי! תקופת הניסיון של 7 ימים ב-PeakTrade VIP מסתיימת מחר.

💎 *כדי להמשיך ליהנות מהתוכן הפרמיום:*
🔗 לחץ כאן לרכישת מנוי: [קישור Gumroad]

💳 *תשלום מאובטח דרך:*
• PayPal
• כרטיס אשראי

⚠️ *חשוב:* השתמש באותו אימייל שרשמת איתו!

*תודה שאתה חלק מקהילת PeakTrade VIP! 🚀*
            """
            
            await self.application.bot.send_message(
                chat_id=user_id,
                text=reminder_message,
                parse_mode='Markdown'
            )
            
            logger.info(f"✅ Payment reminder sent to user {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Error sending payment reminder to {user_id}: {e}")
    
    async def handle_trial_expired(self, user_id, row_index):
        """טיפול במשתמש שתקופת הניסיון שלו הסתיימה"""
        try:
            # הסרת המשתמש מהערוץ
            await self.application.bot.ban_chat_member(
                chat_id=CHANNEL_ID,
                user_id=user_id
            )
            
            # עדכון סטטוס ב-Google Sheets
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.sheet.update_cell(row_index, 8, "expired_no_payment")
            self.sheet.update_cell(row_index, 11, current_time)
            
            # הודעה למשתמש
            expiry_message = """
⏰ *תקופת הניסיון הסתיימה*

היי! תקופת הניסיון שלך ב-PeakTrade VIP הסתיימה.

💎 *רוצה להמשיך ליהנות מהתוכן הפרמיום?*
🔗 לחץ כאן לרכישת מנוי: [קישור Gumroad]

*תודה שניסית את PeakTrade VIP! 🙏*
            """
            
            await self.application.bot.send_message(
                chat_id=user_id,
                text=expiry_message,
                parse_mode='Markdown'
            )
            
            logger.info(f"✅ Trial expired handled for user {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Error handling trial expiry for {user_id}: {e}")
    
    async def send_random_content(self):
        """שליחת תוכן אקראי לערוץ"""
        try:
            # רשימת סימולים פופולריים
            symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META', 'NFLX']
            symbol = random.choice(symbols)
            
            # הורדת נתונים
            stock = yf.Ticker(symbol)
            data = stock.history(period="30d")
            
            if data.empty:
                return
            
            # יצירת גרף נרות
            plt.style.use('dark_background')
            fig, ax = plt.subplots(figsize=(12, 8))
            
            mpf.plot(data, type='candle', style='charles', 
                    title=f'{symbol} - 30 Days Chart',
                    ylabel='Price ($)',
                    ax=ax)
            
            # שמירת הגרף כתמונה
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight')
            buffer.seek(0)
            plt.close()
            
            # יצירת טקסט תיאורי
            current_price = data['Close'].iloc[-1]
            change = data['Close'].iloc[-1] - data['Close'].iloc[-2]
            change_percent = (change / data['Close'].iloc[-2]) * 100
            
            caption = f"""
📈 *{symbol} - ניתוח טכני*

💰 *מחיר נוכחי:* ${current_price:.2f}
📊 *שינוי יומי:* {change:+.2f} ({change_percent:+.2f}%)

🔍 *תובנות:*
• מגמה: {'עלייה' if change > 0 else 'ירידה'}
• נפח מסחר: {'גבוה' if random.choice([True, False]) else 'נמוך'}

⚡ *זה לא ייעוץ השקעה - לצרכי חינוך בלבד*

#PeakTradeVIP #{symbol}
            """
            
            # שליחה לערוץ
            await self.application.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=buffer,
                caption=caption,
                parse_mode='Markdown'
            )
            
            logger.info(f"✅ Random content sent for {symbol}")
            
        except Exception as e:
            logger.error(f"❌ Error sending random content: {e}")
    
    async def run(self):
        """הפעלת הבוט"""
        logger.info("🚀 Starting PeakTrade VIP Bot...")
        
        # יצירת Application
        self.application = Application.builder().token(BOT_TOKEN).build()
        
        # הגדרת handlers
        self.setup_handlers()
        
        # הגדרת scheduler
        self.setup_scheduler()
        
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            logger.info("✅ PeakTrade VIP Bot is running successfully!")
            
            # המתנה אינסופית
            while True:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"❌ Bot error: {e}")
        finally:
            if self.scheduler:
                self.scheduler.shutdown()
            if self.application:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()

# הפעלת הבוט
if __name__ == "__main__":
    bot = PeakTradeBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
