import logging
import os
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# הגדרת לוגינג
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# הגדרות הבוט - החלף בערכים שלך
BOT_TOKEN = "7269747636:AAGSP-Nvm-C7bAiilqv7uO3hwvIrZhO3j58"
CHANNEL_ID = "-1007269747636"  # אם זה לא עובד, נבדוק מזהה אחר

class SimpleBot:
    def __init__(self):
        self.app = None
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת התחלה"""
        user = update.effective_user
        logger.info(f"User {user.id} started the bot")
        
        message = f"""
🎉 שלום {user.first_name}!

ברוך הבא לבוט המסחר שלנו!

📈 לקבלת גישה לערוץ הפרמיום לתקופת ניסיון של 7 ימים, 
פשוט שלח: מאשר

🚀 אחרי האישור תקבל קישור אישי לערוץ!
        """
        
        await update.message.reply_text(message)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """טיפול בהודעות"""
        user = update.effective_user
        text = update.message.text.lower().strip()
        
        logger.info(f"User {user.id} sent: {text}")
        
        if "מאשר" in text:
            # הודעת עיבוד
            await update.message.reply_text("⏳ יוצר קישור אישי...")
            
            try:
                # יצירת קישור הזמנה פשוט
                invite_link = await context.bot.create_chat_invite_link(
                    chat_id=CHANNEL_ID,
                    name=f"User_{user.id}_{datetime.now().strftime('%d%m')}"
                )
                
                success_msg = f"""
✅ ברוך הבא!

👤 שם: {user.first_name}
🆔 מזהה: {user.id}

🔗 הקישור שלך:
{invite_link.invite_link}

⏰ תקופת ניסיון: 7 ימים
📅 תאריך: {datetime.now().strftime('%d/%m/%Y')}

לחץ על הקישור והצטרף! 🚀
                """
                
                await update.message.reply_text(success_msg)
                logger.info(f"✅ Success for user {user.id}")
                
            except Exception as e:
                error_msg = f"""
❌ שגיאה ביצירת קישור

פרטי השגיאה: {str(e)}

🔍 בדיקות:
1. הבוט אדמין בערוץ?
2. הערוץ פרטי?
3. מזהה הערוץ נכון?

מזהה נוכחי: {CHANNEL_ID}
                """
                
                await update.message.reply_text(error_msg)
                logger.error(f"❌ Error: {e}")
        else:
            await update.message.reply_text(
                "❌ אנא שלח 'מאשר' כדי לקבל גישה לערוץ"
            )
    
    async def run(self):
        """הפעלת הבוט"""
        logger.info("🚀 Starting Simple Bot...")
        
        # יצירת Application
        self.app = Application.builder().token(BOT_TOKEN).build()
        
        # הוספת handlers
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # הפעלה
        try:
            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling()
            
            logger.info("✅ Bot running successfully!")
            
            # המתנה אינסופית
            while True:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"❌ Bot error: {e}")
        finally:
            if self.app:
                await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()

# הפעלת הבוט
if __name__ == "__main__":
    bot = SimpleBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
