import logging
import os
import asyncio
import json
from datetime import datetime, timedelta
from telegram import Update
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
import html

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

# מצבי השיחה
WAITING_FOR_EMAIL = 1

class PeakTradeBot:
    def __init__(self):
        self.application = None
        self.scheduler = None
        self.google_client = None
        self.sheet = None
        self.setup_google_sheets()
    
    def escape_markdown(self, text):
        """הימנעות מתווים מיוחדים ב-Markdown"""
        if not text:
            return "N/A"
        # החלפת תווים מיוחדים
        escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in escape_chars:
            text = str(text).replace(char, f'\\{char}')
        return text
        
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
                
                # וידוא שיש כותרות בגיליון
                try:
                    headers = self.sheet.row_values(1)
                    if not headers:
                        header_row = [
                            'telegram_user_id', 'telegram_username', 'email', 
                            'disclaimer_sent_time', 'confirmation_status', 
                            'trial_start_date', 'trial_end_date', 'payment_status',
                            'gumroad_sale_id', 'gumroad_subscription_id', 'last_update_timestamp'
                        ]
                        self.sheet.append_row(header_row)
                        logger.info("✅ Headers added to Google Sheets")
                except Exception as e:
                    logger.error(f"❌ Error checking headers: {e}")
                
                logger.info("✅ Google Sheets connected successfully")
            else:
                logger.warning("⚠️ Google Sheets credentials not found")
        except Exception as e:
            logger.error(f"❌ Error setting up Google Sheets: {e}")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת התחלה עם disclaimer"""
        user = update.effective_user
        logger.info(f"User {user.id} ({user.username}) started PeakTrade bot")
        
        disclaimer_message = f"""
🏔️ <b>PeakTrade VIP | הצהרת אחריות</b>

שלום {html.escape(user.first_name)}! 👋

⚠️ <b>הצהרת ויתור אחריות:</b>
• המידע המוצג בערוץ הוא לצרכי חינוך בלבד
• אין זו המלצה להשקעה או ייעוץ פיננסי
• כל השקעה כרוכה בסיכון והפסדים אפשריים
• אתה נושא באחריות המלאה להחלטותיך

📈 <b>מה תקבל בערוץ PeakTrade VIP:</b>
• ניתוחים טכניים מתקדמים
• גרפי נרות בזמן אמת
• רעיונות מסחר ותובנות שוק
• תוכן ייחודי ומקצועי

⏰ <b>תקופת ניסיון: 7 ימים חינם</b>

✅ <b>להמשך, אנא שלח את כתובת האימייל שלך בפורמט:</b>
<code>your-email@example.com מאשר</code>

💡 <b>דוגמה:</b>
<code>john.doe@gmail.com מאשר</code>

<i>חשוב: השתמש באותו אימייל לתשלום עתידי!</i>
        """
        
        await update.message.reply_text(
            disclaimer_message,
            parse_mode='HTML'
        )
        
        await self.log_disclaimer_sent(user)
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
        
        logger.info(f"User {user.id} sent: {message_text}")
        
        if "מאשר" not in message_text:
            await update.message.reply_text(
                "❌ אנא שלח את האימייל בפורמט הנכון:\n"
                "<code>your-email@example.com מאשר</code>",
                parse_mode='HTML'
            )
            return WAITING_FOR_EMAIL
        
        email = message_text.replace("מאשר", "").strip()
        
        if "@" not in email or "." not in email:
            await update.message.reply_text(
                "❌ כתובת האימייל לא תקינה. אנא נסה שוב:\n"
                "<code>your-email@example.com מאשר</code>",
                parse_mode='HTML'
            )
            return WAITING_FOR_EMAIL
        
        processing_msg = await update.message.reply_text(
            "⏳ מעבד את הרישום לתקופת ניסיון...",
            parse_mode='HTML'
        )
        
        try:
            await self.register_trial_user(user, email)
            
            invite_link = await context.bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                expire_date=int((datetime.now() + timedelta(days=8)).timestamp()),
                name=f"Trial_{user.id}_{email.split('@')[0]}"
            )
            
            # הודעת הצלחה עם HTML במקום Markdown
            success_message = f"""
✅ <b>ברוך הבא ל-PeakTrade VIP!</b>

📧 <b>האימייל שלך:</b> <code>{html.escape(email)}</code>
👤 <b>משתמש:</b> @{html.escape(user.username or 'לא זמין')}
🆔 <b>מזהה:</b> <code>{user.id}</code>

🔗 <b>קישור הצטרפות לערוץ הפרמיום:</b>
{invite_link.invite_link}

⏰ <b>תקופת ניסיון:</b> 7 ימים
📅 <b>מתחיל:</b> {datetime.now().strftime("%d/%m/%Y")}
📅 <b>מסתיים:</b> {(datetime.now() + timedelta(days=7)).strftime("%d/%m/%Y")}

🎯 <b>מה תקבל בערוץ:</b>
• ניתוחים טכניים יומיים
• גרפי נרות בזמן אמת
• רעיונות מסחר מקצועיים
• תובנות שוק ייחודיות

💳 <i>לפני סיום תקופת הניסיון תקבל הודעה עם אפשרות להמשיך כמנוי בתשלום.</i>

<b>לחץ על הקישור והצטרף עכשיו! 🚀</b>
            """
            
            await processing_msg.edit_text(
                success_message,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
            
            logger.info(f"✅ Trial registration successful for user {user.id}")
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"❌ Error in trial registration: {e}")
            await processing_msg.edit_text(
                f"❌ שגיאה ברישום לתקופת ניסיון\n\n"
                f"פרטי השגיאה: <code>{html.escape(str(e))}</code>\n\n"
                f"אנא פנה לתמיכה.",
                parse_mode='HTML'
            )
            return ConversationHandler.END
    
    async def register_trial_user(self, user, email):
        """רישום משתמש לתקופת ניסיון ב-Google Sheets"""
        try:
            if not self.sheet:
                raise Exception("Google Sheets not connected")
            
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            trial_end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
            
            all_values = self.sheet.get_all_values()
            user_row = None
            
            for i, row in enumerate(all_values):
                if len(row) > 0 and str(row[0]) == str(user.id):
                    user_row = i + 1
                    break
            
            if user_row and user_row > 1:
                try:
                    logger.info(f"Updating existing user at row {user_row}")
                    
                    updates = [
                        (user_row, 3, email),
                        (user_row, 5, "confirmed"),
                        (user_row, 6, current_time),
                        (user_row, 7, trial_end),
                        (user_row, 8, "trial_active"),
                        (user_row, 11, current_time)
                    ]
                    
                    for row, col, value in updates:
                        try:
                            self.sheet.update_cell(row, col, value)
                        except Exception as update_error:
                            logger.error(f"Error updating cell ({row}, {col}): {update_error}")
                            raise Exception("Update failed, will create new row")
                    
                except Exception as update_error:
                    logger.warning(f"Failed to update existing row: {update_error}")
                    user_row = None
            
            if not user_row:
                logger.info("Adding new user row")
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
            
            logger.info(f"✅ User {user.id} registered for trial successfully")
            
        except Exception as e:
            logger.error(f"❌ Error registering trial user: {e}")
            raise Exception(f"Google Sheets error: {str(e)}")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת עזרה"""
        help_text = """
🆘 <b>PeakTrade VIP Bot - עזרה</b>

📋 <b>פקודות זמינות:</b>
/start - התחלת תהליך רישום
/help - הצגת עזרה זו

✅ <b>איך להצטרף:</b>
1. שלח /start
2. קרא את הצהרת האחריות
3. שלח את האימייל שלך + "מאשר"
4. קבל קישור לערוץ הפרמיום

⏰ <b>תקופת ניסיון:</b> 7 ימים חינם
💳 <b>תשלום:</b> דרך Gumroad (PayPal/כרטיס אשראי)

💬 <b>תמיכה:</b> פנה למנהל הערוץ
        """
        
        await update.message.reply_text(help_text, parse_mode='HTML')
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ביטול תהליך"""
        await update.message.reply_text(
            "❌ התהליך בוטל. שלח /start כדי להתחיל מחדש.",
            parse_mode='HTML'
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
    
    def setup_scheduler(self):
        """הגדרת תזמון משימות"""
        self.scheduler = AsyncIOScheduler()
        
        self.scheduler.add_job(
            self.check_trial_expiry,
            CronTrigger(hour=9, minute=0),
            id='check_trial_expiry'
        )
        
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
                        try:
                            trial_end = datetime.strptime(trial_end_str, "%Y-%m-%d %H:%M:%S")
                            
                            if current_time > trial_end:
                                user_id = record.get('telegram_user_id')
                                await self.handle_trial_expired(user_id, i + 2)
                            
                            elif (trial_end - current_time).days == 1:
                                user_id = record.get('telegram_user_id')
                                await self.send_payment_reminder(user_id)
                        except ValueError:
                            logger.error(f"Invalid date format: {trial_end_str}")
            
            logger.info("✅ Trial expiry check completed")
            
        except Exception as e:
            logger.error(f"❌ Error checking trial expiry: {e}")
    
    async def send_payment_reminder(self, user_id):
        """שליחת תזכורת תשלום"""
        try:
            reminder_message = """
⏰ <b>תזכורת: תקופת הניסיון מסתיימת מחר!</b>

היי! תקופת הניסיון של 7 ימים ב-PeakTrade VIP מסתיימת מחר.

💎 <b>כדי להמשיך ליהנות מהתוכן הפרמיום:</b>
🔗 לחץ כאן לרכישת מנוי: [קישור Gumroad]

💳 <b>תשלום מאובטח דרך:</b>
• PayPal
• כרטיס אשראי

⚠️ <b>חשוב:</b> השתמש באותו אימייל שרשמת איתו!

<i>תודה שאתה חלק מקהילת PeakTrade VIP! 🚀</i>
            """
            
            await self.application.bot.send_message(
                chat_id=user_id,
                text=reminder_message,
                parse_mode='HTML'
            )
            
            logger.info(f"✅ Payment reminder sent to user {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Error sending payment reminder to {user_id}: {e}")
    
    async def handle_trial_expired(self, user_id, row_index):
        """טיפול במשתמש שתקופת הניסיון שלו הסתיימה"""
        try:
            await self.application.bot.ban_chat_member(
                chat_id=CHANNEL_ID,
                user_id=user_id
            )
            
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                self.sheet.update_cell(row_index, 8, "expired_no_payment")
                self.sheet.update_cell(row_index, 11, current_time)
            except Exception as update_error:
                logger.error(f"Error updating expiry status: {update_error}")
            
            expiry_message = """
⏰ <b>תקופת הניסיון הסתיימה</b>

היי! תקופת הניסיון שלך ב-PeakTrade VIP הסתיימה.

💎 <b>רוצה להמשיך ליהנות מהתוכן הפרמיום?</b>
🔗 לחץ כאן לרכישת מנוי: [קישור Gumroad]

<i>תודה שניסית את PeakTrade VIP! 🙏</i>
            """
            
            await self.application.bot.send_message(
                chat_id=user_id,
                text=expiry_message,
                parse_mode='HTML'
            )
            
            logger.info(f"✅ Trial expired handled for user {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Error handling trial expiry for {user_id}: {e}")
    
    async def send_random_content(self):
        """שליחת תוכן אקראי לערוץ"""
        try:
            symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META', 'NFLX']
            symbol = random.choice(symbols)
            
            stock = yf.Ticker(symbol)
            data = stock.history(period="30d")
            
            if data.empty:
                return
            
            plt.style.use('dark_background')
            fig, ax = plt.subplots(figsize=(12, 8))
            
            mpf.plot(data, type='candle', style='charles', 
                    title=f'{symbol} - 30 Days Chart',
                    ylabel='Price ($)',
                    ax=ax)
            
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight')
            buffer.seek(0)
            plt.close()
            
            current_price = data['Close'].iloc[-1]
            change = data['Close'].iloc[-1] - data['Close'].iloc[-2]
            change_percent = (change / data['Close'].iloc[-2]) * 100
            
            caption = f"""
📈 <b>{symbol} - ניתוח טכני</b>

💰 <b>מחיר נוכחי:</b> ${current_price:.2f}
📊 <b>שינוי יומי:</b> {change:+.2f} ({change_percent:+.2f}%)

🔍 <b>תובנות:</b>
• מגמה: {'עלייה' if change > 0 else 'ירידה'}
• נפח מסחר: {'גבוה' if random.choice([True, False]) else 'נמוך'}

⚡ <i>זה לא ייעוץ השקעה - לצרכי חינוך בלבד</i>

#PeakTradeVIP #{symbol}
            """
            
            await self.application.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=buffer,
                caption=caption,
                parse_mode='HTML'
            )
            
            logger.info(f"✅ Random content sent for {symbol}")
            
        except Exception as e:
            logger.error(f"❌ Error sending random content: {e}")
    
    async def run(self):
        """הפעלת הבוט"""
        logger.info("🚀 Starting PeakTrade VIP Bot (Background Worker)...")
        
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.setup_handlers()
        self.setup_scheduler()
        
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            logger.info("✅ PeakTrade VIP Bot is running successfully!")
            
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

if __name__ == "__main__":
    bot = PeakTradeBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
