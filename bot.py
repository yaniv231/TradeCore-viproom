import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
from telegram.error import TelegramError
import asyncio
import signal
from datetime import datetime, timedelta

# הגדרת לוגינג
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# משתני סביבה - החלף בערכים שלך
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or "7592108692:AAHRNtKPAmveFp4nfv_tWvoMt8Cg0gIFJKE"
CHANNEL_ID = os.getenv('CHANNEL_ID') or "-100591679360"
CHANNEL_USERNAME = os.getenv('CHANNEL_USERNAME') or "my_channel_name"

# מצבי השיחה
WAITING_FOR_CONFIRMATION = 1

class TelegramBot:
    def __init__(self):
        self.application = None
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת התחלה"""
        user = update.effective_user
        logger.info(f"User {user.id} ({user.username}) started the bot")
        
        welcome_message = f"""
🎉 *ברוכים הבאים לבוט הניסיון שלנו!*

שלום {user.first_name}! 👋

🚀 *כדי להתחיל את תקופת הניסיון של 7 ימים:*
אנא שלח אחת מהמילים הבאות:

• `מאשר`
• `מקבל`  
• `מאושר`

לאחר האישור, תקבל קישור לערוץ הפרמיום שלנו! 🎯
        """
        
        await update.message.reply_text(
            welcome_message,
            parse_mode='Markdown'
        )
        
        return WAITING_FOR_CONFIRMATION
    
    async def handle_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """טיפול בהודעת האישור"""
        user = update.effective_user
        message_text = update.message.text.strip().lower()
        
        logger.info(f"User {user.id} sent: {message_text}")
        
        # בדיקה אם ההודעה מכילה אחת ממילות האישור
        confirmation_words = ["מאשר", "מקבל", "מאושר"]
        if not any(word in message_text for word in confirmation_words):
            await update.message.reply_text(
                "❌ אנא שלח אחת ממילות האישור:\n\n"
                "• `מאשר`\n"
                "• `מקבל`\n"  
                "• `מאושר`",
                parse_mode='Markdown'
            )
            return WAITING_FOR_CONFIRMATION
        
        try:
            # בדיקה אם הבוט יכול לגשת לערוץ
            try:
                chat = await context.bot.get_chat(CHANNEL_ID)
                logger.info(f"Channel info: {chat.title}, Type: {chat.type}")
            except Exception as e:
                logger.error(f"Cannot access channel: {e}")
                await update.message.reply_text(
                    "❌ הבוט לא יכול לגשת לערוץ. ודא שהבוט הוא חבר בערוץ.",
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
            
            # בדיקה אם הבוט הוא אדמין
            try:
                bot_member = await context.bot.get_chat_member(CHANNEL_ID, context.bot.id)
                logger.info(f"Bot status in channel: {bot_member.status}")
                
                if bot_member.status not in ['administrator', 'creator']:
                    await update.message.reply_text(
                        "❌ הבוט אינו אדמין בערוץ. אנא הוסף אותו כאדמין.",
                        parse_mode='Markdown'
                    )
                    return ConversationHandler.END
            except Exception as e:
                logger.error(f"Cannot check bot admin status: {e}")
            
            # ניסיון ליצירת קישור הזמנה עם פרמטרים שונים
            try:
                # ניסיון ראשון - עם תפוגה של 7 ימים
                expire_date = int((datetime.now() + timedelta(days=7)).timestamp())
                invite_link = await context.bot.create_chat_invite_link(
                    chat_id=CHANNEL_ID,
                    expire_date=expire_date,
                    member_limit=1,
                    name=f"Trial_{user.id}_{user.username or 'user'}"
                )
            except Exception as e1:
                logger.error(f"First attempt failed: {e1}")
                try:
                    # ניסיון שני - ללא תפוגה
                    invite_link = await context.bot.create_chat_invite_link(
                        chat_id=CHANNEL_ID,
                        member_limit=1,
                        name=f"Trial_{user.id}"
                    )
                except Exception as e2:
                    logger.error(f"Second attempt failed: {e2}")
                    try:
                        # ניסיון שלישי - קישור פשוט ללא הגבלות
                        invite_link = await context.bot.create_chat_invite_link(
                            chat_id=CHANNEL_ID,
                            name=f"User_{user.id}"
                        )
                    except Exception as e3:
                        logger.error(f"All attempts failed: {e3}")
                        
                        # הודעת שגיאה מפורטת
                        error_message = f"""
❌ *לא ניתן ליצור קישור הזמנה*

🔍 *בדיקות שנדרשות:*

1️⃣ **ודא שהבוט הוא אדמין** בערוץ עם ההרשאות:
   • Invite Users via Link ✅
   • Add New Admins ✅

2️⃣ **ודא שהערוץ הוא פרטי** (לא ציבורי)
   • ערוצים ציבוריים לא תומכים בקישורי הזמנה מוגבלים

3️⃣ **נסה להסיר ולהוסיף** את הבוט מחדש כאדמין

👤 *פרטי המשתמש:*
🆔 *מזהה:* `{user.id}`
👤 *שם משתמש:* @{user.username or 'לא זמין'}
📝 *הודעה:* `{message_text}`

💬 *פנה לתמיכה עם הפרטים האלה לקבלת עזרה*
                        """
                        
                        await update.message.reply_text(
                            error_message,
                            parse_mode='Markdown'
                        )
                        return ConversationHandler.END
            
            # אם הגענו לכאן - הקישור נוצר בהצלחה
            success_message = f"""
✅ *נרשמת בהצלחה לתקופת ניסיון!*

👤 *שם:* {user.first_name} {user.last_name or ''}
👤 *משתמש:* @{user.username or 'לא זמין'}
🆔 *מזהה:* `{user.id}`
✅ *סטטוס:* אושר לתקופת ניסיון

🔗 *קישור לערוץ הפרמיום:*
{invite_link.invite_link}

⏰ *תקופת ניסיון:* 7 ימים
📅 *מתחיל:* {datetime.now().strftime("%d/%m/%Y %H:%M")}

🎯 *מה תקבל בערוץ:*
• אותות מסחר בזמן אמת
• ניתוחים טכניים מתקדמים
• גרפים וחיזויים
• תמיכה אישית

*ברוך הבא למשפחה! 🚀*
            """
            
            await update.message.reply_text(
                success_message,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            
            logger.info(f"Successfully created invite link for user {user.id} ({user.username})")
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            await update.message.reply_text(
                f"❌ שגיאה לא צפויה: {str(e)}\n\nפנה לתמיכה עם הודעה זו.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ביטול השיחה"""
        await update.message.reply_text(
            "❌ הפעולה בוטלה. שלח /start כדי להתחיל מחדש.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת עזרה"""
        help_text = """
🆘 *עזרה - פקודות זמינות:*

/start - התחלת תהליך הרשמה לניסיון
/help - הצגת הודעת עזרה זו
/cancel - ביטול תהליך נוכחי

✅ *לרשמה לתקופת ניסיון:*
שלח אחת ממילות האישור:
• `מאשר`
• `מקבל`
• `מאושר`

💬 *זקוק לעזרה נוספת?*
פנה אלינו דרך הערוץ הראשי.
        """
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    def setup_handlers(self):
        """הגדרת handlers"""
        # ConversationHandler לתהליך הרשמה
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', self.start_command)],
            states={
                WAITING_FOR_CONFIRMATION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_confirmation)
                ],
            },
            fallbacks=[
                CommandHandler('cancel', self.cancel_command),
                CommandHandler('start', self.start_command)
            ],
        )
        
        # הוספת handlers
        self.application.add_handler(conv_handler)
        self.application.add_handler(CommandHandler('help', self.help_command))
        
        logger.info("All handlers added successfully")
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """טיפול בשגיאות"""
        logger.error(f"Exception while handling an update: {context.error}")
        
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "❌ אירעה שגיאה. אנא נסה שוב או פנה לתמיכה."
            )
    
    async def run(self):
        """הפעלת הבוט"""
        logger.info(f"Bot token starts with: {BOT_TOKEN[:10]}...")
        logger.info(f"Channel ID: {CHANNEL_ID}")
        logger.info("Starting Telegram Bot...")
        
        # יצירת Application
        self.application = Application.builder().token(BOT_TOKEN).build()
        
        # הגדרת handlers
        self.setup_handlers()
        
        # הגדרת error handler
        self.application.add_error_handler(self.error_handler)
        
        logger.info("Starting polling...")
        
        # הפעלת הבוט עם טיפול נכון ב-event loop
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
            
            # המתנה אינסופית
            stop_signals = (signal.SIGTERM, signal.SIGINT)
            for sig in stop_signals:
                signal.signal(sig, lambda s, f: asyncio.create_task(self.shutdown()))
            
            logger.info("Bot is running. Press Ctrl+C to stop.")
            
            # המתנה אינסופית
            while True:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"Error in bot execution: {e}")
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """כיבוי נקי של הבוט"""
        logger.info("Shutting down bot...")
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

async def main():
    """פונקציה ראשית"""
    bot = TelegramBot()
    await bot.run()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("Bot shutdown complete")
