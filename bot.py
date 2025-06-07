# bot.py
import logging
import datetime
import random
import asyncio
import re

# Imports for ASGI and Lifespan
import contextlib
import uvicorn
from asgiref.wsgi import WsgiToAsgi

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)
from flask import Flask, request, abort
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
import g_sheets
from g_sheets import ConfirmationStatus, PaymentStatus
import graph_generator

# --- הגדרות לוגינג ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- משתנים גלובליים ---
AWAITING_EMAIL_AND_CONFIRMATION = range(1)
application_instance: Application | None = None
flask_app = Flask(__name__)
scheduler = AsyncIOScheduler(timezone="Asia/Jerusalem")

# --- פונקציות עזר ---
def get_disclaimer_dates():
    today = datetime.date.today()
    trial_end_date = today + datetime.timedelta(days=config.TRIAL_PERIOD_DAYS)
    return today.strftime("%d/%m/%Y"), trial_end_date.strftime("%d/%m/%Y")

async def send_invite_link_or_add_to_channel(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str | None):
    actual_username = username or f"User_{user_id}"
    try:
        expire_date = datetime.datetime.now() + datetime.timedelta(days=config.TRIAL_PERIOD_DAYS + 2)
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=config.CHANNEL_ID, name=f"Trial for {actual_username}",
            expire_date=expire_date, member_limit=1
        )
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ אישרת את התנאים וסיפקת אימייל!\n"
                f"הנך מועבר לתקופת ניסיון של {config.TRIAL_PERIOD_DAYS} ימים.\n"
                f"לחץ כאן כדי להצטרף לערוץ: {invite_link.invite_link}"
            )
        )
        logger.info(f"Sent invite link to user {user_id} ({actual_username})")
        return True
    except Exception as e:
        logger.error(f"Could not create invite link for user {user_id}: {e}", exc_info=True)
        await context.bot.send_message(user_id, "אירעה שגיאה ביצירת קישור ההצטרפות. אנא פנה למנהל.")
        if config.ADMIN_USER_ID and config.ADMIN_USER_ID != 0:
            try:
                await context.bot.send_message(config.ADMIN_USER_ID, f"⚠️ שגיאה ביצירת קישור למשתמש {actual_username} ({user_id}): {e}")
            except Exception as admin_err:
                logger.error(f"Failed to send error notification to admin: {admin_err}")
        return False

async def send_async_message(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    if not job or not job.data or 'chat_id' not in job.data or 'text' not in job.data: return
    try: await context.bot.send_message(chat_id=job.data['chat_id'], text=job.data['text'])
    except Exception as e: logger.error(f"Error sending async message to {job.data['chat_id']}: {e}", exc_info=True)

async def send_async_photo_message(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    if not job or not job.data or 'chat_id' not in job.data or 'photo' not in job.data or 'caption' not in job.data: return
    photo_stream = job.data['photo']
    try:
        photo_stream.seek(0)
        await context.bot.send_photo(chat_id=job.data['chat_id'], photo=photo_stream, caption=job.data['caption'])
    except Exception as e: logger.error(f"Error sending async photo to {job.data['chat_id']}: {e}", exc_info=True)
    finally:
        if hasattr(photo_stream, 'close') and callable(photo_stream.close): photo_stream.close()

async def async_handle_user_removal(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    if not job or not job.data or 'user_id' not in job.data: return
    user_id = job.data['user_id']
    logger.info(f"Async job: Starting removal process for user {user_id}")
    try:
        await context.bot.ban_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id)
        await asyncio.sleep(1)
        await context.bot.unban_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id, only_if_banned=True)
        removal_text = (f"הגישה שלך לערוץ {config.CHANNEL_USERNAME or 'TradeCore VIP'} הופסקה "
                        f"מכיוון שלא התקבל תשלום לאחר תקופת הניסיון.")
        await context.bot.send_message(chat_id=user_id, text=removal_text)
        g_sheets.update_user_data(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.EXPIRED_NO_PAYMENT.value})
    except Exception as e:
        logger.error(f"Async job: Error during removal process for user {user_id}: {e}", exc_info=True)
        g_sheets.update_user_data(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.EXPIRED_NO_PAYMENT.value})

# --- ConversationHandler המלא ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    effective_username = user.username or user.first_name or f"User_{user.id}"
    logger.info(f"User {user.id} ({effective_username}) started the bot.")
    user_gs_data = g_sheets.get_user_data(user.id)
    if user_gs_data:
        payment_status_str = user_gs_data.get(g_sheets.COL_PAYMENT_STATUS)
        if payment_status_str in [PaymentStatus.TRIAL.value, PaymentStatus.PAID_SUBSCRIBER.value]:
            await update.message.reply_text("אתה כבר רשום ופעיל בערוץ! 😊")
            return ConversationHandler.END
    
    today_str, trial_end_str = get_disclaimer_dates()
    disclaimer_message = (
        f"היי, זה מצוות הערוץ ״חדר vip -TradeCore״\n\n"
        f"המנוי שלך (לתקופת הניסיון) יתחיל עם אישור התנאים ויסתיים כעבור {config.TRIAL_PERIOD_DAYS} ימים.\n"
        f"חשוב להבהיר: 🚫התוכן כאן אינו מהווה ייעוץ או המלצה פיננסית מכל סוג! "
        f"📌 ההחלטות בסופו של דבר בידיים שלכם – איך לפעול, מתי להיכנס ומתי לצאת מהשוק.\n\n"
        f"כדי להמשיך, אנא שלח את כתובת האימייל שלך (זו שתשמש לתשלום) ואת המילה 'מאשר'.\n"
        f"לדוגמה: `myemail@example.com מאשר`"
    )
    await update.message.reply_text(disclaimer_message)
    g_sheets.add_new_user_for_disclaimer(user.id, effective_username)
    job_name = f"disclaimer_warning_{user.id}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    for job_item in current_jobs: job_item.schedule_removal()
    context.job_queue.run_once(
        disclaimer_24h_warning_job_callback,
        datetime.timedelta(hours=config.REMINDER_MESSAGE_HOURS_BEFORE_WARNING),
        chat_id=user.id, name=job_name, data={'user_id': user.id}
    )
    return AWAITING_EMAIL_AND_CONFIRMATION

async def handle_email_and_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    text = update.message.text.strip()
    effective_username = user.username or user.first_name or f"User_{user.id}"
    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text)
    confirmation_keywords = ["מאשר", "מקובל", "אישור", "ok", "yes", "כן"]
    confirmation_keyword_found = any(keyword in text.lower() for keyword in confirmation_keywords)

    if email_match and confirmation_keyword_found:
        email = email_match.group(0).lower()
        g_sheets.update_user_email_and_confirmation(user.id, email, ConfirmationStatus.CONFIRMED_DISCLAIMER)
        g_sheets.start_user_trial(user.id)
        for job_name_suffix in [f"disclaimer_warning_{user.id}", f"cancel_request_{user.id}"]:
            for job_item in context.job_queue.get_jobs_by_name(job_name_suffix): job_item.schedule_removal()
        await send_invite_link_or_add_to_channel(context, user.id, effective_username)
        return ConversationHandler.END
    else:
        await update.message.reply_text("לא זוהתה כתובת אימייל ואישור. אנא שלח שוב בפורמט: `כתובת@אימייל.קום מאשר`")
        return AWAITING_EMAIL_AND_CONFIRMATION

async def disclaimer_24h_warning_job_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    if not job or not job.data or 'user_id' not in job.data: return
    user_id = job.data['user_id']
    user_gs_data = g_sheets.get_user_data(user_id)
    if user_gs_data and user_gs_data.get(g_sheets.COL_CONFIRMATION_STATUS) == ConfirmationStatus.PENDING_DISCLAIMER.value:
        bot_info = await context.bot.get_me()
        warning_message = (f"⚠️ אזהרה אחרונה ⚠️\n\nבקשתך להצטרפות לערוץ עדיין ממתינה לאישור תנאים. "
                           f"אם לא יתקבל מענה, הבקשה תבוטל.\n\nצוות ״חדר vip - TradeCore ״ http://t.me/{bot_info.username}")
        await context.bot.send_message(chat_id=user_id, text=warning_message)
        g_sheets.update_user_disclaimer_status(user_id, ConfirmationStatus.WARNED_NO_DISCLAIMER)

async def cancel_conversation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    await update.message.reply_text('תהליך ההרשמה בוטל.', reply_markup=ReplyKeyboardRemove())
    g_sheets.update_user_disclaimer_status(user.id, ConfirmationStatus.CANCELLED_NO_DISCLAIMER)
    return ConversationHandler.END

# --- Webhook של Gumroad ---
@flask_app.route('/webhook/gumroad', methods=['POST', 'GET'])
def gumroad_webhook_route():
    global application_instance
    logger.info(f"GUMROAD WEBHOOK HIT (METHOD: {request.method})")
    if request.method != 'POST': return "OK", 200
    try:
        data = request.form.to_dict()
        logger.info(f"Received Gumroad Form data: {data.get('email')}, {data.get('permalink')}")
        email = data.get('email')
        product_identifier = data.get('permalink')
        sale_id = data.get('sale_id')
        if config.GUMROAD_PRODUCT_PERMALINK and product_identifier == config.GUMROAD_PRODUCT_PERMALINK and email and sale_id:
            telegram_user_id_str = g_sheets.update_user_payment_status_from_gumroad(email, sale_id)
            if telegram_user_id_str and application_instance and application_instance.job_queue:
                message_text = f"💰 תודה על רכישת המנוי!\nהגישה שלך לערוץ {config.CHANNEL_USERNAME} חודשה."
                application_instance.job_queue.run_once(send_async_message, 1, chat_id=int(telegram_user_id_str), data={'text': message_text})
    except Exception as e:
        logger.error(f"Error processing Gumroad webhook: {e}", exc_info=True)
    return "Webhook processed", 200

@flask_app.route('/health', methods=['GET'])
def health_check(): return "OK", 200

# --- משימות מתוזמנות ---
def check_trials_and_reminders_job():
    global application_instance
    logger.info("APScheduler: Running check_trials_and_reminders_job.")
    if not (application_instance and application_instance.job_queue): return
    users_to_process = g_sheets.get_users_for_trial_reminder_or_removal()
    for item in users_to_process:
        action, user_gs_data = item['action'], item['data']
        user_id = int(user_gs_data.get(g_sheets.COL_USER_ID, '0'))
        if not user_id: continue
        if action == 'send_trial_end_reminder':
            reminder_text = (f"היי, כאן צוות {config.CHANNEL_USERNAME} 👋\n\nשבוע הניסיון שלך עומד להסתיים. "
                             f"כדי להמשיך, שלם {config.PAYMENT_AMOUNT_ILS}₪ דרך הקישור:\n{config.GUMROAD_PRODUCT_PERMALINK}")
            application_instance.job_queue.run_once(send_async_message, 1, chat_id=user_id, data={'text': reminder_text})
            g_sheets.update_user_data(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.PENDING_PAYMENT_AFTER_TRIAL.value})
        elif action == 'remove_user_no_payment':
            application_instance.job_queue.run_once(async_handle_user_removal, 1, chat_id=user_id, data={'user_id': user_id})

def post_scheduled_content_job():
    global application_instance
    logger.info("APScheduler: Running post_scheduled_content_job.")
    if not (application_instance and application_instance.job_queue): return
    selected_stock = random.choice(config.STOCK_SYMBOLS_LIST) if config.STOCK_SYMBOLS_LIST else None
    if not selected_stock: return
    image_stream, analysis_text = graph_generator.create_stock_graph_and_text(selected_stock)
    if image_stream and analysis_text:
        application_instance.job_queue.run_once(send_async_photo_message, 1, data={'chat_id': config.CHANNEL_ID, 'photo': image_stream, 'caption': analysis_text})

# --- אתחול והרצה ---
async def main_bot_setup_and_run():
    global application_instance, scheduler
    logger.info("Attempting main bot setup and run...")
    if not config.TELEGRAM_BOT_TOKEN: raise ValueError("TELEGRAM_BOT_TOKEN not set.")
    if not g_sheets.get_sheet(): raise ConnectionError("Could not connect to Google Sheets.")

    application_instance = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_command)],
        states={AWAITING_EMAIL_AND_CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_and_confirmation)]},
        fallbacks=[CommandHandler('cancel', cancel_conversation_command)],
    )
    application_instance.add_handler(conv_handler)
    
    async def general_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("Exception during update processing:", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            try: await update.effective_message.reply_text("אופס! אירעה שגיאה. נסה שוב או פנה למנהל.")
            except Exception: pass
    application_instance.add_error_handler(general_error_handler)

    if not scheduler.running:
        scheduler.add_job(check_trials_and_reminders_job, 'cron', hour=9, minute=5, id="check_trials_job_v5", replace_existing=True)
        def schedule_daily_content_posts():
            # ... לוגיקה לתזמן פוסטים ...
            pass
        schedule_daily_content_posts()
        scheduler.add_job(schedule_daily_content_posts, 'cron', hour=0, minute=10, id="reschedule_content_job_v5", replace_existing=True)
        scheduler.start()

    await application_instance.initialize()
    await application_instance.updater.start_polling()
    await application_instance.start()
    logger.info("Telegram bot started polling.")

@contextlib.asynccontextmanager
async def lifespan(app):
    logger.info("Lifespan event: STARTUP")
    asyncio.create_task(main_bot_setup_and_run())
    yield
    logger.info("Lifespan event: SHUTDOWN")
    if application_instance and application_instance.updater: await application_instance.updater.stop()
    if application_instance: await application_instance.stop()
    if scheduler.running: scheduler.shutdown()

asgi_app = WsgiToAsgi(flask_app)
asgi_app.lifespan = lifespan

if __name__ == "__main__":
    logger.info("Running locally with Uvicorn server...")
    uvicorn.run("bot:asgi_app", host="0.0.0.0", port=8000, reload=True)
