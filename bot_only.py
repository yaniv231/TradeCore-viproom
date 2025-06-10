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
import yfinance as yf
import matplotlib.pyplot as plt
import io
import random

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

# הגדרות תשלום
PAYPAL_PAYMENT_LINK = "https://paypal.me/yourpaypal/120"
MONTHLY_PRICE = 120

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
            
            ax.text(0.02, 0.02, 'Exclusive Signal', transform=ax.transAxes, 
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
            
            logger.info(f"✅ Professional chart created for {symbol} with specific prices")
            return buffer
            
        except Exception as e:
            logger.error(f"❌ Error creating professional chart: {e}")
            return None

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
• ניתוחים טכניים מתקדמים
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
            await self.register_trial_user(user, email)
            
            invite_link = await context.bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                expire_date=int((datetime.now() + timedelta(days=8)).timestamp()),
                name=f"Trial_{user.id}_{email.split('@')[0]}"
            )
            
            success_message = f"""✅ ברוך הבא ל-PeakTrade VIP!

📧 האימייל שלך: {email}
👤 משתמש: @{user.username or 'לא זמין'}
🆔 מזהה: {user.id}

🔗 קישור הצטרפות לערוץ הפרמיום:
{invite_link.invite_link}

⏰ תקופת ניסיון: 7 ימים
📅 מתחיל: {datetime.now().strftime("%d/%m/%Y")}
📅 מסתיים: {(datetime.now() + timedelta(days=7)).strftime("%d/%m/%Y")}

🎯 מה תקבל בערוץ:
• הודעות כל 30 דקות בין 10:00-22:00
• ניתוחים טכניים מתקדמים
• גרפי נרות בזמן אמת עם סטופלוס
• המלצות אמריקאיות וישראליות
• תובנות שוק ייחודיות

💳 לפני סיום תקופת הניסיון תקבל הודעה עם אפשרות להמשיך כמנוי בתשלום.

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
                f"פרטי השגיאה: {str(e)}\n\n"
                f"אנא פנה לתמיכה."
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

    async def handle_payment_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """טיפול בבחירת תשלום"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        choice = query.data
        
        if choice == "pay_yes":
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
            await self.handle_trial_expired(user_id, None)
            
            goodbye_message = """👋 תודה שניסית את PeakTrade VIP!

הוסרת מהערוץ הפרמיום.

💡 תמיד אפשר לחזור ולהירשם שוב!
שלח /start כדי להתחיל מחדש.

תודה ובהצלחה! 🙏"""
            
            await query.edit_message_text(text=goodbye_message)
            
        elif choice == "gpay_payment":
            await query.edit_message_text(
                text=f"📱 Google Pay זמין בקרוב!\n\nבינתיים אפשר לשלם דרך PayPal:\n{PAYPAL_PAYMENT_LINK}"
            )
            
        elif choice == "pay_cancel":
            await query.edit_message_text(
                text="❌ התשלום בוטל.\n\nתקבל תזכורת נוספת מחר."
            )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת עזרה"""
        help_text = f"""🆘 PeakTrade VIP Bot - עזרה

📋 פקודות זמינות:
/start - התחלת תהליך רישום
/help - הצגת עזרה זו

✅ איך להצטרף:
1. שלח /start
2. קרא את הצהרת האחריות
3. שלח את האימייל שלך + "מאשר"
4. קבל קישור לערוץ הפרמיום

⏰ תקופת ניסיון: 7 ימים חינם
💰 מחיר מנוי: {MONTHLY_PRICE}₪/חודש

🎯 מה תקבל:
• הודעות כל 30 דקות בין 10:00-22:00
• ניתוחים טכניים מתקדמים
• גרפי נרות עם סטופלוס מומלץ
• המלצות מניות אמריקאיות וישראליות
• המלצות קריפטו מובילות

💳 תשלום דרך:
• PayPal (זמין עכשיו)
• Google Pay (בקרוב)

💬 תמיכה: פנה למנהל הערוץ"""
        
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

    async def send_immediate_test_message(self):
        """שליחת הודעת בדיקה מיידית עם גרף"""
        try:
            logger.info("🧪 Attempting to send immediate test message with chart...")
            
            # יצירת דוגמה עם AAPL
            stock = yf.Ticker("AAPL")
            data = stock.history(period="30d")
            
            if not data.empty:
                current_price = data['Close'][-1]
                entry_price = current_price * 1.02  # כניסה 2% מעל
                stop_loss = current_price * 0.95    # סטופלוס 5% מתחת
                target1 = current_price * 1.08      # יעד ראשון 8%
                target2 = current_price * 1.15      # יעד שני 15%
                
                # יצירת גרף מקצועי
                chart_buffer = self.create_professional_chart_with_prices("AAPL", data, current_price, entry_price, stop_loss, target1, target2)
                
                if chart_buffer:
                    caption = f"""🔥 🇺🇸 אמריקאית AAPL - בדיקת מערכת PeakTrade VIP

💎 סקטור: טכנולוגיה | מחיר נוכחי: ${current_price:.2f}

🧪 זוהי הודעת בדיקה לוודא שהמערכת עובדת!

🎯 אסטרטגיית כניסה LIVE:
🟢 כניסה: ${entry_price:.2f} (+2% מהמחיר הנוכחי)
🔴 סטופלוס: ${stop_loss:.2f} (-5% הגנה)
🎯 יעד ראשון: ${target1:.2f} (+8% רווח)
🚀 יעד שני: ${target2:.2f} (+15% רווח)

💰 פוטנציאל רווח: ${target1 - entry_price:.2f} למניה
💸 סיכון מקסימלי: ${entry_price - stop_loss:.2f} למניה

✅ המערכת פועלת בהצלחה!
📊 הודעות כל 30 דקות בין 10:00-22:00
💰 מחיר מנוי: 120₪/חודש
🚀 עסקה אחת ואתה משלש את ההשקעה!!

⚠️ זוהי הודעת בדיקה - המערכת מוכנה לפעולה!

#PeakTradeVIP #TestMessage #SystemCheck"""
                    
                    await self.application.bot.send_photo(
                        chat_id=CHANNEL_ID,
                        photo=chart_buffer,
                        caption=caption
                    )
                    
                    logger.info("✅ Immediate test with chart sent successfully!")
                else:
                    await self.send_immediate_test_text()
            else:
                await self.send_immediate_test_text()
                
        except Exception as e:
            logger.error(f"❌ Error sending immediate test with chart: {e}")
            await self.send_immediate_test_text()

    async def send_immediate_test_text(self):
        """שליחת הודעת בדיקה טקסט אם הגרף נכשל"""
        try:
            test_message = """🧪 בדיקת מערכת PeakTrade VIP

✅ הבוט פעיל ועובד מושלם!
📊 מערכת תזמון פועלת
⏰ הודעות כל 30 דקות בין 10:00-22:00

🎯 מה תקבלו:
• גרפי נרות מקצועיים עם מחירים ספציפיים
• נקודות כניסה ויציאה מדויקות
• המלצות בלעדיות לחברי VIP
• ניתוח טכני מתקדם

💰 מחיר מנוי: 120₪/חודש
🚀 עסקה אחת ואתה משלש את ההשקעה!!

⚠️ זוהי הודעת בדיקה - המערכת מוכנה לפעולה!

#TestMessage #PeakTradeVIP #SystemReady"""
            
            await self.application.bot.send_message(
                chat_id=CHANNEL_ID,
                text=test_message
            )
            
            logger.info("✅ Immediate test text sent successfully!")
            
        except Exception as e:
            logger.error(f"❌ Error sending immediate test text: {e}")

    async def send_scheduled_content(self):
        """שליחת תוכן מתוזמן - מניה או קריפטו"""
        try:
            logger.info("📊 Sending scheduled content...")
            
            # בחירה אקראית בין מניה לקריפטו
            content_type = random.choice(['stock', 'crypto'])
            
            if content_type == 'stock':
                await self.send_guaranteed_stock_content()
            else:
                await self.send_guaranteed_crypto_content()
                
        except Exception as e:
            logger.error(f"❌ Error sending scheduled content: {e}")

    async def send_guaranteed_stock_content(self):
        """שליחת תוכן מניה מקצועי עם גרף ומחירים ספציפיים"""
        try:
            logger.info("📈 Preparing stock content with specific prices...")
            
            # מניות פופולריות עם פוטנציאל רווח
            premium_stocks = [
                {'symbol': 'AAPL', 'type': '🇺🇸 אמריקאית', 'sector': 'טכנולוגיה'},
                {'symbol': 'MSFT', 'type': '🇺🇸 אמריקאית', 'sector': 'טכנולוגיה'},
                {'symbol': 'GOOGL', 'type': '🇺🇸 אמריקאית', 'sector': 'טכנולוגיה'},
                {'symbol': 'TSLA', 'type': '🇺🇸 אמריקאית', 'sector': 'רכב חשמלי'},
                {'symbol': 'NVDA', 'type': '🇺🇸 אמריקאית', 'sector': 'AI/שבבים'},
                {'symbol': 'CHKP', 'type': '🇮🇱 ישראלית (נאסד"ק)', 'sector': 'סייבר'},
                {'symbol': 'NICE', 'type': '🇮🇱 ישראלית (נאסד"ק)', 'sector': 'תוכנה'},
                {'symbol': 'WIX', 'type': '🇮🇱 ישראלית (נאסד"ק)', 'sector': 'אינטרנט'}
            ]
            
            selected = random.choice(premium_stocks)
            symbol = selected['symbol']
            stock_type = selected['type']
            sector = selected['sector']
            
            # קבלת נתונים מפורטים
            stock = yf.Ticker(symbol)
            data = stock.history(period="30d")
            
            if data.empty:
                logger.warning(f"No data for {symbol}")
                return
            
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
            
            currency = "₪" if symbol.endswith('.TA') else "$"
            
            # תוכן בלעדי ומקצועי עם מחירים ספציפיים
            caption = f"""🔥 {stock_type} {symbol} - המלצת השקעה בלעדית

💎 סקטור: {sector} | מחיר נוכחי: {currency}{current_price:.2f}

📊 ניתוח טכני מתקדם (30 ימים):
• טווח: {currency}{low_30d:.2f} - {currency}{high_30d:.2f}
• נפח ממוצע: {avg_volume:,.0f} | היום: {volume:,.0f}
• מומנטום: {'חיובי 📈' if change_percent > 0 else 'שלילי 📉'} ({change_percent:+.2f}%)

🎯 אסטרטגיית כניסה LIVE - מחירים ספציפיים:
🟢 כניסה: {currency}{entry_price:.2f} (מעל המחיר הנוכחי)
🔴 סטופלוס: {currency}{stop_loss:.2f} (הגנה מפני הפסדים)
🎯 יעד ראשון: {currency}{profit_target_1:.2f} (רווח ראשון)
🚀 יעד שני: {currency}{profit_target_2:.2f} (רווח מקסימלי)

⚖️ יחס סיכון/תשואה: 1:{risk_reward:.1f}

💡 המלצה בלעדית PeakTrade:
{"🔥 כניסה מומלצת - מגמה חזקה!" if change_percent > 2 else "⚡ המתן לפריצה מעל נקודת הכניסה" if change_percent > 0 else "⏳ המתן לייצוב לפני כניסה"}

📈 אסטרטגיית יציאה:
• מכור 50% ב-{currency}{profit_target_1:.2f} (יעד ראשון)
• מכור 50% ב-{currency}{profit_target_2:.2f} (יעד שני)
• הזז סטופלוס ל-{currency}{entry_price:.2f} אחרי יעד ראשון

💰 פוטנציאל רווח: {currency}{reward:.2f} למניה
💸 סיכון מקסימלי: {currency}{risk:.2f} למניה

⚠️ זוהי המלצה בלעדית לחברי PeakTrade VIP בלבד
🚀 עסקה אחת ואתה משלש את ההשקעה!!

#PeakTradeVIP #{symbol} #ExclusiveSignal #LiveAnalysis"""
            
            if chart_buffer:
                await self.application.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=chart_buffer,
                    caption=caption
                )
                logger.info(f"✅ Professional stock content with chart and specific prices sent for {symbol}")
            else:
                await self.application.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=caption
                )
                logger.info(f"✅ Professional stock content (text only) sent for {symbol}")
            
        except Exception as e:
            logger.error(f"❌ Error sending professional stock content: {e}")

    async def send_guaranteed_crypto_content(self):
        """שליחת תוכן קריפטו מקצועי עם גרף ומחירים ספציפיים"""
        try:
            logger.info("🪙 Preparing crypto content with specific prices...")
            
            # קריפטו עם פוטנציאל רווח גבוה
            premium_crypto = [
                {'symbol': 'BTC-USD', 'name': 'Bitcoin', 'type': '👑 מלך הקריפטו'},
                {'symbol': 'ETH-USD', 'name': 'Ethereum', 'type': '⚡ פלטפורמת חכמה'},
                {'symbol': 'SOL-USD', 'name': 'Solana', 'type': '🚀 בלוקצ\'יין מהיר'},
                {'symbol': 'XRP-USD', 'name': 'Ripple', 'type': '🏦 תשלומים בנקאיים'},
                {'symbol': 'BNB-USD', 'name': 'Binance', 'type': '🔥 טוקן בורסה'},
                {'symbol': 'ADA-USD', 'name': 'Cardano', 'type': '🌱 ירוק ומתקדם'},
                {'symbol': 'AVAX-USD', 'name': 'Avalanche', 'type': '❄️ מהיר וזול'}
            ]
            
            selected = random.choice(premium_crypto)
            symbol = selected['symbol']
            crypto_name = selected['name']
            crypto_type = selected['type']
            
            # קבלת נתונים מפורטים
            crypto = yf.Ticker(symbol)
            data = crypto.history(period="30d")
            
            if data.empty:
                logger.warning(f"No data for {symbol}")
                return
            
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

📊 ניתוח קריפטו מתקדם (30 ימים):
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

#PeakTradeVIP #{crypto_name} #CryptoSignal #ExclusiveAlert"""
            
            if chart_buffer:
                await self.application.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=chart_buffer,
                    caption=caption
                )
                logger.info(f"✅ Professional crypto content with chart and specific prices sent for {symbol}")
            else:
                await self.application.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=caption
                )
                logger.info(f"✅ Professional crypto content (text only) sent for {symbol}")
            
        except Exception as e:
            logger.error(f"❌ Error sending professional crypto content: {e}")

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
                            
                            # יום לפני סיום הניסיון
                            if (trial_end - current_time).days == 1:
                                user_id = record.get('telegram_user_id')
                                await self.send_payment_reminder(user_id)
                            
                            # ניסיון הסתיים
                            elif current_time > trial_end:
                                user_id = record.get('telegram_user_id')
                                await self.handle_trial_expired(user_id, i + 2)
                                
                        except ValueError:
                            logger.error(f"Invalid date format: {trial_end_str}")
            
            logger.info("✅ Trial expiry check completed")
            
        except Exception as e:
            logger.error(f"❌ Error checking trial expiry: {e}")
    
    async def send_payment_reminder(self, user_id):
        """שליחת תזכורת תשלום עם כפתורים"""
        try:
            keyboard = [
                [InlineKeyboardButton("💎 כן - אני רוצה להמשיך!", callback_data="pay_yes")],
                [InlineKeyboardButton("❌ לא תודה", callback_data="pay_no")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            reminder_message = f"""⏰ תקופת הניסיון מסתיימת מחר!

היי! תקופת הניסיון של 7 ימים ב-PeakTrade VIP מסתיימת מחר.

💎 רוצה להמשיך ליהנות מהתוכן הפרמיום?
• הודעות כל 30 דקות עם גרפים מקצועיים
• מחירי כניסה ויציאה ספציפיים
• ניתוחים טכניים מתקדמים
• מניות ישראליות ואמריקאיות
• המלצות קריפטו

💰 מחיר: {MONTHLY_PRICE}₪/חודש
💳 תשלום מאובטח דרך PayPal

⚠️ מי שלא מחדש – מוסר אוטומטית.
📸 אחרי התשלום שלח צילום מסך

🚀 עסקה אחת ואתה משלש את ההשקעה!!

מה תבחר?"""
            
            await self.application.bot.send_message(
                chat_id=user_id,
                text=reminder_message,
                reply_markup=reply_markup
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
            if row_index and self.sheet:
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                try:
                    self.sheet.update_cell(row_index, 8, "expired_no_payment")
                    self.sheet.update_cell(row_index, 11, current_time)
                except Exception as update_error:
                    logger.error(f"Error updating expiry status: {update_error}")
            
            logger.info(f"✅ Trial expired handled for user {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Error handling trial expiry for {user_id}: {e}")

    def setup_scheduler(self):
        """הגדרת תזמון משימות - הודעה כל 30 דקות + בדיקה מיידית"""
        try:
            self.scheduler = AsyncIOScheduler(timezone="Asia/Jerusalem")
            
            # בדיקת תפוגת ניסיונות
            self.scheduler.add_job(
                self.check_trial_expiry,
                CronTrigger(hour=9, minute=0),
                id='check_trial_expiry'
            )
            
            # שליחת הודעה כל 30 דקות בין 10:00-22:00
            for hour in range(10, 23):
                for minute in [0, 30]:
                    if hour == 22 and minute == 30:  # לא לשלוח ב-22:30
                        break
                        
                    self.scheduler.add_job(
                        self.send_scheduled_content,
                        CronTrigger(hour=hour, minute=minute),
                        id=f'content_{hour}_{minute}'
                    )
            
            # הודעת בדיקה מיידית (30 שניות אחרי הפעלה)
            test_time = datetime.now() + timedelta(seconds=30)
            self.scheduler.add_job(
                self.send_immediate_test_message,
                'date',
                run_date=test_time,
                id='immediate_test'
            )
            
            self.scheduler.start()
            logger.info("✅ Scheduler configured: Message every 30 minutes + immediate test in 30 seconds")
            
        except Exception as e:
            logger.error(f"❌ Error setting up scheduler: {e}")

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
            logger.info("📊 Content: Every 30 minutes between 10:00-22:00")
            logger.info("🧪 Test message with chart will be sent in 30 seconds")
            logger.info(f"💰 Monthly subscription: {MONTHLY_PRICE}₪")
            
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
