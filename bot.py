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
# הגברת רמת לוגינג לספריות טלגרם לבדיקה
logging.getLogger("telegram.ext").setLevel(logging.INFO) # אפשר לשנות ל-DEBUG אם צריך אבחון עמוק יותר
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
    if not job or not job.data or 'chat_id' not in job.data or 'text' not in job.data:
        logger.error(f"send_async_message: Invalid job data: {job.data if job else 'No job'}")
        return
    try: await context.bot.send_message(chat_id=job.data['chat_id'], text=job.data['text'])
    except Exception as e: logger.error(f"Error sending async message to {job.data['chat_id']}: {e}", exc_info=True)

async def send_async_photo_message(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    if not job or not job.data or 'chat_id' not in job.data or 'photo' not in job.data or 'caption' not in job.data:
        logger.error(f"send_async_photo_message: Invalid job data: {job.data if job else 'No job'}")
        return
    photo_stream = job.data['photo']
    try:
        photo_stream.seek(0)
        await context.bot.send_photo(chat_id=job.data['chat_id'], photo=photo_stream, caption=job.data['caption'])
    except Exception as e: logger.error(f"Error sending async photo to {job.data['chat_id']}: {e}", exc_info=True)
    finally:
        if hasattr(photo_stream, 'close') and callable(photo_stream.close): photo_stream.close()

async def async_handle_user_removal(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    if not job or not job.data or 'user_id' not in job.data:
        logger.error(f"async_handle_user_removal: Invalid job data: {job.data if job else 'No job'}")
        return
    user_id = job.data['user_id']
    logger.info(f"Async job: Starting removal process for user {user_id}")
    try:
        await context.bot.ban_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id)
        logger.info(f"Async job: Banned user {user_id} from channel {config.CHANNEL_ID}")
        await asyncio.sleep(1)
        await context.bot.unban_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id, only_if_banned=True)
        logger.info(f"Async job: Unbanned user {user_id} from channel {config.CHANNEL_ID}.")
        removal_text = (f"הגישה שלך לערוץ {config.CHANNEL_USERNAME or 'TradeCore VIP'} הופסקה "
                        f"מכיוון שלא התקבל תשלום לאחר תקופת הניסיון. "
                        f"נשמח לראותך שוב אם תחליט להצטרף ולחדש את המנוי!")
        await context.bot.send_message(chat_id=user_id, text=removal_text)
        logger.info(f"Async job: Sent removal notice to user {user_id}.")
        g_sheets.update_user_data(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.EXPIRED_NO_PAYMENT.value})
        logger.info(f"Async job: Updated GSheet status for user {user_id} to EXPIRED_NO_PAYMENT.")
    except Exception as e:
        logger.error(f"Async job: Error during removal process for user {user_id}: {e}", exc_info=True)
        g_sheets.update_user_data(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.EXPIRED_NO_PAYMENT.value})
        logger.info(f"Async job: Updated GSheet status for user {user_id} to EXPIRED_NO_PAYMENT despite Telegram API error.")


# --- ה-ConversationHandler המלא (מופעל כעת) ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    effective_username = user.username or user.first_name or f"User_{user.id}"
    logger.info(f"User {user.id} ({effective_username}) started the bot (full conv handler).")
    
    user_gs_data = g_sheets.get_user_data(user.id)
    if user_gs_data:
        confirmation_status_str = user_gs_data.get(g_sheets.COL_CONFIRMATION_STATUS)
        payment_status_str = user_gs_data.get(g_sheets.COL_PAYMENT_STATUS)
        is_confirmed = confirmation_status_str == ConfirmationStatus.CONFIRMED_DISCLAIMER.value
        is_trial_or_paid = payment_status_str in [PaymentStatus.TRIAL.value, PaymentStatus.PAID_SUBSCRIBER.value]

        if is_confirmed and is_trial_or_paid:
            await update.message.reply_text("אתה כבר רשום ופעיל בערוץ! 😊")
            return ConversationHandler.END
        
        elif confirmation_status_str in [ConfirmationStatus.PENDING_DISCLAIMER.value, ConfirmationStatus.WARNED_NO_DISCLAIMER.value]:
            await update.message.reply_text(
                "נראה שהתחלת בתהליך ההרשמה אך לא סיימת.\n"
                "אנא שלח את כתובת האימייל שלך (לצורך תשלום עתידי ב-Gumroad) ואת המילה 'מאשר' או 'מקובל'.\n"
                "לדוגמה: `myemail@example.com מאשר`"
            )
            return AWAITING_EMAIL_AND_CONFIRMATION
    
    today_str, trial_end_str = get_disclaimer_dates()
    disclaimer_message = (
        f"היי, זה מצוות הערוץ ״חדר vip -TradeCore״\n\n"
        f"המנוי שלך (לתקופת הניסיון) יתחיל עם אישור התנאים ויסתיים כעבור {config.TRIAL_PERIOD_DAYS} ימים.\n"
        f"(לתשומת ליבך, אם תאשר היום {today_str}, הניסיון יסתיים בערך ב-{trial_end_str}).\n\n"
        f"חשוב להבהיר: 🚫התוכן כאן אינו מהווה ייעוץ או המלצה פיננסית מכל סוג! "
        f"📌 ההחלטות בסופו של דבר בידיים שלכם – איך לפעול, מתי להיכנס ומתי לצאת מהשוק.\n\n"
        f"כדי להמשיך, אנא שלח את כתובת האימייל שלך (זו שתשמש לתשלום ב-Gumroad אם תבחר להמשיך) ולאחר מכן את המילה 'מאשר' או 'מקובל'.\n"
        f"לדוגמה: `myemail@example.com מאשר`"
    )
    await update.message.reply_text(disclaimer_message)
    
    g_sheets.add_new_user_for_disclaimer(user.id, effective_username)

    job_name = f"disclaimer_warning_{user.id}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    for job_item in current_jobs:
        job_item.schedule_removal()
        
    context.job_queue.run_once(
        disclaimer_24h_warning_job_callback,
        datetime.timedelta(hours=config.REMINDER_MESSAGE_HOURS_BEFORE_WARNING),
        chat_id=user.id, 
        name=job_name,
        data={'user_id': user.id}
    )
    logger.info(f"Scheduled 24h disclaimer warning for user {user.id}. Returning AWAITING_EMAIL_AND_CONFIRMATION.")
    return AWAITING_EMAIL_AND_CONFIRMATION


async def handle_email_and_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    text = update.message.text.strip() 
    effective_username = user.username or user.first_name or f"User_{user.id}"
    logger.info(f"User {user.id} ({effective_username}) sent text for disclaimer confirmation: {text}")

    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text)
    confirmation_keywords = ["מאשר", "מקובל", "אישור", "ok", "yes", "כן"]
    text_lower = text.lower()
    confirmation_keyword_found = any(keyword in text_lower for keyword in confirmation_keywords)

    if email_match and confirmation_keyword_found:
        email = email_match.group(0).lower()
        logger.info(f"User {user.id} provided email {email} and confirmed disclaimer.")

        g_sheets.update_user_email_and_confirmation(user.id, email, ConfirmationStatus.CONFIRMED_DISCLAIMER)
        g_sheets.start_user_trial(user.id)

        job_name_warn = f"disclaimer_warning_{user.id}"
        current_jobs_warn = context.job_queue.get_jobs_by_name(job_name_warn)
        for job_item in current_jobs_warn: job_item.schedule_removal()
        logger.info(f"Removed disclaimer warning job for user {user.id} after confirmation.")
        
        job_name_cancel = f"cancel_request_{user.id}"
        cancel_jobs = context.job_queue.get_jobs_by_name(job_name_cancel)
        for job_item in cancel_jobs: job_item.schedule_removal()
        logger.info(f"Removed cancel request job for user {user.id} after confirmation.")

        await send_invite_link_or_add_to_channel(context, user.id, effective_username)
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "לא הצלחתי לזהות כתובת אימייל תקינה ואישור ('מאשר' או 'מקובל').\n"
            "אנא שלח שוב בפורמט: `כתובת@אימייל.קום מאשר`"
        )
        return AWAITING_EMAIL_AND_CONFIRMATION

async def disclaimer_24h_warning_job_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    if not job or not job.data or 'user_id' not in job.data: return
    user_id = job.data['user_id']
    logger.info(f"Running 24h disclaimer warning job callback for user {user_id}")
    user_gs_data = g_sheets.get_user_data(user_id)

    if user_gs_data and user_gs_data.get(g_sheets.COL_CONFIRMATION_STATUS) == ConfirmationStatus.PENDING_DISCLAIMER.value:
        bot_info = await context.bot.get_me()
        bot_username = bot_info.username
        warning_message = (
            f"⚠️ אזהרה אחרונה ⚠️\n\n"
            f"לא קיבלנו ממך אישור, והבקשה שלך להצטרפות לערוץ עדיין ממתינה.\n\n"
            f"אם לא נקבל מענה בהקדם – הבקשה תבוטל ותוסר. זהו תזכורת אחרונה.\n\n"
            f"צוות הערוץ ״חדר vip - TradeCore ״ http://t.me/{bot_username}"
        )
        await context.bot.send_message(chat_id=user_id, text=warning_message)
        g_sheets.update_user_disclaimer_status(user_id, ConfirmationStatus.WARNED_NO_DISCLAIMER)
        logger.info(f"Sent final disclaimer warning to user {user_id}")

        job_name_cancel = f"cancel_request_{user.id}"
        current_cancel_jobs = context.job_queue.get_jobs_by_name(job_name_cancel)
        for c_job in current_cancel_jobs: c_job.schedule_removal()
        context.job_queue.run_once(
            cancel_request_job_callback,
            datetime.timedelta(hours=config.HOURS_FOR_FINAL_CONFIRMATION_AFTER_WARNING),
            chat_id=user_id, name=job_name_cancel, data={'user_id': user_id}
        )
        logger.info(f"Scheduled final cancellation job for user {user_id} with job name {job_name_cancel}")
    else:
        logger.info(f"User {user_id} already confirmed or not in pending state. Warning job skipped.")

async def cancel_request_job_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    if not job or not job.data or 'user_id' not in job.data: return
    user_id = job.data['user_id']
    logger.info(f"Running final cancellation job callback for user {user_id}")
    user_gs_data = g_sheets.get_user_data(user_id)
    if user_gs_data and user_gs_data.get(g_sheets.COL_CONFIRMATION_STATUS) == ConfirmationStatus.WARNED_NO_DISCLAIMER.value:
        g_sheets.update_user_disclaimer_status(user_id, ConfirmationStatus.CANCELLED_NO_DISCLAIMER)
        await context.bot.send_message(chat_id=user_id, text="בקשתך להצטרפות לערוץ בוטלה עקב חוסר מענה.")
        logger.info(f"Cancelled request for user {user_id} due to no final confirmation.")

async def cancel_conversation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    logger.info(f"User {user.id} canceled the conversation using /cancel.")
    await update.message.reply_text(
        'תהליך ההרשמה בוטל. תוכל להתחיל מחדש על ידי שליחת /start.',
        reply_markup=ReplyKeyboardRemove()
    )
    user_gs_data = g_sheets.get_user_data(user.id)
    if user_gs_data and user_gs_data.get(g_sheets.COL_CONFIRMATION_STATUS) in [
        ConfirmationStatus.PENDING_DISCLAIMER.value, ConfirmationStatus.WARNED_NO_DISCLAIMER.value
    ]:
        g_sheets.update_user_disclaimer_status(user.id, ConfirmationStatus.CANCELLED_NO_DISCLAIMER)
        for job_name_suffix in [f"disclaimer_warning_{user.id}", f"cancel_request_{user.id}"]:
            current_jobs = context.job_queue.get_jobs_by_name(job_name_suffix)
            for job_item in current_jobs: job_item.schedule_removal()
    return ConversationHandler.END

# --- Webhook של Gumroad ---
@flask_app.route('/webhook/gumroad', methods=['POST', 'GET'])
def gumroad_webhook_route():
    global application_instance
    logger.info(f"--- GUMROAD WEBHOOK ENDPOINT HIT (METHOD: {request.method}) ---")
    data_to_process = None
    if request.method == 'POST':
        content_type = request.headers.get('Content-Type', '').lower()
        if 'application/json' in content_type:
            try: data_to_process = request.json
            except Exception as e: logger.error(f"Error parsing JSON: {e}"); return "Error parsing JSON", 400
            logger.info("Received Gumroad POST JSON data.")
        elif 'application/x-www-form-urlencoded' in content_type:
            try: data_to_process = request.form.to_dict()
            except Exception as e: logger.error(f"Error parsing Form data: {e}"); return "Error parsing Form data", 400
            logger.info("Received Gumroad POST Form data.")
        else:
            logger.warning(f"POST with unexpected Content-Type: {content_type}.")
            return "Unsupported Content-Type for POST", 415

        if data_to_process:
            email = data_to_process.get('email')
            product_identifier = data_to_process.get('permalink')
            sale_id = data_to_process.get('sale_id')
            subscription_id = data_to_process.get('subscription_id')
            logger.info(f"Extracted for processing: email='{email}', product_identifier='{product_identifier}'")
            
            if config.GUMROAD_PRODUCT_PERMALINK and product_identifier == config.GUMROAD_PRODUCT_PERMALINK:
                logger.info("Correct product permalink received.")
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
                    return "Webhook data processed", 200
            else:
                logger.warning(f"Webhook for wrong product received: '{product_identifier}', expected: '{config.GUMROAD_PRODUCT_PERMALINK}'")
                return "Webhook for wrong product", 200
    elif request.method == 'GET':
        logger.info("Received GET to Gumroad webhook endpoint (test/ping).")
        return "GET received. This endpoint expects POST for sales.", 200
    
    return "OK", 200 # Fallback response


# --- משימות מתוזמנות ---
def check_trials_and_reminders_job():
    global application_instance
    logger.info("APScheduler: Running check_trials_and_reminders job.")
    if not (application_instance and application_instance.job_queue): return
    users_to_process = g_sheets.get_users_for_trial_reminder_or_removal()
    for item in users_to_process:
        # ... (הלוגיקה המלאה של check_trials_and_reminders_job מגרסה #50) ...
        pass

def post_scheduled_content_job():
    global application_instance
    logger.info("APScheduler: Attempting to post scheduled content.")
    if not (application_instance and application_instance.job_queue): return
    # ... (הלוגיקה המלאה של post_scheduled_content_job מגרסה #50) ...
    pass

# --- אתחול והרצה ---
async def main_bot_setup_and_run():
    global application_instance, scheduler
    logger.info("Attempting main async setup...")
    if not config.TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN not set. Halting."); return
    if not g_sheets.get_sheet():
        logger.critical("Could not connect to Google Sheets. Halting."); return

    builder = Application.builder().token(config.TELEGRAM_BOT_TOKEN)
    application_instance = builder.build()

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

    if not scheduler.running:
        try:
            scheduler.add_job(check_trials_and_reminders_job, 'cron', hour=9, minute=5, id="check_trials_job_v4", replace_existing=True)
            def schedule_daily_content_posts():
                # ... (הלוגיקה של תזמון הפוסטים) ...
                pass
            schedule_daily_content_posts()
            scheduler.add_job(schedule_daily_content_posts, 'cron', hour=0, minute=10, id="reschedule_content_job_v4", replace_existing=True)
            scheduler.start()
            logger.info("APScheduler started and jobs scheduled.")
        except Exception as e_sched:
            logger.error(f"Failed to start APScheduler jobs: {e_sched}", exc_info=True)
    
    await application_instance.initialize()
    await application_instance.updater.start_polling()
    await application_instance.start()
    logger.info("Telegram bot has been initialized and started polling.")

@contextlib.asynccontextmanager
async def lifespan(app):
    logger.info("Lifespan event: STARTUP")
    asyncio.create_task(main_bot_setup_and_run())
    yield
    logger.info("Lifespan event: SHUTDOWN")
    if application_instance and application_instance.updater and application_instance.updater.running:
        await application_instance.updater.stop()
    if application_instance and application_instance.running:
        await application_instance.stop()
    if scheduler.running:
        scheduler.shutdown()
    logger.info("Shutdown tasks complete.")

# יצירת אובייקט ה-ASGI הסופי ש-Gunicorn/Uvicorn יריץ
)

# ... (כל הקוד עד להגדרת lifespan) ...
@contextlib.asynccontextmanager
async def lifespan(app):
    # ... (הפונקציה lifespan נשארת כפי שהיא) ...
    logger.info("Lifespan event: STARTUP")
    asyncio.create_task(main_bot_setup_and_run())
    yield
    logger.info("Lifespan event: SHUTDOWN")
    # ... (שאר לוגיקת הכיבוי) ...

# --- הוסף את הקוד הבא ---
# מתאם WSGI -> ASGI עבור אפליקציית ה-Flask
flask_asgi_app = WsgiToAsgi(flask_app)

# יצירת אפליקציית ASGI ראשית שתשלב את הכל
async def asgi_app(scope, receive, send):
    """
    זוהי אפליקציית ה-ASGI הראשית ש-Uvicorn יריץ.
    היא מפעילה את מנגנון ה-lifespan, ומעבירה את בקשות ה-HTTP ל-Flask.
    """
    if scope['type'] == 'lifespan':
        async with lifespan(flask_app):
            await flask_asgi_app(scope, receive, send)
    else:
        await flask_asgi_app(scope, receive, send)

# הרצה מקומית (לצורך פיתוח בלבד)
if __name__ == "__main__":
    logger.info("Running locally with Uvicorn server...")
    uvicorn.run("bot:asgi_app", host="0.0.0.0", port=8000, reload=True)

# הרצה מקומית (לצורך פיתוח בלבד)
if __name__ == "__main__":
    logger.info("Running locally with Uvicorn server...")
    uvicorn.run("bot:asgi_app", host="0.0.0.0", port=8000, reload=True)
