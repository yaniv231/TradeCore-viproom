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
import pandas as pd
from urllib.request import urlopen

# הגדרות לוג
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# משתני סביבה
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
GOOGLE_CREDENTIALS = os.getenv('GOOGLE_CREDENTIALS')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
FMP_API_KEY = os.getenv('FMP_API_KEY')

# הגדרות תשלום
PAYPAL_PAYMENT_LINK = "https://www.paypal.com/ncp/payment/LYPU8NUFJB7XW"
MONTHLY_PRICE = 200

# מצבי שיחה
WAITING_FOR_EMAIL = 1

class FMPHandler:
    def __init__(self, api_key):
        self.base_url = "https://financialmodelingprep.com/api/v3"
        self.api_key = api_key

    def fetch_stock_data(self, symbol):
        try:
            url = f"{self.base_url}/historical-price-full/{symbol}?apikey={self.api_key}"
            with urlopen(url) as response:
                data = json.loads(response.read().decode())
                return self._process_data(data)
        except Exception as e:
            logger.error(f"שגיאה ב-FMP: {e}")
            return None

    def _process_data(self, data):
        if 'historical' not in data:
            return None
        df = pd.DataFrame(data['historical'])
        df['date'] = pd.to_datetime(df['date'])
        return df.set_index('date').sort_index()

class BotCore:
    def __init__(self):
        self.fmp = FMPHandler(FMP_API_KEY)
        self.scheduler = AsyncIOScheduler()
        self.setup_google_sheets()

    def setup_google_sheets(self):
        try:
            if GOOGLE_CREDENTIALS:
                creds = Credentials.from_service_account_info(json.loads(GOOGLE_CREDENTIALS))
                self.gc = gspread.authorize(creds)
                self.sheet = self.gc.open_by_key(SPREADSHEET_ID).sheet1
        except Exception as e:
            logger.error(f"שגיאה בגוגל שיטס: {e}")

    async def start_bot(self, application):
        await application.initialize()
        await application.start()
        await application.updater.start_polling()

class TelegramHandlers:
    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "ברוך הבא! שלח 'מאשר' כדי להתחיל בשבוע ניסיון חינם"
        )
        return WAITING_FOR_EMAIL

    @staticmethod
    async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        try:
            invite_link = await context.bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                expire_date=int((datetime.now() + timedelta(days=8)).timestamp())
            )
            await update.message.reply_text(f"הקישור שלך: {invite_link.invite_link}")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"שגיאה ביצירת קישור: {e}")
            await update.message.reply_text("שגיאה, נסה שוב מאוחר יותר")
            return ConversationHandler.END

class SchedulerTasks:
    @staticmethod
    async def check_expired_trials():
        # קוד לבדיקת תוקף ניסיון
        pass

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # רישום handlers
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', TelegramHandlers.start)],
        states={
            WAITING_FOR_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, TelegramHandlers.confirm)]
        },
        fallbacks=[CommandHandler('cancel', lambda u,c: ConversationHandler.END)]
    )
    application.add_handler(conv_handler)

    # הגדרת משימות רקע
    bot_core = BotCore()
    bot_core.scheduler.add_job(
        SchedulerTasks.check_expired_trials,
        CronTrigger(hour=9, minute=0, timezone="Asia/Jerusalem")
    )
    bot_core.scheduler.start()

    # הפעלת הבוט
    loop = asyncio.get_event_loop()
    loop.run_until_complete(bot_core.start_bot(application))
    loop.run_forever()

if __name__ == '__main__':
    main()
