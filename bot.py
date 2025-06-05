# bot.py
import logging
import datetime
import random
import threading
import time
import re
import asyncio
import pytz # הוספת ייבוא ל-pytz

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
from apscheduler.schedulers.background import BackgroundScheduler

import config
import g_sheets
from g_sheets import ConfirmationStatus, PaymentStatus
import graph_generator


# --- הגדרות לוגינג ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO  # ודא שהשורה הזו נראית כך, והפסיק שלפניה תקין אם יש פרמטרים נוספים לפני כן
)
# שורות הלוגינג המפורט (ודא שהן מגיעות *אחרי* basicConfig):
logging.getLogger("telegram.ext.Application").setLevel(logging.DEBUG) # אם החלטת להוסיף את זה
logging.getLogger("telegram.ext.Updater").setLevel(logging.DEBUG)     # אם החלטת להוסיף את זה
logging.getLogger("telegram.ext.Dispatcher").setLevel(logging.DEBUG)  # אם החלטת להוסיף את זה
logging.getLogger("telegram.bot").setLevel(logging.DEBUG)         # אם החלטת להוסיף את זה
logging.getLogger("httpx").setLevel(logging.DEBUG)                # אם החלטת להוסיף את זה

logger = logging.getLogger(__name__) # הלוגר של הקוד שלך
# ... (שאר הקוד שלך) ...

AWAITING_EMAIL_AND_CONFIRMATION = range(1)

application_instance: Application | None = None
flask_app = Flask(__name__)
scheduler = BackgroundScheduler(timezone="Asia/Jerusalem")
bot_thread_event = threading.Event()

# --- פונקציות עזר שהיו קודם ---
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
            await context.bot.send_message(config.ADMIN_USER_ID, f"⚠️ שגיאה ביצירת קישור למשתמש {actual_username} ({user_id}): {e}")
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

# --- בדיקה ראשונית ---
async def simple_start_command_for_full_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"--- FULL BOT (SIMPLIFIED HANDLER): /start received by user {user.id} ({user.username or user.first_name}) ---")
    try:
        await update.message.reply_text('FULL BOT (SIMPLIFIED HANDLER) responding to /start!')
        logger.info(f"--- FULL BOT (SIMPLIFIED HANDLER): Reply sent to user {user.id} ---")
    except Exception as e:
        logger.error(f"--- FULL BOT (SIMPLIFIED HANDLER): Error sending reply to user {user.id}: {e} ---", exc_info=True)
async def general_error_handler_for_full_bot(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("--- FULL BOT (GENERAL ERROR HANDLER): Exception during update processing by dispatcher ---", exc_info=context.error)
# --- הלוגיקה המלאה של ConversationHandler (כרגע בהערה) ---
# async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
#     user = update.effective_user
#     effective_username = user.username or user.first_name or f"User_{user.id}"
#     logger.info(f"User {user.id} ({effective_username}) started the bot (full handler).")
#     # ... (כל הלוגיקה של start_command המקורי מגרסה #42) ...
#     # ... ודא שהוא מסתיים ב- return AWAITING_EMAIL_AND_CONFIRMATION או ConversationHandler.END ...
#     # לדוגמה:
#     today_str, trial_end_str = get_disclaimer_dates()
#     disclaimer_message = (
#         f"היי, זה מצוות הערוץ ״חדר vip -TradeCore״\n\n"
#         f"המנוי שלך (לתקופת הניסיון) יתחיל עם אישור התנאים ויסתיים כעבור {config.TRIAL_PERIOD_DAYS} ימים.\n"
#         f"(לתשומת ליבך, אם תאשר היום {today_str}, הניסיון יסתיים בערך ב-{trial_end_str}).\n\n"
#         f"חשוב להבהיר: 🚫התוכן כאן אינו מהווה ייעוץ או המלצה פיננסית מכל סוג! "
#         f"📌 ההחלטות בסופו של דבר בידיים שלכם – איך לפעול, מתי להיכנס ומתי לצאת מהשוק.\n\n"
#         f"כדי להמשיך, אנא שלח את כתובת האימייל שלך (זו שתשמש לתשלום ב-Gumroad אם תבחר להמשיך) ולאחר מכן את המילה 'מאשר' או 'מקובל'.\n"
#         f"לדוגמה: `myemail@example.com מאשר`"
#     )
#     await update.message.reply_text(disclaimer_message)
#     if not g_sheets.add_new_user_for_disclaimer(user.id, effective_username):
#         if config.ADMIN_USER_ID and config.ADMIN_USER_ID != 0:
#             await context.bot.send_message(config.ADMIN_USER_ID, f"שגיאה בהוספת משתמש {user.id} ל-GSheets בשלב ההצהרה.")
#     job_name = f"disclaimer_warning_{user.id}"
#     # ... (שאר הלוגיקה של תזמון האזהרה) ...
#     context.job_queue.run_once(
#         disclaimer_24h_warning_job_callback,
#         datetime.timedelta(hours=config.REMINDER_MESSAGE_HOURS_BEFORE_WARNING),
#         chat_id=user.id, name=job_name, data={'user_id': user.id}
#     )
#     logger.info(f"Scheduled 24h disclaimer warning for user {user.id} with job name {job_name}")
#     return AWAITING_EMAIL_AND_CONFIRMATION


# async def handle_email_and_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
#     # ... (כל הלוגיקה של handle_email_and_confirmation המקורי מגרסה #42) ...
#     # ... ודא שהוא מסתיים ב- return ConversationHandler.END או מצב אחר ...
#     user = update.effective_user
#     text = update.message.text.strip() 
#     # ... (שאר הלוגיקה) ...
#     # await send_invite_link_or_add_to_channel(context, user.id, effective_username)
#     return ConversationHandler.END


# async def disclaimer_24h_warning_job_callback(context: ContextTypes.DEFAULT_TYPE):
#     # ... (כל הלוגיקה של disclaimer_24h_warning_job_callback המקורי מגרסה #42) ...
#     pass

# async def cancel_request_job_callback(context: ContextTypes.DEFAULT_TYPE):
#     # ... (כל הלוגיקה של cancel_request_job_callback המקורי מגרסה #42) ...
#     pass

# async def cancel_conversation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
#     # ... (כל הלוגיקה של cancel_conversation_command המקורי מגרסה #42) ...
#     return ConversationHandler.END

# --- Webhook של Gumroad (באמצעות Flask) ---
@flask_app.route('/webhook/gumroad', methods=['POST', 'GET'])
def gumroad_webhook_route():
    global application_instance
    logger.info(f"--- GUMROAD WEBHOOK ENDPOINT HIT (METHOD: {request.method}) ---")
    # ... (הלוגיקה של ה-webhook מגרסה #46, שכוללת טיפול ב-form data) ...
    raw_body = request.get_data(as_text=True)
    logger.info(f"Request Raw Body (Webhook): {raw_body[:1000]}...") # רשום רק חלק מהגוף
    data_to_process = None
    if request.method == 'POST':
        content_type = request.headers.get('Content-Type', '').lower()
        if 'application/json' in content_type:
            try: data_to_process = request.json
            except Exception as e: logger.error(f"Error parsing JSON: {e}"); return "Error parsing JSON", 400
            logger.info(f"Received Gumroad POST JSON data: {data_to_process}")
        elif 'application/x-www-form-urlencoded' in content_type:
            try: data_to_process = request.form.to_dict()
            except Exception as e: logger.error(f"Error parsing Form data: {e}"); return "Error parsing Form data", 400
            logger.info(f"Received Gumroad POST Form data (converted to dict): {data_to_process}")
        else:
            logger.warning(f"POST with unexpected Content-Type: {content_type}.")
            return "Unsupported Content-Type for POST", 415

        if data_to_process:
            email = data_to_process.get('email')
            product_identifier = data_to_process.get('permalink') or data_to_process.get('short_product_id') or data_to_process.get('product_id')
            sale_id = data_to_process.get('sale_id') or data_to_process.get('order_number')
            subscription_id = data_to_process.get('subscription_id')
            logger.info(f"Extracted for processing: email='{email}', product_identifier='{product_identifier}', sale_id='{sale_id}', subscription_id='{subscription_id}'")
            
            if not config.GUMROAD_PRODUCT_PERMALINK or config.GUMROAD_PRODUCT_PERMALINK == 'YOUR_GUMROAD_PRODUCT_PERMALINK_HERE':
                logger.error("GUMROAD_PRODUCT_PERMALINK is not configured correctly in config or env variables.")
                return "Server configuration error (Gumroad permalink missing)", 500
            logger.info(f"Comparing with configured GUMROAD_PRODUCT_PERMALINK: '{config.GUMROAD_PRODUCT_PERMALINK}'")

            if product_identifier and product_identifier == config.GUMROAD_PRODUCT_PERMALINK:
                logger.info("Correct product permalink received.")
                if email and sale_id:
                    telegram_user_id_str = g_sheets.update_user_payment_status_from_gumroad(
                        email, str(sale_id), str(subscription_id) if subscription_id else None
                    )
                    if telegram_user_id_str:
                        telegram_user_id = int(telegram_user_id_str)
                        if application_instance and application_instance.job_queue:
                            message_text = (
                                f"💰 תודה על רכישת המנוי דרך Gumroad!\n"
                                f"הגישה שלך לערוץ {config.CHANNEL_USERNAME or config.CHANNEL_ID} חודשה/אושרה.\n"
                                f"פרטי עסקה: {sale_id}"
                            )
                            application_instance.job_queue.run_once(
                                send_async_message, datetime.timedelta(seconds=1), chat_id=telegram_user_id, data={'text': message_text}, name=f"gumroad_confirm_{telegram_user_id}"
                            )
                            logger.info(f"Queued payment confirmation to Telegram user {telegram_user_id} for Gumroad sale {sale_id}")
                        else: logger.error("Telegram application_instance or job_queue not available for Gumroad confirmation.")
                    else: logger.warning(f"Gumroad sale processed for email {email}, but no matching Telegram user ID found/updated in GSheet.")
                    return "Webhook data processed", 200
                else:
                    logger.error(f"Gumroad POST for correct product, but missing email or sale_id: {data_to_process}")
                    return "Missing email or sale_id", 400
            else:
                logger.warning(f"Webhook for wrong Gumroad product: Received='{product_identifier}', Expected='{config.GUMROAD_PRODUCT_PERMALINK}'")
                return "Webhook for wrong product", 200
        else:
            logger.warning("No data could be processed from POST request.")
            return "Could not process data", 400
    elif request.method == 'GET':
        logger.info("Received GET to Gumroad webhook endpoint (test/ping).")
        return "GET received. Expecting POST for sales.", 200
    return "Method not handled", 405

@flask_app.route('/health', methods=['GET'])
def health_check():
    return "OK", 200

# --- משימות מתוזמנות עם APScheduler ---
def check_trials_and_reminders_job():
    global application_instance
    logger.info("APScheduler: Running check_trials_and_reminders_job.")
    if not (application_instance and application_instance.job_queue):
        logger.error("APScheduler: Telegram application_instance/job_queue not ready for trial checks.")
        return
    # ... (הלוגיקה של check_trials_and_reminders_job מגרסה #42, עם הקריאה ל-job_queue עבור async_handle_user_removal) ...
    users_to_process = g_sheets.get_users_for_trial_reminder_or_removal()
    for item in users_to_process:
        action = item['action']
        user_gs_data = item['data']
        user_id_str = user_gs_data.get(g_sheets.COL_USER_ID)
        if not user_id_str: continue
        user_id = int(user_id_str)
        email = user_gs_data.get(g_sheets.COL_EMAIL)
        if action == 'send_trial_end_reminder':
            logger.info(f"APScheduler: Sending trial end reminder to user {user_id} (email: {email})")
            # ... (הודעת התזכורת המלאה) ...
            reminder_text = (
                f"היי, כאן צוות {config.CHANNEL_USERNAME or 'TradeCore VIP'} 👋\n\n"
                f"שבוע הניסיון שלך בערוץ ״חדר vip -TradeCore״ עומד להסתיים.\n"
                f"איך היה? הרגשת שיפור בתיק שלך? קיבלת ידע וניתוחים שלא יצא לך לדעת? הרגשת יחס אישי?\n\n"
                f"אם אתה רוצה להמשיך – העלות {config.PAYMENT_AMOUNT_ILS}₪ לחודש.\n"
                f"🔗 קישור לתשלום מאובטח דרך Gumroad (תומך PayPal ועוד): {config.GUMROAD_PRODUCT_PERMALINK or 'אנא פנה למנהל לקבלת קישור'}\n"
                f"(לחלופין, אם יש בעיה עם Gumroad, ניתן לשלם ישירות דרך PayPal: {config.PAYPAL_ME_LINK} - אם תבחר באפשרות זו, אנא שלח צילום מסך של התשלום למנהל לאישור ידני)\n\n"
                f"מי שלא מחדש – יוסר אוטומטית מהערוץ בימים הקרובים.\n"
                f"עסקה אחת ואתה משלש את ההשקעה!! 😉"
            )
            application_instance.job_queue.run_once(
                send_async_message, datetime.timedelta(seconds=1), chat_id=user_id, data={'text': reminder_text}, name=f"trial_reminder_{user_id}"
            )
            g_sheets.update_user_data(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.PENDING_PAYMENT_AFTER_TRIAL.value})
        elif action == 'remove_user_no_payment':
            logger.info(f"APScheduler: Queuing removal task for user {user_id} (email: {email}).")
            application_instance.job_queue.run_once(
                async_handle_user_removal, datetime.timedelta(seconds=1), 
                chat_id=user_id, data={'user_id': user_id}, name=f"exec_removal_{user_id}"
            )


def post_scheduled_content_job():
    global application_instance
    logger.info("APScheduler: Attempting to post scheduled content.")
    if not (application_instance and application_instance.job_queue):
        logger.error("APScheduler: Telegram application_instance/job_queue not ready for content posting.")
        return
    # ... (הלוגיקה של post_scheduled_content_job מגרסה #42, עם הקריאה ל-job_queue עבור send_async_photo_message) ...
    selected_stock = random.choice(config.STOCK_SYMBOLS_LIST) if config.STOCK_SYMBOLS_LIST else None
    if not selected_stock:
        logger.warning("APScheduler: STOCK_SYMBOLS_LIST is empty. Cannot post content.")
        return
    logger.info(f"APScheduler: Selected stock {selected_stock} for posting.")
    try:
        image_stream, analysis_text = graph_generator.create_stock_graph_and_text(selected_stock)
        if image_stream and analysis_text:
            job_data = {'chat_id': config.CHANNEL_ID, 'photo': image_stream, 'caption': analysis_text}
            application_instance.job_queue.run_once(
                send_async_photo_message, datetime.timedelta(seconds=1), data=job_data, name=f"content_post_photo_{selected_stock}"
            )
            logger.info(f"APScheduler: Queued photo content for {selected_stock} to channel {config.CHANNEL_ID}")
        else:
            logger.warning(f"APScheduler: Failed to generate graph/text for {selected_stock}. Details: {analysis_text}")
    except Exception as e:
        logger.error(f"APScheduler: Error in post_scheduled_content_job for {selected_stock}: {e}", exc_info=True)


# --- פונקציית main ואתחול ---
async def setup_bot_and_scheduler():
    global application_instance, scheduler
    logger.info("Attempting to setup bot and scheduler...")

    if not config.TELEGRAM_BOT_TOKEN:
        logger.critical("setup_bot_and_scheduler: TELEGRAM_BOT_TOKEN is not set. Cannot start bot.")
        return False

    if not g_sheets.get_sheet():
        logger.critical("setup_bot_and_scheduler: Could not connect to Google Sheets. Bot setup failed.")
        return False

    builder = Application.builder().token(config.TELEGRAM_BOT_TOKEN)
    application_instance = builder.build()

    # --- הפעל את ה-handler הפשוט לבדיקה ראשונית ---
    application_instance.add_handler(CommandHandler("start", simple_start_command_for_full_bot))
    logger.info("Added SIMPLIFIED /start handler for initial testing.")
    
    # --- ה-ConversationHandler המלא (כרגע בהערה) ---
    # conv_handler = ConversationHandler(
    #     entry_points=[CommandHandler('start', start_command)], # כאן תהיה הפונקציה המלאה start_command
    #     states={
    #         AWAITING_EMAIL_AND_CONFIRMATION: [
    #             MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_and_confirmation)
    #         ],
    #     },
    #     fallbacks=[CommandHandler('cancel', cancel_conversation_command)],
    # )
    # application_instance.add_handler(conv_handler)
    # logger.info("Full ConversationHandler (currently commented out) would be added here.")


    # הוסף error handler כללי
    async def general_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("--- GENERAL EXCEPTION DURING UPDATE PROCESSING ---", exc_info=context.error)
        # נסה להודיע למשתמש אם אפשר
        if isinstance(update, Update) and update.effective_message:
            try: await update.effective_message.reply_text("אופס! אירעה שגיאה בעיבוד. אנא נסה שוב או פנה למנהל.")
            except Exception: pass
        elif isinstance(update, Update) and update.callback_query:
            try: await update.callback_query.answer("שגיאה בעיבוד.", show_alert=True)
            except Exception: pass
    application_instance.add_error_handler(general_error_handler)
    logger.info("Added general error handler.")


    if not scheduler.running:
        try:
            scheduler.add_job(check_trials_and_reminders_job, 'cron', hour=9, minute=5, id="check_trials_job_v3", replace_existing=True, misfire_grace_time=3600)
            logger.info("APScheduler: Scheduled 'check_trials_and_reminders_job' daily at 09:05 (Asia/Jerusalem).")

            def schedule_daily_content_posts():
                if not (application_instance and application_instance.job_queue): return
                for job in scheduler.get_jobs():
                    if job.id and job.id.startswith("daily_content_post_"):
                        try: scheduler.remove_job(job.id)
                        except Exception: pass
                num_posts = random.randint(1, config.MAX_POSTS_PER_DAY)
                logger.info(f"APScheduler: Scheduling {num_posts} content posts for today.")
                for i in range(num_posts):
                    hour = random.randint(config.POSTING_SCHEDULE_HOURS_START, config.POSTING_SCHEDULE_HOURS_END -1 if config.POSTING_SCHEDULE_HOURS_END > config.POSTING_SCHEDULE_HOURS_START else config.POSTING_SCHEDULE_HOURS_START)
                    minute = random.randint(0, 59)
                    job_id = f"daily_content_post_{i}_{hour}_{minute}"
                    try:
                        scheduler.add_job(post_scheduled_content_job, 'cron', hour=hour, minute=minute, id=job_id, replace_existing=True, misfire_grace_time=600)
                        logger.info(f"APScheduler: Scheduled content post with ID {job_id} at {hour:02d}:{minute:02d}.")
                    except Exception as e_add_job: logger.error(f"APScheduler: Failed to add content job {job_id}: {e_add_job}")
            
            schedule_daily_content_posts()
            scheduler.add_job(schedule_daily_content_posts, 'cron', hour=0, minute=10, id="reschedule_content_job_v3", replace_existing=True, misfire_grace_time=3600)
            logger.info("APScheduler: Scheduled 'schedule_daily_content_posts' daily at 00:10 (Asia/Jerusalem).")
            
            scheduler.start()
            logger.info("APScheduler: Scheduler started.")
        except Exception as e_sched:
            logger.error(f"Failed to start or schedule APScheduler jobs: {e_sched}", exc_info=True)
            return False
    else:
        logger.info("APScheduler: Scheduler already running.")

    try:
        logger.info("Attempting to initialize and start Telegram bot components...")
        await application_instance.initialize()
        logger.info("Application initialized.")
        if not application_instance.updater:
             application_instance.updater = application_instance.create_updater()
             logger.info("Updater created.")
        await application_instance.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Updater polling started.")
        await application_instance.start()
        logger.info("Application dispatcher started. Telegram bot is live and polling.")
        return True
    except Exception as e_telegram_start:
        logger.error(f"Failed to initialize or start Telegram bot: {e_telegram_start}", exc_info=True)
        return False

def run_bot_logic_in_thread_target():
    global bot_thread_event, application_instance, scheduler
    logger.info("Bot logic thread starting...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot_started_successfully = False
    try:
        bot_started_successfully = loop.run_until_complete(setup_bot_and_scheduler())
        if bot_started_successfully:
            logger.info("Bot and scheduler setup complete in thread. Main polling loop should be active.")
            while not bot_thread_event.is_set():
                # Check if polling is still active, this is a bit indirect
                if not (application_instance and application_instance.updater and application_instance.updater.running):
                    logger.warning("Updater polling seems to have stopped. Bot thread will exit.")
                    break
                time.sleep(5) # Keep thread alive and periodically check
            logger.info("Bot thread main loop finished or event was set.")
        else:
            logger.error("Bot and scheduler setup FAILED in thread. Thread will exit.")
            
    except Exception as e:
        logger.critical(f"Unhandled exception in bot_thread's main execution: {e}", exc_info=True)
    finally:
        logger.info("Bot logic thread target function is finishing. Cleaning up...")
        # Graceful shutdown attempt
        if application_instance:
            if application_instance.updater and application_instance.updater.running:
                logger.info("Stopping PTB updater in thread finally block...")
                loop.run_until_complete(application_instance.updater.stop())
            if application_instance.running:
                 logger.info("Stopping PTB application in thread finally block...")
                 loop.run_until_complete(application_instance.stop())
        if scheduler.running:
            scheduler.shutdown(wait=False) # wait=False as loop might be closing
            logger.info("APScheduler shutdown in thread.")
        if not loop.is_closed():
            loop.close()
            logger.info("Asyncio event loop closed in bot thread.")

# --- קריאה לאתחול הבוט וה-Scheduler ---
if __name__ != '__main__': # ירוץ כאשר Gunicorn מייבא את הקובץ
    logger.info("Module bot.py imported by a WSGI server (e.g., Gunicorn).")
    logger.info("Attempting to start bot logic in a separate thread...")
    # ודא שהלוגר מוגדר לפני ש-thread מתחיל להשתמש בו
    if not bot_thread_event.is_set(): # התחל את ה-thread רק אם הוא לא כבר רץ או בתהליך עצירה
        bot_main_thread = threading.Thread(target=run_bot_logic_in_thread_target, daemon=True, name="BotLogicThread")
        bot_main_thread.start()
        logger.info("BotLogicThread started.")
    else:
        logger.info("BotLogicThread event is already set or thread might be running; not starting new one.")

elif __name__ == '__main__':
    # הרצה מקומית לפיתוח (לא דרך Gunicorn)
    logger.info("Running bot.py directly for local development.")
    # כאן אפשר להוסיף הרצה של Flask אם רוצים לבדוק גם Webhook מקומית
    # flask_dev_thread = threading.Thread(target=lambda: flask_app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False), daemon=True)
    # flask_dev_thread.start()
    # logger.info("Flask development server (for webhook testing) started in a thread on port 5001.")
    
    main_event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(main_event_loop)
    try:
        if main_event_loop.run_until_complete(setup_bot_and_scheduler()):
            logger.info("Local bot setup complete. Polling should be active. Press Ctrl+C to exit.")
            main_event_loop.run_forever() # Keep main thread alive for asyncio tasks
        else:
            logger.error("Local bot setup failed.")
    except KeyboardInterrupt:
        logger.info("Shutdown requested via KeyboardInterrupt (local run).")
    except Exception as e:
        logger.critical(f"Critical error in local main execution: {e}", exc_info=True)
    finally:
        logger.info("Attempting graceful shutdown for local run...")
        bot_thread_event.set() # Signal the bot thread to stop, if it's running

        async def shutdown_local_async_components():
            if application_instance:
                if application_instance.updater and application_instance.updater.running:
                    await application_instance.updater.stop()
                if application_instance.running:
                    await application_instance.stop()
                # await application_instance.shutdown() # Use for ApplicationBuilder persistence
            if scheduler.running:
                scheduler.shutdown(wait=True) # Wait for jobs to finish if possible
        
        try:
            shutdown_loop = asyncio.get_event_loop()
            if shutdown_loop.is_running(): # Should be the main_event_loop
                 # Schedule shutdown tasks on the existing loop
                 tasks = asyncio.gather(shutdown_local_async_components(), return_exceptions=True)
                 shutdown_loop.run_until_complete(tasks)
            else: # Fallback if the loop isn't running (e.g., setup failed early)
                 asyncio.run(shutdown_local_async_components())
        except RuntimeError: # No running loop, try a new one for shutdown
             asyncio.run(shutdown_local_async_components())
        except Exception as e_shutdown:
            logger.error(f"Error during local async components shutdown: {e_shutdown}")

        logger.info("Local bot execution finished.")
