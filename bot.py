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
    JobQueue # JobQueue מובנה ב-Application
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
logging.getLogger("apscheduler").setLevel(logging.WARNING) # להפחתת לוגים מה-scheduler
logger = logging.getLogger(__name__)

# --- משתנים גלובליים ל-ConversationHandler (מצבים) ---
ASK_EMAIL_AND_CONFIRM, AWAITING_DISCLAIMER_CONFIRMATION = range(2) # שמות המצבים עודכנו

# --- אובייקטים גלובליים (בזהירות) ---
application_instance = None # ישמש גלובלית לגישה מה-Webhook וה-Scheduler
flask_app = Flask(__name__) # אתחול אפליקציית Flask
scheduler = BackgroundScheduler(timezone="Asia/Jerusalem") # אתחול APScheduler

# --- פונקציות עזר לבוט ---
def get_disclaimer_dates():
    today = datetime.date.today()
    trial_end_date = today + datetime.timedelta(days=config.TRIAL_PERIOD_DAYS)
    return today.strftime("%d/%m/%Y"), trial_end_date.strftime("%d/%m/%Y")

async def send_invite_link_or_add_to_channel(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str):
    try:
        expire_date = datetime.datetime.now() + datetime.timedelta(days=config.TRIAL_PERIOD_DAYS + 2)
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=config.CHANNEL_ID,
            name=f"Trial for {username} ({user_id})",
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
        logger.info(f"Sent invite link to user {user_id} ({username})")
        return True
    except Exception as e:
        logger.error(f"Could not create invite link for user {user_id}: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text="אירעה שגיאה ביצירת קישור ההצטרפות לערוץ. אנא פנה למנהל לקבלת סיוע."
        )
        if config.ADMIN_USER_ID:
            await context.bot.send_message(
                chat_id=config.ADMIN_USER_ID,
                text=f"⚠️ שגיאה ביצירת קישור הצטרפות למשתמש {username} ({user_id}) לערוץ {config.CHANNEL_ID}.\nשגיאה: {e}"
            )
        return False

async def send_async_message(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    await context.bot.send_message(chat_id=job_data['chat_id'], text=job_data['text'])

async def send_async_photo_message(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    photo_stream = job_data['photo']
    photo_stream.seek(0) # ודא שהסמן בתחילת ה-stream
    await context.bot.send_photo(
        chat_id=job_data['chat_id'],
        photo=photo_stream,
        caption=job_data['caption']
    )
    photo_stream.close() # סגור את ה-stream לאחר השליחה

# --- תהליך אישור התנאים (ConversationHandler) ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username or user.first_name}) started the bot.")
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
            # אם כבר התחיל ולא סיים, נמשיך לבקשת האימייל והאישור
            await update.message.reply_text(
                "נראה שהתחלת בתהליך ההרשמה אך לא סיימת.\n"
                "אנא שלח את כתובת האימייל שלך (לצורך תשלום עתידי ב-Gumroad) ואת המילה 'מאשר' או 'מקובל'.\n"
                "לדוגמה: `myemail@example.com מאשר`"
            )
            return AWAITING_DISCLAIMER_CONFIRMATION
        # אם יש מצב אחר לא מטופל, נתחיל מחדש (לפשטות)
    
    # משתמש חדש לגמרי
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
    
    # הוסף או עדכן משתמש ב-GSheets
    if not g_sheets.add_new_user_for_disclaimer(user.id, user.username or user.first_name):
         # אם יש בעיה קריטית בהוספה, הודע למנהל
        if config.ADMIN_USER_ID:
            await context.bot.send_message(config.ADMIN_USER_ID, f"שגיאה בהוספת משתמש {user.id} ל-GSheets בשלב ההצהרה.")

    # תזמון בדיקה ל-24 שעות (באמצעות JobQueue של הבוט)
    # נסיר משימות קיימות עם אותו שם אם יש, כדי למנוע כפילות
    current_jobs = context.job_queue.get_jobs_by_name(f"disclaimer_warning_{user.id}")
    for job in current_jobs:
        job.schedule_removal()
    context.job_queue.run_once(
        disclaimer_24h_warning_job_callback, # שם הפונקציה עודכן
        datetime.timedelta(hours=config.REMINDER_MESSAGE_HOURS_BEFORE_WARNING),
        chat_id=user.id,
        name=f"disclaimer_warning_{user.id}"
    )
    logger.info(f"Scheduled 24h disclaimer warning for user {user.id}")
    return AWAITING_DISCLAIMER_CONFIRMATION

async def handle_email_and_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    text = update.message.text.strip() 
    logger.info(f"User {user.id} sent text for disclaimer confirmation: {text}")

    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text)
    confirmation_keywords = ["מאשר", "מקובל", "אישור", "ok", "yes", "כן"]
    # בדוק אם אחת ממילות האישור מופיעה בטקסט (לא בהכרח קשור לאימייל)
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
        
        # נסיר גם את משימת הביטול אם קיימת
        cancel_jobs = context.job_queue.get_jobs_by_name(f"cancel_request_{user.id}")
        for job in cancel_jobs:
            job.schedule_removal()

        await send_invite_link_or_add_to_channel(context, user.id, user.username or user.first_name)
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "לא הצלחתי לזהות כתובת אימייל תקינה ואישור ('מאשר' או 'מקובל').\n"
            "אנא שלח שוב בפורמט: `כתובת@אימייל.קום מאשר`"
        )
        return AWAITING_DISCLAIMER_CONFIRMATION

async def disclaimer_24h_warning_job_callback(context: ContextTypes.DEFAULT_TYPE): # שם הפונקציה עודכן
    job = context.job
    user_id = job.chat_id
    logger.info(f"Running 24h disclaimer warning job for user {user_id}")
    user_gs_data = g_sheets.get_user_data(user_id)

    if user_gs_data and user_gs_data.get(g_sheets.COL_CONFIRMATION_STATUS) == ConfirmationStatus.PENDING_DISCLAIMER.value:
        bot_username = (await context.bot.get_me()).username # קבל את שם המשתמש של הבוט
        warning_message = (
            f"⚠️ אזהרה אחרונה ⚠️\n\n"
            f"לא קיבלנו ממך אישור, והבקשה שלך להצטרפות לערוץ עדיין ממתינה.\n\n"
            f"אם לא נקבל מענה בהקדם – הבקשה תבוטל ותוסר. זהו תזכורת אחרונה.\n\n"
            f"צוות הערוץ ״חדר vip - TradeCore ״ http://t.me/{bot_username}"
        )
        await context.bot.send_message(chat_id=user_id, text=warning_message)
        g_sheets.update_user_disclaimer_status(user_id, ConfirmationStatus.WARNED_NO_DISCLAIMER)
        logger.info(f"Sent final disclaimer warning to user {user_id}")

        # תזמון ביטול סופי אם אין תגובה גם לזה
        current_cancel_jobs = context.job_queue.get_jobs_by_name(f"cancel_request_{user_id}")
        for c_job in current_cancel_jobs:
            c_job.schedule_removal()
        context.job_queue.run_once(
            cancel_request_job_callback, # שם הפונקציה עודכן
            datetime.timedelta(hours=config.HOURS_FOR_FINAL_CONFIRMATION_AFTER_WARNING),
            chat_id=user_id,
            name=f"cancel_request_{user_id}"
        )
    else:
        logger.info(f"User {user_id} already confirmed or not in pending state. Warning job for disclaimer skipped.")

async def cancel_request_job_callback(context: ContextTypes.DEFAULT_TYPE): # שם הפונקציה עודכן
    job = context.job
    user_id = job.chat_id
    logger.info(f"Running final cancellation job for user {user_id} (disclaimer)")
    user_gs_data = g_sheets.get_user_data(user_id)
    if user_gs_data and user_gs_data.get(g_sheets.COL_CONFIRMATION_STATUS) == ConfirmationStatus.WARNED_NO_DISCLAIMER.value:
        g_sheets.update_user_disclaimer_status(user_id, ConfirmationStatus.CANCELLED_NO_DISCLAIMER)
        await context.bot.send_message(chat_id=user_id, text="בקשתך להצטרפות לערוץ בוטלה עקב חוסר מענה לאישור התנאים.")
        logger.info(f"Cancelled request for user {user_id} due to no final disclaimer confirmation.")

async def cancel_conversation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: # שם הפונקציה עודכן
    user = update.effective_user
    logger.info(f"User {user.id} canceled the conversation using /cancel.")
    await update.message.reply_text(
        'תהליך ההרשמה בוטל. תוכל להתחיל מחדש על ידי שליחת /start.',
        reply_markup=ReplyKeyboardRemove()
    )
    # נעדכן סטטוס ב-GSheet אם הוא היה בתהליך
    user_gs_data = g_sheets.get_user_data(user.id)
    if user_gs_data and user_gs_data.get(g_sheets.COL_CONFIRMATION_STATUS) in [ConfirmationStatus.PENDING_DISCLAIMER.value, ConfirmationStatus.WARNED_NO_DISCLAIMER.value]:
        g_sheets.update_user_disclaimer_status(user.id, ConfirmationStatus.CANCELLED_NO_DISCLAIMER)
    return ConversationHandler.END

# --- Webhook של Gumroad (באמצעות Flask) ---
@flask_app.route('/webhook/gumroad', methods=['POST'])
def gumroad_webhook_route(): # שם הפונקציה שונה כדי למנוע התנגשות עם פונקציות טלגרם
    # אימות (אם גאמרוד שולחים secret בכותרת X-Gumroad-Signature או דומה)
    # signature = request.headers.get('X-Gumroad-Signature')
    # if not verify_gumroad_signature(request.data, signature, config.GUMROAD_WEBHOOK_SECRET):
    #     logger.warning("Invalid Gumroad webhook signature.")
    #     abort(403)

    data = request.json
    logger.info(f"Received Gumroad webhook: {data}")

    email = data.get('email')
    # product_id או product_permalink תלוי מה Gumroad שולח ומה הגדרת ב-config
    product_identifier = data.get('product_permalink') or data.get('product_id') 
    sale_id = data.get('sale_id') or data.get('order_id') # או מזהה אחר של המכירה/מנוי
    # is_test_purchase = data.get('test', False)

    if product_identifier != config.GUMROAD_PRODUCT_PERMALINK:
        logger.warning(f"Webhook for wrong Gumroad product: {product_identifier}")
        return "Webhook for wrong product", 200

    if email and sale_id:
        telegram_user_id_str = g_sheets.update_user_payment_status_from_gumroad(email, sale_id)
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
                # אם המשתמש עדיין לא בערוץ (למשל, אם לא השלים את הניסיון ובחר לשלם מאוחר יותר)
                # כאן נוכל לנסות להוסיף אותו שוב אם צריך, או לוודא שהסטטוס שלו מונע הסרה.
                # g_sheets.start_user_trial(telegram_user_id) # זה יקבע תאריכי ניסיון, אולי עדיף פונקציה אחרת
                user_data = g_sheets.get_user_data(telegram_user_id)
                if user_data and user_data.get(g_sheets.COL_PAYMENT_STATUS) == PaymentStatus.PAID_SUBSCRIBER.value:
                    # ודא שהוא יכול להצטרף אם הוא לא בערוץ
                    # send_invite_link_or_add_to_channel(application_instance.context_types.DEFAULT_TYPE(application_instance, chat_id=telegram_user_id), telegram_user_id) # קצת מסורבל
                    logger.info(f"User {telegram_user_id} is now a paid subscriber.")
            else:
                logger.error("Telegram application_instance not available for Gumroad confirmation (webhook).")
        else:
            logger.warning(f"Gumroad sale processed for email {email}, but no matching Telegram user ID found in GSheet or user ID is not set.")
    else:
        logger.error(f"Gumroad webhook missing email or sale_id: {data}")
        return "Missing data", 400
    return "Webhook received successfully", 200

@flask_app.route('/health', methods=['GET'])
def health_check():
    return "OK", 200

# --- משימות מתוזמנות עם APScheduler ---
def check_trials_and_reminders_job(): # שם הפונקציה עודכן
    global application_instance # ודא שמשתמשים בגלובלי הנכון
    logger.info("APScheduler: Running check_trials_and_reminders job.")
    if not application_instance:
        logger.error("APScheduler: Telegram application_instance not available for trial checks.")
        return

    users_to_process = g_sheets.get_users_for_trial_reminder_or_removal()
    for item in users_to_process:
        action = item['action']
        user_gs_data = item['data'] # זה כבר dict מהרשומות
        user_id_str = user_gs_data.get(g_sheets.COL_USER_ID)
        if not user_id_str: continue # דלג אם אין user_id
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
            logger.info(f"APScheduler: Processing removal for user {user_id} (email: {email}) due to no payment after trial.")
            try:
                # נסה להסיר מהערוץ
                bot_instance = application_instance.bot
                # ננסה קודם להוציא, ואז לשלוח הודעה
                await bot_instance.ban_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id)
                await bot_instance.unban_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id) # כדי שיוכל להצטרף שוב אם ישלם
                logger.info(f"APScheduler: Kicked user {user_id} from channel {config.CHANNEL_ID}")

                removal_text = f"הגישה שלך לערוץ {config.CHANNEL_USERNAME or 'TradeCore VIP'} הופסקה מכיוון שלא התקבל תשלום לאחר תקופת הניסיון. נשמח לראותך שוב אם תחליט להצטרף ולחדש את המנוי!"
                application_instance.job_queue.run_once(
                    send_async_message, 0, chat_id=user_id, data={'text': removal_text}, name=f"removal_notice_{user_id}"
                )
                g_sheets.update_user_status(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.EXPIRED_NO_PAYMENT.value})
            except Exception as e:
                logger.error(f"APScheduler: Error during removal process for user {user_id}: {e}")
                # אם ההסרה נכשלה, לפחות נעדכן את הסטטוס ב-GSheet כדי שלא יקבל תוכן
                g_sheets.update_user_status(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.EXPIRED_NO_PAYMENT.value})


def post_scheduled_content_job():
    global application_instance
    logger.info("APScheduler: Attempting to post scheduled content.")
    if not application_instance:
        logger.error("APScheduler: Telegram application_instance not available for posting content.")
        return

    selected_stock = random.choice(config.STOCK_SYMBOLS_LIST)
    logger.info(f"APScheduler: Selected stock {selected_stock} for posting.")

    try:
        image_stream, analysis_text = graph_generator.create_stock_graph_and_text(selected_stock)
        
        if image_stream and analysis_text:
            # image_stream.seek(0) # הפונקציה send_async_photo_message תעשה זאת
            job_data = {
                'chat_id': config.CHANNEL_ID,
                'photo': image_stream,
                'caption': analysis_text
            }
            application_instance.job_queue.run_once(
                send_async_photo_message, 0, data=job_data, name=f"content_post_photo_{selected_stock}"
            )
            logger.info(f"APScheduler: Queued photo content for {selected_stock} to channel {config.CHANNEL_ID}")
        else:
            logger.warning(f"APScheduler: Failed to generate graph or text for {selected_stock}. Details (if any): {analysis_text}")
    except Exception as e:
        logger.error(f"APScheduler: Error posting scheduled content for {selected_stock}: {e}", exc_info=True)


# --- פונקציית main ואתחול ---
def run_flask_app_in_thread(): # שם הפונקציה שונה
    logger.info(f"Starting Flask app for webhooks on {config.WEBHOOK_LISTEN_HOST}:{config.WEBHOOK_PORT}")
    # בסביבת Render, Gunicorn יריץ את זה. מקומית, אפשר להשתמש בשרת הפיתוח של Flask.
    # flask_app.run(host=config.WEBHOOK_LISTEN_HOST, port=config.WEBHOOK_PORT, debug=False)
    # מכיוון ש-Gunicorn יריץ את flask_app, אין צורך להריץ את זה מכאן אם Gunicorn הוא נקודת הכניסה.
    # אם Gunicorn *לא* נקודת הכניסה (למשל אם ה-start command הוא `python bot.py`), אז צריך להפעיל את Flask.
    # כרגע נשאיר את זה כך, בהנחה ש-gunicorn הוא ה-entry point.
    # אם לא, נצטרך לבטל את הקומנט ולהתאים את ה-start command ב-Render.
    pass


async def setup_bot_and_scheduler():
    """מאתחל את הבוט והתזמונים."""
    global application_instance, scheduler

    if not g_sheets.get_sheet():
        logger.critical("CRITICAL: Could not connect to Google Sheets. Bot will not function correctly. Exiting.")
        return

    builder = Application.builder().token(config.TELEGRAM_BOT_TOKEN)
    application_instance = builder.build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_command)],
        states={
            AWAITING_DISCLAIMER_CONFIRMATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_and_confirmation)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation_command)],
        # persistent=True, name="main_conversation" # אפשר להוסיף אם רוצים לשמר מצבים
    )
    application_instance.add_handler(conv_handler)
    # הוסף כאן פקודות אדמין אם תרצה

    # הגדרת משימות APScheduler (הוא כבר מאותחל גלובלית)
    if not scheduler.running:
        # 1. בדיקת תקופות ניסיון ותזכורות
        scheduler.add_job(check_trials_and_reminders_job, 'cron', hour=9, minute=0, id="check_trials_job")
        logger.info("APScheduler: Scheduled 'check_trials_and_reminders_job' daily at 09:00.")

        # 2. תזמון דינמי לשליחת תוכן
        def schedule_daily_content_posts():
            if not application_instance: # בדיקה נוספת
                logger.warning("APScheduler: application_instance not ready for scheduling daily content.")
                return

            # הסר משימות קיימות של תוכן מהיום הקודם
            for job in scheduler.get_jobs():
                if job.id and job.id.startswith("daily_content_post_"):
                    try:
                        scheduler.remove_job(job.id)
                    except Exception as e_rem:
                        logger.warning(f"Could not remove old content job {job.id}: {e_rem}")
            
            num_posts = random.randint(1, config.MAX_POSTS_PER_DAY)
            logger.info(f"APScheduler: Scheduling {num_posts} content posts for today.")
            for i in range(num_posts):
                hour = random.randint(config.POSTING_SCHEDULE_HOURS_START, config.POSTING_SCHEDULE_HOURS_END -1)
                minute = random.randint(0, 59)
                job_id = f"daily_content_post_{i}_{hour}_{minute}" # שם ייחודי יותר
                try:
                    scheduler.add_job(
                        post_scheduled_content_job, 
                        'cron', 
                        hour=hour, 
                        minute=minute,
                        id=job_id 
                    )
                    logger.info(f"APScheduler: Scheduled content post with ID {job_id} at {hour:02d}:{minute:02d}.")
                except Exception as e_add_job:
                     logger.error(f"APScheduler: Failed to add content job {job_id}: {e_add_job}")


        schedule_daily_content_posts() # תזמן להיום
        scheduler.add_job(schedule_daily_content_posts, 'cron', hour=0, minute=5, id="reschedule_content_job")
        logger.info("APScheduler: Scheduled 'schedule_daily_content_posts' daily at 00:05.")
        
        scheduler.start()
        logger.info("APScheduler: Scheduler started.")
    else:
        logger.info("APScheduler: Scheduler already running.")

    # הרצת הבוט (Polling)
    logger.info("Starting Telegram bot polling...")
    await application_instance.initialize() # חשוב לאתחל לפני הרצת polling או webhook
    await application_instance.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    await application_instance.start()
    
    # השאר את הבוט רץ
    # await asyncio.Event().wait() # ישאיר את הלולאה האסינכרונית רצה


# נקודת הכניסה הראשית שתקרא על ידי Gunicorn היא flask_app
# אבל אנחנו צריכים גם להריץ את הבוט וה-scheduler.
# Gunicorn יריץ את flask_app. אנחנו נריץ את הבוט וה-scheduler ב-thread נפרד
# שמתחיל כאשר המודול הזה מיובא על ידי Gunicorn.
# זה קצת טריקי, אבל אפשרי.
# דרך טובה יותר היא להפריד את ה-web service (Flask) מה-bot worker (Telegram + Scheduler)
# לשני שירותים נפרדים ב-Render אם התוכנית מאפשרת.
# כרגע, ננסה להריץ הכל יחד.

bot_thread = None

def start_bot_logic_in_thread():
    """מריץ את הלוגיקה של הבוט וה-scheduler ב-thread נפרד."""
    global bot_thread
    if bot_thread is None or not bot_thread.is_alive():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def run_bot_async():
            await setup_bot_and_scheduler()
            # הלולאה של הבוט (start_polling) כבר רצה, אין צורך ב-asyncio.Event().wait() כאן בתוך ה-thread
            # ה-thread יישאר בחיים כל עוד הלולאה של הבוט רצה.
            # כדי לאפשר כיבוי חינני, נצטרך לטפל ב-SIGTERM.
            while True: # שמור על ה-thread חי
                await asyncio.sleep(3600) # בדוק כל שעה (סתם כדי שה-thread לא יסתיים)
                if not (application_instance and application_instance.updater and application_instance.updater.running):
                    logger.warning("Bot polling seems to have stopped. Exiting thread.")
                    break


        bot_thread = threading.Thread(target=lambda: loop.run_until_complete(run_bot_async()), daemon=True)
        bot_thread.start()
        logger.info("Telegram bot and scheduler logic thread started.")

# --- קריאה לאתחול הבוט וה-Scheduler ---
# זה יקרה כאשר Gunicorn ייבא את המודול 'bot' כדי למצוא את 'flask_app'
# וזה בדיוק מה שגרם ל-NameError הקודם אם הקריאה ל-graph_generator הייתה כאן.
# כעת, הפונקציות של ה-scheduler והתוכן נקראות רק *אחרי* שהכל מאותחל.
if __name__ != '__main__': # ירוץ כאשר Gunicorn מייבא את הקובץ
    logger.info("Module bot.py imported by Gunicorn. Starting bot logic in thread.")
    start_bot_logic_in_thread()
elif __name__ == '__main__':
    # הרצה מקומית לפיתוח (לא דרך Gunicorn)
    logger.info("Running bot locally for development (not via Gunicorn).")
    
    # אם רוצים להריץ גם את Flask מקומית באותו זמן
    # flask_dev_thread = threading.Thread(target=lambda: flask_app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False), daemon=True)
    # flask_dev_thread.start()
    # logger.info("Flask development server started in a separate thread on port 5000.")

    asyncio.run(setup_bot_and_scheduler()) # הרץ את הבוט וה-scheduler
    # הלולאה תישאר רצה בגלל ה-start_polling
