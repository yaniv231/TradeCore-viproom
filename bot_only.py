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
TWELVE_DATA_API_KEY = os.getenv('TWELVE_DATA_API_KEY') or "fb6b77ae35bc44e0a0837163538c406a"

# הגדרות תשלום
PAYPAL_PAYMENT_LINK = "https://www.paypal.com/ncp/payment/LYPU8NUFJB7XW"
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
        user = update.effective_user
        logger.info(f"User {user.id} ({user.username}) started PeakTrade bot")

        try:
            if self.sheet:
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                trial_end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

                new_row = [
                    user.id,
                    user.username or "N/A",
                    user.first_name or "",
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
                logger.info(f"✅ User {user.id} registered in sheet")
        except Exception as e:
            logger.error(f"❌ Error writing user to sheet: {e}")

        try:
            invite_link = await context.bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                expire_date=int((datetime.now() + timedelta(days=8)).timestamp()),
                name=f"Trial_{user.id}_{user.username or 'user'}"
            )

            message = f"""🎉 ברוך הבא ל-PeakTrade VIP!

👤 שם משתמש: @{user.username or 'לא זמין'}

🔗 הקישור שלך לקבוצה:
{invite_link.invite_link}

⏰ תקופת ניסיון: 7 ימים
📅 מתחיל: {datetime.now().strftime('%d/%m/%Y')}
📅 מסתיים: {(datetime.now() + timedelta(days=7)).strftime('%d/%m/%Y')}

בהצלחה! 🚀"""
            await update.message.reply_text(message)

        except Exception as e:
            logger.error(f"❌ Error creating invite link: {e}")
            await update.message.reply_text("❌ לא הצלחנו להפיק קישור. אנא נסה שוב מאוחר יותר.")

        return ConversationHandler.END

    def setup_handlers(self):
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', self.start_command)],
            states={},
            fallbacks=[],
        )
        self.application.add_handler(conv_handler)
        logger.info("✅ All handlers configured")

    async def run(self):
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.setup_handlers()
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        logger.info("✅ Bot started")

if __name__ == "__main__":
    bot = PeakTradeBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
