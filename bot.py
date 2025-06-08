import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
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

# משתני סביבה - עם המזהה המתוקן
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or "7269747636:AAETblnIfIDN9kqH7vw8B6rdHVjM2_1ybrg"
CHANNEL_ID = os.getenv('CHANNEL_ID') or "-1007269747696"
CHANNEL_USERNAME = os.getenv('CHANNEL_USERNAME') or "my_trading_channel"

# מצבי השיחה
WAITING_FOR_CONFIRMATION = 1

class TradingBot:
    def __init__(self):
        self.application = None
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת התחלה"""
        user = update.effective_user
        logger.info(f"New user started: {user.id} ({user.username})")
        
        welcome_message = f"""
🚀 *ברוכים הבאים לבוט המסחר המתקדם!*

שלום {user.first_name}! 👋

🎯 *מה אנחנו מציעים:*
• אותות מסחר מדויקים בזמן אמת
• ניתוחים טכניים מתקדמים
• גרפים אינטראקטיביים
• תמיכה אישית 24/7

📈 *תקופת ניסיון של 7 ימים חינם!*

✅ *להתחלה, פשוט שלח:*
`מאשר`

לאחר האישור תקבל גישה מיידית לערוץ הפרמיום! 🎯
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
        
        # בדיקה אם ההודעה מכילה "מאשר"
        if "מאשר" not in message_text:
            await update.message.reply_text(
                "❌ אנא שלח `מאשר` כדי להתחיל את תקופת הניסיון",
                parse_mode='Markdown'
            )
            return WAITING_FOR_CONFIRMATION
        
        # הודעת עיבוד
        processing_msg = await update.message.reply_text(
            "⏳ יוצר קישור גישה אישי...",
            parse_mode='Markdown'
        )
        
        try:
            # יצירת קישור הזמנה
            invite_link = await context.bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                name=f"Trial_{user.id}_{datetime.now().strftime('%d%m%Y')}"
            )
            
            # הודעת הצלחה
            success_message = f"""
✅ *ברוך הבא למשפחה!*

👤 *פרטיך:*
• שם: {user.first_name} {user.last_name or ''}
• משתמש: @{user.username or 'לא זמין'}
• מזהה: `{user.id}`

🔗 *הקישור האישי שלך:*
{invite_link.invite_link}

⏰ *תקופת ניסיון:* 7 ימים
📅 *מתחיל:* {datetime.now().strftime("%d/%m/%Y %H:%M")}

🎯 *מה תקבל:*
• אותות קנייה/מכירה בזמן אמת
• ניתוחים טכניים יומיים
• גרפים מתקדמים
• תמיכה אישית

*לחץ על הקישור והצטרף עכשיו! 🚀*
            """
            
            await processing_msg.edit_text(
                success_message,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            
            logger.info(f"✅ Successfully created trial for user {user.id}")
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"❌ Error creating invite link: {e}")
            await processing_msg.edit_text(
                f"❌ שגיאה ביצירת הקישור\n\n"
                f"פרטי השגיאה: `{str(e)}`\n\n"
                f"אנא פנה לתמיכה.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת עזרה"""
        help_text = """
🆘 *עזרה - איך להשתמש בבוט:*

/start - התחלת תקופת ניסיון
/help - הצגת עזרה זו

✅ *לקבלת גישה:*
שלח `מאשר` אחרי /start

🎯 *מה תקבל:*
• אותות מסחר חיים
• ניתוחים טכניים
• גרפים מתקדמים
• תמיכה 24/7

💬 *תמיכה:* פנה אלינו בערוץ הראשי
        """
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    def setup_handlers(self):
        """הגדרת handlers"""
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', self.start_command)],
            states={
                WAITING_FOR_CONFIRMATION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_confirmation)
                ],
            },
            fallbacks=[CommandHandler('start', self.start_command)],
        )
        
        self.application.add_handler(conv_handler)
        self.application.add_handler(CommandHandler('help', self.help_command))
        
        logger.info("✅ All handlers configured")
    
    async def run(self):
        """הפעלת הבוט"""
        logger.info("🚀 Starting new Trading Bot...")
        logger.info(f"Token: {BOT_TOKEN[:10]}...")
        logger.info(f"Channel: {CHANNEL_ID}")
        
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.setup_handlers()
        
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
            
            logger.info("✅ Bot is running successfully!")
            
            while True:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"❌ Bot error: {e}")
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """כיבוי הבוט"""
        logger.info("🔄 Shutting down bot...")
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

def main():
    bot = TradingBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")

if __name__ == '__main__':
    main()
