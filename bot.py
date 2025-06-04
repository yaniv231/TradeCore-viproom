# bot.py
import logging
import datetime
import random
import threading
import time
import re
import asyncio # נדרש להרצת main

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    # CallbackQueryHandler, # אם נשתמש בכפתורים Inline - לא בשימוש כרגע
    # JobQueue # JobQueue מובנה ב-Application
)
from flask import Flask, request, abort
from apscheduler.schedulers.background import BackgroundScheduler

# --- ייבוא המודולים שלנו ---
import config
import g_sheets
from g_sheets import ConfirmationStatus, PaymentStatus # לייבוא קל יותר של הסטטוסים
import graph_generator # <--- ייבוא חשוב מאוד!

# --- הגדרות לוגינג ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- משתנים גלובליים ל-ConversationHandler (מצבים) ---
AWAITING_EMAIL_AND_CONFIRMATION = range(1) # רק מצב אחד אחרי start

# --- אובייקטים גלובליים (בזהירות) ---
application_instance: Application | None = None # הגדרה עם Type Hinting
flask_app = Flask(__name__)
scheduler = BackgroundScheduler(timezone="Asia/Jerusalem")

# --- פונקציות עזר לבוט ---
def get_disclaimer_dates():
    today = datetime.date.today()
    trial_end_date = today + datetime.timedelta(days=config.TRIAL_PERIOD_DAYS)
    return today.strftime("%d/%m/%Y"), trial_end_date.strftime("%d/%m/%Y")

async def send_invite_link_or_add_to_channel(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str | None):
    actual_username = username or f"User {user_id}"
    try:
        expire_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=config.TRIAL_PERIOD_DAYS + 2)
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=config.CHANNEL_ID,
            name=f"Trial for {actual_username}",
            expire_date=expire_date,
            member_limit=1
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
        logger.error(f"Could not create invite link for user {user_id}: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text="אירעה שגיאה ביצירת קישור ההצטרפות לערוץ. אנא פנה למנהל לקבלת סיוע."
        )
        if config.ADMIN_USER_ID:
            try:
                await context.bot.send_message(
                    chat_id=config.ADMIN_USER_ID,
                    text=f"⚠️ שגיאה ביצירת קישור הצטרפות למשתמש {actual_username} ({user_id}) לערוץ {config.CHANNEL_ID}.\nשגיאה: {e}"
                )
            except Exception as admin_err:
                logger.error(f"Failed to send error notification to admin: {admin_err}")
        return False

async def send_async_message(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    await context.bot.send_message(chat_id=job_data['chat_id'], text=job_data['text'])

async def send_async_photo_message(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    photo_stream = job_data['photo']
    photo_stream.seek(0)
    try:
        await context.bot.send_photo(
            chat_id=job_data['chat_id'],
            photo=photo_stream,
            caption=job_data['caption']
        )
    finally:
        photo_stream.close()

async def async_handle_user_removal(context: ContextTypes.DEFAULT_TYPE):
    """
    פונקציה אסינכרונית לטיפול בהסרת משתמש מהערוץ, שליחת הודעה ועדכון GSheet.
    נקראת דרך ה-JobQueue.
    """
    job_data = context.job.data
    user_id = job_data['user_id']
    logger.info(f"Async job: Starting removal process for user {user_id}")
    try:
        await context.bot.ban_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id)
        logger.info(f"Async job: Banned user {user_id} from channel {config.CHANNEL_ID}")
        await asyncio.sleep(1) # המתנה קצרה לפני unban
        await context.bot.unban_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id, only_if_banned=True)
        logger.info(f"Async job: Unbanned user {user_id} from channel {config.CHANNEL_ID} (to allow rejoining if they pay).")
        
        removal_text = (f"הגישה שלך לערוץ {config.CHANNEL_USERNAME or 'TradeCore VIP'} הופסקה "
                        f"מכיוון שלא התקבל תשלום לאחר תקופת הניסיון. "
                        f"נשמח לראותך שוב אם תחליט להצטרף ולחדש את המנוי!")
        await context.bot.send_message(chat_id=user_id, text=removal_text)
        logger.info(f"Async job: Sent removal notice to user {user_id}.")
        
        g_sheets.update_user_status(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.EXPIRED_NO_PAYMENT.value})
        logger.info(f"Async job: Updated GSheet status for user {user_id} to EXPIRED_NO_PAYMENT.")

    except Exception as e:
        logger.error(f"Async job: Error during removal process for user {user_id}: {e}")
        # גם אם יש שגיאה בפעולת הטלגרם, נעדכן את הסטטוס ב-GSheet
        g_sheets.update_user_status(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.EXPIRED_NO_PAYMENT.value})
        logger.info(f"Async job: Updated GSheet status for user {user_id} to EXPIRED_NO_PAYMENT despite Telegram API error during removal.")


# --- תהליך אישור התנאים (ConversationHandler) ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    effective_username = user.username or user.first_name or f"User_{user.id}"
    logger.info(f"User {user.id} ({effective_username}) started the bot.")
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
            return AWAITING_EMAIL_AND_CONFIRMATION # חזור למצב המתנה לאימייל ואישור
    
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
    
    if not g_sheets.add_new_user_for_disclaimer(user.id, effective_username):
        if config.ADMIN_USER_ID:
            await context.bot.send_message(config.ADMIN_USER_ID, f"שגיאה בהוספת משתמש {user.id} ל-GSheets בשלב ההצהרה.")

    current_jobs = context.job_queue.get_jobs_by_name(f"disclaimer_warning_{user.id}")
    for job in current_jobs:
        job.schedule_removal()
    context.job_queue.run_once(
        disclaimer_24h_warning_job_callback,
        datetime.timedelta(hours=config.REMINDER_MESSAGE_HOURS_BEFORE_WARNING), # שימוש בקבוע מהקונפיג
        chat_id=user.id, # משמש לזיהוי ה-job, לא ישירות לשליחת ההודעה
        name=f"disclaimer_warning_{user.id}",
        data={'user_id': user.id} # העברת user_id ל-callback
    )
    logger.info(f"Scheduled 24h disclaimer warning for user {user.id}")
    return AWAITING_EMAIL_AND_CONFIRMATION

async def handle_email_and_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    text = update.message.text.strip() 
    effective_username = user.username or user.first_name or f"User_{user.id}"
    logger.info(f"User {user.id} sent text for disclaimer confirmation: {text}")

    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text)
    confirmation_keywords = ["מאשר", "מקובל", "אישור", "ok", "yes", "כן"]
    text_lower = text.lower()
    confirmation_keyword_found = any(keyword in text_lower for keyword in confirmation_keywords)

    if email_match and confirmation_keyword_found:
        email = email_match.group(0).lower()
        logger.info(f"User {user.id} provided email {email} and confirmed disclaimer.")

        g_sheets.update_user_email_and_confirmation(user.id, email, ConfirmationStatus.CONFIRMED_DISCLAIMER)
        g_sheets.start_user_trial(user.id)

        current_jobs = context.job_queue.get_jobs_by_name(f"disclaimer_warning_{user.id}")
        for job in current_jobs:
            job.schedule_removal()
        logger.info(f"Removed disclaimer warning job for user {user.id} after confirmation.")
        
        cancel_jobs = context.job_queue.get_jobs_by_name(f"cancel_request_{user.id}")
        for job in cancel_jobs:
            job.schedule_removal()

        await send_invite_link_or_add_to_channel(context, user.id, effective_username)
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "לא הצלחתי לזהות כתובת אימייל תקינה ואישור ('מאשר' או 'מקובל').\n"
            "אנא שלח שוב בפורמט: `כתובת@אימייל.קום מאשר`"
        )
        return AWAITING_EMAIL_AND_CONFIRMATION # הישאר באותו מצב

async def disclaimer_24h_warning_job_callback(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id = job_data['user_id']
    logger.info(f"Running 24h disclaimer warning job callback for user {user_id}")
    user_gs_data = g_sheets.get_user_data(user_id)

    if user_gs_data and user_gs_data.get(g_sheets.COL_CONFIRMATION_STATUS) == ConfirmationStatus.PENDING_DISCLAIMER.value:
        bot_username = (await context.bot.get_me()).username
        warning_message = (
            f"⚠️ אזהרה אחרונה ⚠️\n\n"
            f"לא קיבלנו ממך אישור, והבקשה שלך להצטרפות לערוץ עדיין ממתינה.\n\n"
            f"אם לא נקבל מענה בהקדם – הבקשה תבוטל ותוסר. זהו תזכורת אחרונה.\n\n"
            f"צוות הערוץ ״חדר vip - TradeCore ״ http://t.me/{bot_username}"
        )
        await context.bot.send_message(chat_id=user_id, text=warning_message)
        g_sheets.update_user_disclaimer_status(user_id, ConfirmationStatus.WARNED_NO_DISCLAIMER)
        logger.info(f"Sent final disclaimer warning to user {user_id}")

        current_cancel_jobs = context.job_queue.get_jobs_by_name(f"cancel_request_{user_id}")
        for c_job in current_cancel_jobs:
            c_job.schedule_removal()
        context.job_queue.run_once(
            cancel_request_job_callback,
            datetime.timedelta(hours=config.HOURS_FOR_FINAL_CONFIRMATION_AFTER_WARNING), # שימוש בקבוע מהקונפיג
            chat_id=user_id, # שוב, רק לזיהוי ה-job
            name=f"cancel_request_{user_id}",
            data={'user_id': user_id}
        )
    else:
        logger.info(f"User {user_id} already confirmed or not in pending state. Warning job for disclaimer skipped.")

async def cancel_request_job_callback(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id = job_data['user_id']
    logger.info(f"Running final cancellation job callback for user {user_id} (disclaimer)")
    user_gs_data = g_sheets.get_user_data(user_id)
    if user_gs_data and user_gs_data.get(g_sheets.COL_CONFIRMATION_STATUS) == ConfirmationStatus.WARNED_NO_DISCLAIMER.value:
        g_sheets.update_user_disclaimer_status(user_id, ConfirmationStatus.CANCELLED_NO_DISCLAIMER)
        await context.bot.send_message(chat_id=user_id, text="בקשתך להצטרפות לערוץ בוטלה עקב חוסר מענה לאישור התנאים.")
        logger.info(f"Cancelled request for user {user_id} due to no final disclaimer confirmation.")

async def cancel_conversation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    logger.info(f"User {user.id} canceled the conversation using /cancel.")
    await update.message.reply_text(
        'תהליך ההרשמה בוטל. תוכל להתחיל מחדש על ידי שליחת /start.',
        reply_markup=ReplyKeyboardRemove()
    )
    user_gs_data = g_sheets.get_user_data(user.id)
    if user_gs_data and user_gs_data.get(g_sheets.COL_CONFIRMATION_STATUS) in [
        ConfirmationStatus.PENDING_DISCLAIMER.value, 
        ConfirmationStatus.WARNED_NO_DISCLAIMER.value
    ]:
        g_sheets.update_user_disclaimer_status(user.id, ConfirmationStatus.CANCELLED_NO_DISCLAIMER)
        # בטל משימות תזכורת אם קיימות
        for job_name_suffix in [f"disclaimer_warning_{user.id}", f"cancel_request_{user.id}"]:
            current_jobs = context.job_queue.get_jobs_by_name(job_name_suffix)
            for job in current_jobs:
                job.schedule_removal()
    return ConversationHandler.END

# --- Webhook של Gumroad (באמצעות Flask) ---
# bot.py - קטע ה-Flask app
@flask_app.route('/webhook/gumroad', methods=['POST', 'GET']) # הוספנו GET לבדיקה קלה יותר מהדפדפן
def gumroad_webhook_route():
    global application_instance
    logger.info(f"--- GUMROAD WEBHOOK ENDPOINT HIT (METHOD: {request.method}) ---")
    logger.info(f"Request Headers: {request.headers}")
    raw_body = request.get_data(as_text=True)
    logger.info(f"Request Raw Body: {raw_body}")

    data_to_process = None

    if request.method == 'POST':
        content_type = request.headers.get('Content-Type', '').lower()
        if 'application/json' in content_type:
            try:
                data_to_process = request.json
                logger.info(f"Received Gumroad POST JSON data: {data_to_process}")
            except Exception as e:
                logger.error(f"Error parsing JSON data from POST request: {e}")
                return "Error parsing JSON data", 400
        elif 'application/x-www-form-urlencoded' in content_type:
            try:
                data_to_process = request.form.to_dict()
                logger.info(f"Received Gumroad POST Form data (converted to dict): {data_to_process}")
            except Exception as e:
                logger.error(f"Error parsing Form data from POST request: {e}")
                return "Error parsing Form data", 400
        else:
            logger.warning(f"Received POST request with unexpected Content-Type: {content_type}")
            # נסה בכל זאת לקרוא את הגוף אם הוא לא גדול מדי, למקרה חירום
            if len(raw_body) < 10000: # הגנה מפני גוף גדול מדי
                 logger.info(f"Attempting to process raw body for unexpected POST: {raw_body}")
                 # כאן אפשר להוסיף לוגיקה לפרסור ידני אם צריך, אבל זה לא סטנדרטי
            return "Unsupported Content-Type for POST", 415

        if data_to_process:
            email = data_to_process.get('email')
            # Gumroad שולח 'permalink' עבור המוצר שנמכר, וגם 'product_permalink' שהוא ה-URL המלא.
            # עדיף להשתמש ב-'permalink' (שהוא כמו ה-slug/ID) להשוואה עם מה ששמור ב-config.
            product_identifier = data_to_process.get('permalink') or data_to_process.get('short_product_id') # ה-permalink הקצר
            
            # אם ה-permalink הקצר לא קיים, נסה להשתמש ב-product_id אם הוא זמין (לפעמים Gumroad שולח אותו)
            if not product_identifier:
                product_identifier = data_to_process.get('product_id')

            sale_id = data_to_process.get('sale_id') or data_to_process.get('order_number') # השתמש במזהה מכירה או מספר הזמנה
            subscription_id = data_to_process.get('subscription_id') # למקרה של מנויים חוזרים

            logger.info(f"Extracted for processing: email='{email}', product_identifier='{product_identifier}', sale_id='{sale_id}', subscription_id='{subscription_id}'")
            logger.info(f"Comparing with configured GUMROAD_PRODUCT_PERMALINK: '{config.GUMROAD_PRODUCT_PERMALINK}'")


            if product_identifier and product_identifier == config.GUMROAD_PRODUCT_PERMALINK:
                logger.info("Correct product permalink received.")
                if email and sale_id:
                    telegram_user_id_str = g_sheets.update_user_payment_status_from_gumroad(
                        email, 
                        str(sale_id), # ודא שזה תמיד מחרוזת
                        str(subscription_id) if subscription_id else None
                    )
                    if telegram_user_id_str:
                        telegram_user_id = int(telegram_user_id_str)
                        if application_instance:
                            message_text = (
                                f"💰 תודה על רכישת המנוי דרך Gumroad!\n"
                                f"הגישה שלך לערוץ {config.CHANNEL_USERNAME or config.CHANNEL_ID} חודשה/אושרה.\n"
                                f"פרטי עסקה: {sale_id}"
                            )
                            application_instance.job_queue.run_once(
                                send_async_message, 0, chat_id=telegram_user_id, data={'text': message_text}, name=f"gumroad_confirm_{telegram_user_id}"
                            )
                            logger.info(f"Queued payment confirmation to Telegram user {telegram_user_id} for Gumroad sale {sale_id}")
                            # כאן תוכל להוסיף לוגיקה נוספת אם צריך, כמו לוודא שהמשתמש בערוץ
                        else:
                            logger.error("Telegram application_instance not available for Gumroad confirmation (webhook).")
                    else:
                        logger.warning(f"Gumroad sale processed for email {email}, but no matching Telegram user ID found/updated in GSheet.")
                    return "Webhook data processed", 200
                else:
                    logger.error(f"Gumroad POST webhook for correct product, but missing email or sale_id: {data_to_process}")
                    return "Missing email or sale_id in payload", 400
            else:
                logger.warning(f"Webhook for wrong Gumroad product: Received permalink='{product_identifier}', Expected='{config.GUMROAD_PRODUCT_PERMALINK}'")
                return "Webhook for wrong product (but endpoint was hit)", 200 # עדיין החזר 200 כדי שגאמרוד לא ינסה שוב ושוב
        else:
            logger.warning("No data could be processed from the POST request.")
            return "Could not process data from POST request", 400

    elif request.method == 'GET':
        logger.info("Received GET request to Gumroad webhook endpoint (likely a manual test or simple ping).")
        return "GET request received. This endpoint expects POST from Gumroad for sales.", 200
    
    return "Request method not explicitly handled", 405 # Method Not Allowed

# --- משימות מתוזמנות עם APScheduler ---
def check_trials_and_reminders_job():
    global application_instance
    logger.info("APScheduler: Running check_trials_and_reminders job.")
    if not application_instance:
        logger.error("APScheduler: Telegram application_instance not available for trial checks.")
        return

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
            reminder_text = (
                f"היי, כאן צוות {config.CHANNEL_USERNAME or 'TradeCore VIP'} 👋\n\n"
                f"שבוע הניסיון שלך בערוץ ״חדר vip -TradeCore״ עומד להסתיים.\n"
                f"איך היה? הרגשת שיפור בתיק שלך? קיבלת ידע וניתוחים שלא יצא לך לדעת? הרגשת יחס אישי?\n\n"
                f"אם אתה רוצה להמשיך – העלות {config.PAYMENT_AMOUNT_ILS}₪ לחודש.\n"
                f"🔗 קישור לתשלום מאובטח דרך Gumroad (תומך PayPal ועוד): {config.GUMROAD_PRODUCT_PERMALINK}\n"
                f"(לחלופין, אם יש בעיה עם Gumroad, ניתן לשלם ישירות דרך PayPal: {config.PAYPAL_ME_LINK} - אם תבחר באפשרות זו, אנא שלח צילום מסך של התשלום למנהל לאישור ידני)\n\n"
                f"מי שלא מחדש – יוסר אוטומטית מהערוץ בימים הקרובים.\n"
                f"עסקה אחת ואתה משלש את ההשקעה!! 😉"
            )
            application_instance.job_queue.run_once(
                send_async_message, 0, chat_id=user_id, data={'text': reminder_text}, name=f"trial_reminder_{user_id}"
            )
            g_sheets.update_user_status(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.PENDING_PAYMENT_AFTER_TRIAL.value})

        elif action == 'remove_user_no_payment':
            logger.info(f"APScheduler: Queuing removal task for user {user_id} (email: {email}) due to no payment after trial.")
            application_instance.job_queue.run_once(
                async_handle_user_removal, # הפונקציה האסינכרונית החדשה
                0,
                chat_id=user_id, # לזיהוי ה-job
                data={'user_id': user_id},
                name=f"exec_removal_{user_id}"
            )

def post_scheduled_content_job():
    global application_instance
    logger.info("APScheduler: Attempting to post scheduled content.")
    if not application_instance:
        logger.error("APScheduler: Telegram application_instance not available for posting content.")
        return

    selected_stock = random.choice(config.STOCK_SYMBOLS_LIST)
    logger.info(f"APScheduler: Selected stock {selected_stock} for posting.")

    # ---- הודעת טקסט פשוטה לבדיקה ----
    try:
        current_time_jerusalem = datetime.datetime.now(datetime.timezone.utc).astimezone(pytz.timezone('Asia/Jerusalem'))
        test_message = f"📢 בדיקה אוטומטית מהבוט! 📢\nמניה נבחרה (ללא גרף): {selected_stock}\nשעה: {current_time_jerusalem.strftime('%Y-%m-%d %H:%M:%S %Z')}"

        if application_instance and config.CHANNEL_ID:
            application_instance.job_queue.run_once(
                send_async_message, 0, data={'chat_id': config.CHANNEL_ID, 'text': test_message}, name=f"test_content_post_{selected_stock}"
            )
            logger.info(f"APScheduler: Queued TEST text content for {selected_stock} to channel {config.CHANNEL_ID}")
        else:
            logger.error("APScheduler: application_instance or CHANNEL_ID is missing for test message.")
        return # דלג על יצירת הגרף לצורך הבדיקה הזו
    except Exception as e_test:
        logger.error(f"APScheduler: Error during simple text test post: {e_test}", exc_info=True)
    # ---- סוף הודעת טקסט פשוטה ----

    # # # קוד יצירת הגרף המקורי (כרגע בקומנט לצורך הבדיקה)
    # logger.info(f"APScheduler: Selected stock {selected_stock} for posting.")
    # try:
    #     image_stream, analysis_text = graph_generator.create_stock_graph_and_text(selected_stock)

    #     if image_stream and analysis_text:
    #         job_data = {
    #             'chat_id': config.CHANNEL_ID,
    #             'photo': image_stream,
    #             'caption': analysis_text
    #         }
    #         application_instance.job_queue.run_once(
    #             send_async_photo_message, 0, data=job_data, name=f"content_post_photo_{selected_stock}"
    #         )
    #         logger.info(f"APScheduler: Queued photo content for {selected_stock} to channel {config.CHANNEL_ID}")
    #     else:
    #         logger.warning(f"APScheduler: Failed to generate graph or text for {selected_stock}. Details: {analysis_text}")
    # except Exception as e:
    #     logger.error(f"APScheduler: Error posting scheduled content for {selected_stock}: {e}", exc_info=True)
    try:
        image_stream, analysis_text = graph_generator.create_stock_graph_and_text(selected_stock)
        
        if image_stream and analysis_text:
            job_data = {
                'chat_id': config.CHANNEL_ID,
                'photo': image_stream, # זה BytesIO
                'caption': analysis_text
            }
            application_instance.job_queue.run_once(
                send_async_photo_message, 0, data=job_data, name=f"content_post_photo_{selected_stock}"
            )
            logger.info(f"APScheduler: Queued photo content for {selected_stock} to channel {config.CHANNEL_ID}")
        else:
            logger.warning(f"APScheduler: Failed to generate graph or text for {selected_stock}. Details: {analysis_text}")
    except Exception as e:
        logger.error(f"APScheduler: Error posting scheduled content for {selected_stock}: {e}", exc_info=True)


# --- פונקציית main ואתחול ---
async def setup_bot_and_scheduler():
    global application_instance, scheduler

    if not g_sheets.get_sheet(): # בדוק חיבור ל-Google Sheets
        logger.critical("CRITICAL: Could not connect to Google Sheets. Please check credentials and sheet ID/name. Bot exiting.")
        exit() # יציאה אם אין חיבור ל-GSHEETS כי הבוט לא יוכל לתפקד

    builder = Application.builder().token(config.TELEGRAM_BOT_TOKEN)
    application_instance = builder.build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_command)],
        states={
            AWAITING_EMAIL_AND_CONFIRMATION: [ # השתמש בקבוע הנכון
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_and_confirmation)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation_command)],
    )
    application_instance.add_handler(conv_handler)

    if not scheduler.running:
        scheduler.add_job(check_trials_and_reminders_job, 'cron', hour=9, minute=1, id="check_trials_job", replace_existing=True)
        logger.info("APScheduler: Scheduled 'check_trials_and_reminders_job' daily at 09:01.")

        def schedule_daily_content_posts():
            if not application_instance:
                logger.warning("APScheduler: application_instance not ready for scheduling daily content.")
                return
            
            for job in scheduler.get_jobs():
                if job.id and job.id.startswith("daily_content_post_"):
                    try: scheduler.remove_job(job.id)
                    except Exception: pass
            
            num_posts = random.randint(1, config.MAX_POSTS_PER_DAY)
            logger.info(f"APScheduler: Scheduling {num_posts} content posts for today.")
            for i in range(num_posts):
                hour = random.randint(config.POSTING_SCHEDULE_HOURS_START, config.POSTING_SCHEDULE_HOURS_END -1)
                minute = random.randint(0, 59)
                job_id = f"daily_content_post_{i}_{hour}_{minute}"
                try:
                    scheduler.add_job(post_scheduled_content_job, 'cron', hour=hour, minute=minute, id=job_id, replace_existing=True)
                    logger.info(f"APScheduler: Scheduled content post with ID {job_id} at {hour:02d}:{minute:02d}.")
                except Exception as e_add_job:
                     logger.error(f"APScheduler: Failed to add content job {job_id}: {e_add_job}")
        
        schedule_daily_content_posts()
        scheduler.add_job(schedule_daily_content_posts, 'cron', hour=0, minute=5, id="reschedule_content_job", replace_existing=True)
        logger.info("APScheduler: Scheduled 'schedule_daily_content_posts' daily at 00:05.")
        
        scheduler.start()
        logger.info("APScheduler: Scheduler started.")
    else:
        logger.info("APScheduler: Scheduler already running.")

    logger.info("Starting Telegram bot polling...")
    await application_instance.initialize()
    await application_instance.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    await application_instance.start()
    logger.info("Telegram bot is live and polling.")


bot_thread_event = threading.Event() # ישמש לעצירה חיננית

def run_bot_logic_in_thread_target():
    """Target function for the bot thread, sets up and runs the asyncio event loop."""
    global bot_thread_event
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(setup_bot_and_scheduler())
        # לאחר ש-start_polling התחיל, הוא ימשיך לרוץ עד שיקבל סיגנל עצירה
        # הוסף לולאה כדי לשמור על ה-thread חי ולבדוק את האירוע לעצירה
        while not bot_thread_event.is_set():
            time.sleep(1) # בדוק כל שנייה אם צריך לעצור
    except Exception as e:
        logger.critical(f"Exception in bot_thread: {e}", exc_info=True)
    finally:
        if application_instance and application_instance.updater and application_instance.updater.running:
            loop.run_until_complete(application_instance.updater.stop())
            logger.info("Bot polling stopped in thread.")
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("APScheduler shutdown in thread.")
        loop.close()
        logger.info("Asyncio event loop closed in bot thread.")

# --- קריאה לאתחול הבוט וה-Scheduler ---
if __name__ != '__main__': # ירוץ כאשר Gunicorn מייבא את הקובץ
    logger.info("Module bot.py imported (likely by Gunicorn). Starting bot logic in thread.")
    bot_thread = threading.Thread(target=run_bot_logic_in_thread_target, daemon=True)
    bot_thread.start()
elif __name__ == '__main__':
    logger.info("Running bot locally for development (not via Gunicorn).")
    try:
        asyncio.run(setup_bot_and_scheduler())
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested via KeyboardInterrupt (local run).")
    except Exception as e:
        logger.critical(f"Critical error in local main execution: {e}", exc_info=True)
    finally:
        # עצירה חיננית גם בהרצה מקומית
        if application_instance and application_instance.updater and application_instance.updater.running:
            # הפונקציות stop/shutdown של application_instance הן אסינכרוניות
            async def shutdown_local_bot():
                await application_instance.updater.stop()
                await application_instance.stop()
                await application_instance.shutdown() # לכיבוי חינני יותר של ה-JobQueue וכו'
            
            current_loop = asyncio.get_event_loop()
            if current_loop.is_running():
                 current_loop.create_task(shutdown_local_bot())
            else:
                 asyncio.run(shutdown_local_bot())

            logger.info("Local bot polling stopped.")
        if scheduler.running:
            scheduler.shutdown(wait=False) # wait=False כדי לא לחסום אם הלולאה הראשית כבר נסגרה
            logger.info("Local APScheduler shutdown.")
        logger.info("Local bot execution finished.")
