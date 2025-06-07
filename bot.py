# bot.py
import logging
import datetime
import random
import asyncio
import pytz
import re

# Imports for ASGI and Lifespan
import contextlib
import uvicorn
from asgiref.wsgi import WsgiToAsgi

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from flask import Flask, request, abort
from apscheduler.schedulers.asyncio import AsyncIOScheduler # שינוי לגרסה האסינכרונית של APScheduler

import config
import g_sheets
from g_sheets import ConfirmationStatus, PaymentStatus
import graph_generator

# --- הגדרות לוגינג (ללא שינוי) ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.INFO) # נחזיר לרמת INFO כדי למנוע הצפת לוגים
logging.getLogger("telegram.ext").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# --- משתנים גלובליים ---
AWAITING_EMAIL_AND_CONFIRMATION = range(1)
application_instance: Application | None = None
scheduler = AsyncIOScheduler(timezone="Asia/Jerusalem") # שימוש בגרסה האסינכרונית

# --- פונקציות עזר (ללא שינוי משמעותי) ---
# ... (כל פונקציות העזר כמו get_disclaimer_dates, send_invite_link_or_add_to_channel, 
# send_async_message, send_async_photo_message, async_handle_user_removal נשארות כפי שהיו)
# (לנוחות הקריאה, אני לא מדביק אותן שוב, אבל ודא שהן קיימות בקובץ שלך מהגרסאות הקודמות)

# --- ה-ConversationHandler המלא (ללא שינוי בלוגיקה הפנימית) ---
# ... (כל הפונקציות של ה-ConversationHandler: start_command, handle_email_and_confirmation,
# disclaimer_24h_warning_job_callback, cancel_request_job_callback, cancel_conversation_command
# נשארות כפי שהיו בגרסה המלאה האחרונה שסיפקתי)

# --- הגדרת אפליקציית Flask ---
flask_app = Flask(__name__)

@flask_app.route('/health', methods=['GET'])
def health_check():
    return "OK", 200

@flask_app.route('/webhook/gumroad', methods=['POST', 'GET'])
def gumroad_webhook_route():
    # ... (הלוגיקה של ה-webhook מגרסה #62 נשארת כפי שהיא) ...
    # היא תמשיך להשתמש ב-application_instance.job_queue כדי לשלוח הודעות
    global application_instance
    logger.info(f"--- GUMROAD WEBHOOK ENDPOINT HIT (METHOD: {request.method}) ---")
    data_to_process = None
    if request.method == 'POST':
        content_type = request.headers.get('Content-Type', '').lower()
        if 'application/x-www-form-urlencoded' in content_type:
            data_to_process = request.form.to_dict()
            logger.info("Received Gumroad POST Form data.")
        else:
            logger.warning(f"POST with unexpected Content-Type: {content_type}")
            return "Unsupported Content-Type", 415

        if data_to_process:
            email = data_to_process.get('email')
            product_identifier = data_to_process.get('permalink')
            sale_id = data_to_process.get('sale_id')
            subscription_id = data_to_process.get('subscription_id')

            if product_identifier and product_identifier == config.GUMROAD_PRODUCT_PERMALINK:
                if email and sale_id:
                    telegram_user_id_str = g_sheets.update_user_payment_status_from_gumroad(
                        email, str(sale_id), str(subscription_id) if subscription_id else None)
                    if telegram_user_id_str:
                        telegram_user_id = int(telegram_user_id_str)
                        if application_instance and application_instance.job_queue:
                            message_text = f"💰 תודה על רכישת המנוי!\nהגישה שלך לערוץ {config.CHANNEL_USERNAME} חודשה."
                            application_instance.job_queue.run_once(
                                send_async_message, 1, chat_id=telegram_user_id, data={'text': message_text}, name=f"gumroad_confirm_{telegram_user_id}")
                            logger.info(f"Queued payment confirmation for user {telegram_user_id}.")
                    else:
                        logger.warning(f"Gumroad sale for {email} processed, but no matching user found in GSheet.")
                    return "Webhook processed", 200
            else:
                logger.warning(f"Webhook for wrong product received: {product_identifier}")
                return "Wrong product", 200
    return "OK", 200

# --- משימות מתוזמנות ---
# ... (הפונקציות check_trials_and_reminders_job ו-post_scheduled_content_job נשארות כפי שהן,
# הן יקראו ל-job_queue של הבוט) ...

# --- פונקציית האתחול המרכזית (עכשיו אסינכרונית) ---
async def main_bot_setup_and_run():
    global application_instance, scheduler
    logger.info("Attempting main async setup...")

    if not config.TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN not set. Halting.")
        return
    if not g_sheets.get_sheet():
        logger.critical("Could not connect to Google Sheets. Halting.")
        return

    builder = Application.builder().token(config.TELEGRAM_BOT_TOKEN)
    application_instance = builder.build()

    # הוספת ה-ConversationHandler המלא
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_command)],
        states={
            AWAITING_EMAIL_AND_CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_and_confirmation)],
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation_command)],
    )
    application_instance.add_handler(conv_handler)
    logger.info("Added FULL ConversationHandler for /start.")

    async def general_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("--- GENERAL EXCEPTION DURING UPDATE PROCESSING ---", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            try: await update.effective_message.reply_text("אופס! אירעה שגיאה. נסה שוב או פנה למנהל.")
            except Exception: pass
    application_instance.add_error_handler(general_error_handler)
    logger.info("Added general error handler.")

    # הגדרת משימות ה-APScheduler
    if not scheduler.running:
        try:
            scheduler.add_job(check_trials_and_reminders_job, 'cron', hour=9, minute=5, id="check_trials_job_v4", replace_existing=True)
            def schedule_daily_content_posts():
                # ... לוגיקת תזמון הפוסטים היומיים ...
                pass
            schedule_daily_content_posts()
            scheduler.add_job(schedule_daily_content_posts, 'cron', hour=0, minute=10, id="reschedule_content_job_v4", replace_existing=True)
            scheduler.start()
            logger.info("APScheduler started and jobs scheduled.")
        except Exception as e_sched:
            logger.error(f"Failed to start APScheduler jobs: {e_sched}", exc_info=True)

    # אתחול והרצת הבוט של טלגרם
    try:
        await application_instance.initialize()
        await application_instance.updater.start_polling()
        await application_instance.start()
        logger.info("Telegram bot has been initialized and started polling.")
    except Exception as e_telegram:
        logger.error(f"Failed to initialize or start Telegram bot: {e_telegram}", exc_info=True)

# --- חיבור בין Flask ל-Uvicorn עם Lifespan ---
@contextlib.asynccontextmanager
async def lifespan(app):
    # הפונקציה הזו רצה כשהשרת עולה
    logger.info("Lifespan event: STARTUP")
    # הפעל את הלוגיקה של הבוט כמשימת רקע בלולאת האירועים של Uvicorn
    asyncio.create_task(main_bot_setup_and_run())
    yield
    # הפונקציה הזו רצה כשהשרת נכבה
    logger.info("Lifespan event: SHUTDOWN")
    if application_instance and application_instance.updater and application_instance.updater.running:
        await application_instance.updater.stop()
    if application_instance and application_instance.running:
        await application_instance.stop()
    if scheduler.running:
        scheduler.shutdown()
    logger.info("Shutdown tasks complete.")

# יצירת אובייקט ה-ASGI הסופי ש-Gunicorn/Uvicorn יריץ
asgi_app = WsgiToAsgi(flask_app)
asgi_app.lifespan = lifespan

# הרצה מקומית (לצורך פיתוח בלבד)
if __name__ == "__main__":
    logger.info("Running locally with Uvicorn server...")
    uvicorn.run("bot:asgi_app", host="0.0.0.0", port=8000, reload=True)
