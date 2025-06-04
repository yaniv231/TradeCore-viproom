# bot_minimal.py
import logging
import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# הגדרות לוגינג
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')

async def start_minimal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"MINIMAL BOT: /start received from user {user.id}")
    try:
        await update.message.reply_text('MINIMAL BOT: Received /start! Working on Render!')
        logger.info(f"MINIMAL BOT: Reply sent to user {user.id}")
    except Exception as e:
        logger.error(f"MINIMAL BOT: Error: {e}", exc_info=True)

def main_minimal():
    if not TOKEN:
        logger.critical("MINIMAL BOT: TELEGRAM_BOT_TOKEN missing!")
        return
    
    logger.info("MINIMAL BOT: Starting...")
    application = Application.builder().token(TOKEN).build()
    
    # הוספת handler לפקודת /start
    application.add_handler(CommandHandler("start", start_minimal))
    
    logger.info("MINIMAL BOT: Starting polling...")
    application.run_polling()

if __name__ == '__main__':
    main_minimal()
