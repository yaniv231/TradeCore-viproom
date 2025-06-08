# bot.py - גרסה פשוטה ועובדת לבוט טלגרם עם ConversationHandler

import logging
import datetime
import re
import os
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)

# הגדרות לוגינג
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# קבועים
AWAITING_EMAIL_AND_CONFIRMATION = 1

# משתני סביבה (חובה להגדיר ב-Render)
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHANNEL_ID = int(os.environ.get('CHANNEL_ID', '-100591679360'))
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME', 'TradeCore VIP')
TRIAL_PERIOD_DAYS = 7

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required!")

logger.info(f"Bot starting with token: {TELEGRAM_BOT_TOKEN[:10]}...")

# פונקציות עזר
def get_disclaimer_dates():
    today = datetime.date.today()
    trial_end_date = today + datetime.timedelta(days=TRIAL_PERIOD_DAYS)
    return today.strftime("%d/%m/%Y"), trial_end_date.strftime("%d/%m/%Y")

async def send_invite_link_or_add_to_channel(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str):
    """יוצר קישור הצטרפות לערוץ"""
    try:
        expire_date = datetime.datetime.now() + datetime.timedelta(days=TRIAL_PERIOD_DAYS + 2)
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            name=f"Trial for {username}",
            expire_date=expire_date,
            member_limit=1
        )
        
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ ברוך הבא!\n"
                f"הנך מועבר לתקופת ניסיון של {TRIAL_PERIOD_DAYS} ימים.\n"
                f"לחץ כאן כדי להצטרף לערוץ: {invite_link.invite_link}"
            )
        )
        logger.info(f"Sent invite link to user {user_id} ({username})")
        return True
        
    except Exception as e:
        logger.error(f"Could not create invite link for user {user_id}: {e}")
        await context.bot.send_message(
            user_id, 
            "אירעה שגיאה ביצירת קישור ההצטרפות. אנא פנה למנהל."
        )
        return False

# ConversationHandler handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """פונקציית התחלה - מציגה את ההסבר ומבקשת אימייל ואישור"""
    user = update.effective_user
    effective_username = user.username or user.first_name or f"User_{user.id}"
    
    logger.info(f"User {user.id} ({effective_username}) started the bot.")
    
    today_str, trial_end_str = get_disclaimer_dates()
    
    disclaimer_message = (
        f"🔥 ברוכים הבאים לערוץ TradeCore VIP! 🔥\n\n"
        f"📈 המנוי שלך (לתקופת הניסיון) יתחיל עם אישור התנאים ויסתיים כעבור {TRIAL_PERIOD_DAYS} ימים.\n"
        f"📅 אם תאשר היום ({today_str}), הניסיון יסתיים ב-{trial_end_str}\n\n"
        f"⚠️ חשוב להבהיר: התוכן כאן אינו מהווה ייעוץ או המלצה פיננסית!\n"
        f"💡 ההחלטות בסופו של דבר בידיים שלכם.\n\n"
        f"📧 כדי להמשיך, אנא שלח:\n"
        f"1️⃣ את כתובת האימייל שלך\n"
        f"2️⃣ את המילה 'מאשר'\n\n"
        f"📝 דוגמה: myemail@example.com מאשר"
    )
    
    await update.message.reply_text(disclaimer_message)
    
    return AWAITING_EMAIL_AND_CONFIRMATION

async def handle_email_and_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מטפל בהודעה שמכילה אימייל ואישור"""
    user = update.effective_user
    text = update.message.text.strip()
    effective_username = user.username or user.first_name or f"User_{user.id}"
    
    logger.info(f"User {user.id} sent: {text}")
    
    # חיפוש אימייל בטקסט
    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text)
    
    # חיפוש מילות אישור
    confirmation_keywords = ["מאשר", "מקובל", "אישור", "ok", "yes", "כן", "אני מאשר"]
    text_lower = text.lower()
    confirmation_keyword_found = any(keyword in text_lower for keyword in confirmation_keywords)
    
    if email_match and confirmation_keyword_found:
        email = email_match.group(0).lower()
        
        logger.info(f"User {user.id} provided email {email} and confirmed")
        
        # כאן תוכל להוסיף שמירה ל-Google Sheets או DB
        # לעת עתה נשלח רק הודעת הצלחה
        
        await update.message.reply_text("✅ תודה! מעבד את הבקשה...")
        
        # שליחת קישור לערוץ
        success = await send_invite_link_or_add_to_channel(context, user.id, effective_username)
        
        if success:
            await update.message.reply_text(
                f"🎉 הצלחת! ההרשמה הושלמה.\n"
                f"תיהנה מתקופת הניסיון של {TRIAL_PERIOD_DAYS} ימים!"
            )
        
        return ConversationHandler.END
        
    else:
        await update.message.reply_text(
            "❌ לא זיהיתי אימייל תקין ואישור.\n\n"
            "אנא שלח שוב בפורמט:\n"
            "📧 כתובת@אימייל.קום מאשר\n\n"
            "דוגמה: user@gmail.com מאשר"
        )
        return AWAITING_EMAIL_AND_CONFIRMATION

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מבטל את השיחה"""
    await update.message.reply_text(
        '❌ תהליך ההרשמה בוטל.\n'
        'תוכל להתחיל מחדש עם /start',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """מטפל בשגיאות כלליות"""
    logger.error("Exception during update processing:", exc_info=context.error)
    
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "אופס! אירעה שגיאה. נסה שוב או פנה למנהל."
            )
        except Exception:
            pass

def main():
    """הפונקציה הראשית"""
    logger.info("Starting Telegram Bot...")
    
    # יצירת האפליקציה
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # הגדרת ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_command)],
        states={
            AWAITING_EMAIL_AND_CONFIRMATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_and_confirmation)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)],
        allow_reentry=True,  # מאפשר להתחיל שיחה חדשה גם אם יש כבר אחת פעילה
    )
    
    # הוספת ה-handlers
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    
    logger.info("ConversationHandler added successfully")
    
    # הפעלת הבוט
    logger.info("Starting polling...")
    application.run_polling(
        drop_pending_updates=True,  # מתעלם מהודעות שהצטברו בזמן שהבוט היה כבוי
        allowed_updates=['message', 'callback_query']  # מקבל רק הודעות וכפתורים
    )

if __name__ == '__main__':
    main()
