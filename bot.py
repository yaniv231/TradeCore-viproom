import os
import logging
from datetime import datetime, timedelta
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,  # ייבוא חסר שהיה צריך להוסיף
    CallbackContext
)
from apscheduler.schedulers.background import BackgroundScheduler
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf
import mplfinance as mpf
import matplotlib.pyplot as plt
import requests
from pytz import timezone
from typing import cast
import asyncio

# הגדרת אפליקציית Flask עם השם הנדרש
flask_app = Flask(__name__)  # שיניתי את השם ל-flask_app

# ... (הגדרת משתנים ופונקציות עוזר) ...

# הגדרת הפונקציות עם תיקון ה-async
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"שלום {user.first_name}! ברוך הבא לבוט VIP."
    )

async def handle_user_removal(context: CallbackContext) -> None:
    # ... קוד קיים ...

# פונקציית Flask עם תיקון ה-async
@flask_app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    # ... לוגיקת ה-webhook ...
    
    # דוגמה לשימוש ב-async בתוך Flask
    async def async_task():
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=CHANNEL_ID, text="הודעה חדשה התקבלה")
    
    asyncio.run(async_task())
    
    return 'OK', 200

# הגדרת הפונקציה הראשית כ-async
async def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    # ... הוספת שאר ההאנדלרים ...
    
    scheduler = BackgroundScheduler(timezone=timezone('Asia/Jerusalem'))
    scheduler.add_job(
        handle_user_removal,
        'interval',
        hours=24,
        args=[application],
        next_run_time=datetime.now() + timedelta(minutes=1)
    scheduler.start()
    
    await application.run_polling()

# הפעלת האפליקציה כאשר הקובץ רץ ישירות
if __name__ == '__main__':
    # הפעלת Flask בשרת נפרד
    flask_app.run(port=5000, debug=True)
    
    # הפעלת הבוט של Telegram
    asyncio.run(main())
