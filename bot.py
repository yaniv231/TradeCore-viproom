# bot.py
import logging
import datetime
import random
import threading # להרצת Flask והבוט באותו תהליך (לפשטות ב-Render)
import time
import re # לזיהוי אימייל

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler, # אם נשתמש בכפתורים Inline
    JobQueue
)
from flask import Flask, request, abort # לשרת ה-Webhook
from apscheduler.schedulers.background import BackgroundScheduler # לתזמון משימות

# ייבוא המודולים שלנו
import config
import g_sheets
from g_sheets import ConfirmationStatus, PaymentStatus # לייבוא קל יותר של הסטטוסים
# graph_generator ייווצר בהמשך
# import graph_generator

# --- הגדרות לוגינג ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING) # להפחתת לוגים מספריית HTTPx
logger = logging.getLogger(__name__)

# --- משתנים גלובליים ל-ConversationHandler (מצבים) ---
ASK_EMAIL, WAITING_FOR_DISCLAIMER_CONFIRMATION = range(2)

# --- פונקציות עזר לבוט ---
def get_disclaimer_dates():
    """מחזיר את תאריך היום ותאריך סיום הניסיון לפורמט תצוגה."""
    today = datetime.date.today()
    trial_end_date = today + datetime.timedelta(days=config.TRIAL_PERIOD_DAYS)
    return today.strftime("%d/%m/%Y"), trial_end_date.strftime("%d/%m/%Y")

async def send_invite_link_or_add_to_channel(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """
    מנסה ליצור קישור הצטרפות אישי לערוץ או להוסיף את המשתמש ישירות.
    הבוט חייב להיות אדמין בערוץ עם ההרשאות המתאימות.
    """
    try:
        # נסה ליצור קישור הצטרפות יחיד שתקף לזמן קצר
        expire_date = datetime.datetime.now() + datetime.timedelta(days=config.TRIAL_PERIOD_DAYS + 2) # קצת יותר מתקופת הניסיון
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=config.CHANNEL_ID,
            name=f"Trial for {user_id}",
            expire_date=expire_date,
            member_limit=1
        )
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ אישרת את התנאים!\n"
                 f"הנך מועבר לתקופת ניסיון של {config.TRIAL_PERIOD_DAYS} ימים.\n"
                 f"לחץ כאן כדי להצטרף לערוץ: {invite_link.invite_link}"
        )
        logger.info(f"Sent invite link to user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Could not create invite link or add user {user_id} to channel {config.CHANNEL_ID}: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text="אירעה שגיאה ביצירת קישור ההצטרפות לערוץ. אנא פנה למנהל לקבלת סיוע."
        )
        # אפשר לשלוח הודעה לאדמין על הבעיה
        await context.bot.send_message(
            chat_id=config.ADMIN_USER_ID,
            text=f"⚠️ שגיאה ביצירת קישור הצטרפות למשתמש {user_id} לערוץ {config.CHANNEL_ID}.\nשגיאה: {e}"
        )
        return False

# --- תהליך אישור התנאים (ConversationHandler) ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    מתחיל את הבוט או את תהליך אישור התנאים למשתמש חדש.
    """
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) started the bot.")

    user_data_gs = g_sheets.get_user_data(user.id)

    if user_data_gs:
        confirmation_status = user_data_gs.get(g_sheets.COL_CONFIRMATION_STATUS)
        payment_status = user_data_gs.get(g_sheets.COL_PAYMENT_STATUS)

        if confirmation_status == ConfirmationStatus.CONFIRMED_DISCLAIMER.value and \
           (payment_status == PaymentStatus.TRIAL.value or payment_status == PaymentStatus.PAID_SUBSCRIBER.value):
            await update.message.reply_text("אתה כבר רשום ופעיל בערוץ! 😊")
            return ConversationHandler.END
        elif confirmation_status == ConfirmationStatus.PENDING_DISCLAIMER.value or \
             confirmation_status == ConfirmationStatus.WARNED_NO_DISCLAIMER.value:
            # אם המשתמש כבר התחיל את התהליך אך לא סיים, שלח שוב את הודעת התנאים
            # או את הודעת האזהרה בהתאם לסטטוס
            # (לפשטות כרגע נשלח שוב את ההתחלה, אבל אפשר לוגיקה מורכבת יותר)
            pass # נמשיך לשליחת הודעת התנאים

    # משתמש חדש או שלא סיים אישור
    today_str, trial_end_str = get_disclaimer_dates()
    disclaimer_message = (
        f"היי, זה מצוות הערוץ ״חדר vip -TradeCore״\n\n"
        f"המנוי שלך (לתקופת הניסיון) מתחיל היום {today_str} ויסתיים ב-{trial_end_str}.\n\n"
        f"חשוב להבהיר: 🚫התוכן כאן אינו מהווה ייעוץ או המלצה פיננסית מכל סוג! "
        f"📌 ההחלטות בסופו של דבר בידיים שלכם – איך לפעול, מתי להיכנס ומתי לצאת מהשוק.\n\n"
        f"אנא אשר שקראת והבנת את כל הפרטים על ידי שליחת כתובת האימייל שלך (זו שתשמש לתשלום ב-Gumroad אם תבחר להמשיך) והקלדת 'מאשר' או 'מקובל' אחריה.\n"
        f"לדוגמה: `myemail@example.com מאשר`"
    )
    await update.message.reply_text(disclaimer_message)

    # שמירת המשתמש ב-GSheets עם סטטוס ממתין
    g_sheets.add_new_user_for_disclaimer(user.id, user.username or user.first_name)

    # תזמון בדיקה ל-24 שעות (באמצעות JobQueue של הבוט)
    context.job_queue.run_once(
        disclaimer_24h_warning_job,
        datetime.timedelta(hours=config.REMINDER_MESSAGE_HOURS_BEFORE_WARNING),
        chat_id=user.id,
        name=f"disclaimer_warning_{user.id}"
    )
    logger.info(f"Scheduled 24h disclaimer warning for user {user.id}")
    return WAITING_FOR_DISCLAIMER_CONFIRMATION


async def handle_disclaimer_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מטפל בתגובת המשתמש להודעת התנאים."""
    user = update.effective_user
    text = update.message.text.lower().strip() # המר לאותיות קטנות והסר רווחים

    # נסה לחלץ אימייל ותשובת אישור
    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text)
    confirmation_keyword_found = any(keyword in text for keyword in ["מאשר", "מקובל", "אישור", "ok", "yes"])

    if email_match and confirmation_keyword_found:
        email = email_match.group(0)
        logger.info(f"User {user.id} provided email {email} and confirmed disclaimer.")

        # עדכן סטטוס ב-GSןheets
        g_sheets.update_user_email_and_confirmation(user.id, email, ConfirmationStatus.CONFIRMED_DISCLAIMER)

        # התחל תקופת ניסיון
        g_sheets.start_user_trial(user.id)

        # בטל את משימת האזהרה אם קיימת
        current_jobs = context.job_queue.get_jobs_by_name(f"disclaimer_warning_{user.id}")
        if current_jobs:
            for job in current_jobs:
                job.schedule_removal()
            logger.info(f"Removed disclaimer warning job for user {user.id}")

        # הוסף לערוץ / שלח קישור
        await send_invite_link_or_add_to_channel(context, user.id)

        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "לא הצלחתי לזהות כתובת אימייל ואישור ('מאשר' או 'מקובל').\n"
            "אנא שלח שוב בפורמט: `כתובת@אימייל.קום מאשר`"
        )
        return WAITING_FOR_DISCLAIMER_CONFIRMATION


async def disclaimer_24h_warning_job(context: ContextTypes.DEFAULT_TYPE):
    """שולח הודעת אזהרה אם המשתמש לא אישר את התנאים תוך 24 שעות."""
    job = context.job
    user_id = job.chat_id # ב-JobQueue, chat_id הוא ה-user_id
    logger.info(f"Running 24h disclaimer warning job for user {user_id}")

    user_data_gs = g_sheets.get_user_data(user_id)
    if user_data_gs and user_data_gs.get(g_sheets.COL_CONFIRMATION_STATUS) == ConfirmationStatus.PENDING_DISCLAIMER.value:
        warning_message = (
            f"⚠️ אזהרה אחרונה ⚠️\n\n"
            f"לא קיבלנו ממך אישור, והבקשה שלך להצטרפות לערוץ עדיין ממתינה.\n\n"
            f"אם לא נקבל מענה בהקדם – הבקשה תבוטל ותוסר. זהו תזכורת אחרונה.\n\n"
            f"צוות הערוץ ״חדר vip - TradeCore ״ {context.bot.username}" # משתמש בשם הבוט
        )
        await context.bot.send_message(chat_id=user_id, text=warning_message)
        g_sheets.update_user_disclaimer_status(user_id, ConfirmationStatus.WARNED_NO_DISCLAIMER)
        logger.info(f"Sent final disclaimer warning to user {user_id}")

        # אפשר לתזמן ביטול סופי אם אין תגובה גם לזה
        context.job_queue.run_once(
            cancel_request_job,
            datetime.timedelta(hours=config.HOURS_FOR_FINAL_CONFIRMATION_AFTER_WARNING),
            chat_id=user_id,
            name=f"cancel_request_{user_id}"
        )
    else:
        logger.info(f"User {user_id} already confirmed or not in pending state. Warning job skipped.")


async def cancel_request_job(context: ContextTypes.DEFAULT_TYPE):
    """מבטל בקשת הצטרפות אם לא התקבל אישור סופי."""
    job = context.job
    user_id = job.chat_id
    logger.info(f"Running final cancellation job for user {user_id}")
    user_data_gs = g_sheets.get_user_data(user_id)
    if user_data_gs and user_data_gs.get(g_sheets.COL_CONFIRMATION_STATUS) == ConfirmationStatus.WARNED_NO_DISCLAIMER.value:
        g_sheets.update_user_disclaimer_status(user_id, ConfirmationStatus.CANCELLED_NO_DISCLAIMER)
        await context.bot.send_message(chat_id=user_id, text="בקשתך להצטרפות לערוץ בוטלה עקב חוסר מענה.")
        logger.info(f"Cancelled request for user {user_id} due to no final confirmation.")


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """מאפשר למשתמש לבטל את התהליך (אם רוצים)."""
    user = update.effective_user
    logger.info(f"User {user.id} canceled the conversation.")
    await update.message.reply_text(
        'תהליך ההרשמה בוטל. תוכל להתחיל מחדש על ידי שליחת /start.',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


# --- Webhook של Gumroad (באמצעות Flask) ---
flask_app = Flask(__name__)

@flask_app.route('/webhook/gumroad', methods=['POST'])
def gumroad_webhook():
    """מאזין ל-Webhook מ-Gumroad."""
    # כאן תוסיף אימות של ה-Webhook אם Gumroad מספקים "secret"
    # gumroad_secret = request.headers.get('X-Gumroad-Secret')
    # if gumroad_secret != config.GUMROAD_WEBHOOK_SECRET:
    #     abort(403) # Forbidden

    data = request.json
    logger.info(f"Received Gumroad webhook: {data}")

    # פרטי המכירה הרלוונטיים
    email = data.get('email')
    product_permalink = data.get('product_permalink') # או product_id
    sale_id = data.get('sale_id') # או מזהה אחר של המכירה/מנוי
    # is_test_purchase = data.get('test', False) # אם זו רכישת מבחן

    # בדוק אם זה המוצר הנכון
    if product_permalink != config.GUMROAD_PRODUCT_PERMALINK:
        logger.warning(f"Webhook received for wrong product: {product_permalink}")
        return "Webhook for wrong product", 200 # החזר 200 כדי שגאמרוד לא ינסו שוב

    if email and sale_id:
        # עדכן את המשתמש ב-Google Sheets
        telegram_user_id = g_sheets.update_user_payment_status_from_gumroad(email, sale_id)

        if telegram_user_id:
            # שלח הודעת אישור למשתמש בטלגרם
            # חשוב: כדי לשלוח הודעות מחוץ להקשר של פקודה (כמו כאן מה-webhook),
            # צריך להשתמש באובייקט ה-Application של הבוט.
            # זה ידרוש ארכיטקטורה קצת שונה אם ה-Flask והבוט רצים בתהליכים נפרדים לחלוטין.
            # אם הם רצים באותו תהליך עם threading, ניתן לגשת לאובייקט ה-bot.
            # נניח ש-application_instance זמין גלובלית או מועבר.
            try:
                if application_instance: # application_instance הוא האובייקט שנוצר מ-Application.builder()
                    message_text = (
                        f"💰 תודה על רכישת המנוי דרך Gumroad!\n"
                        f"הגישה שלך לערוץ {config.CHANNEL_USERNAME} חודשה/אושרה.\n"
                        f"פרטי עסקה: {sale_id}"
                    )
                    # שימוש ב-asyncio.run_coroutine_threadsafe אם ה-webhook רץ ב-thread נפרד
                    # או אם ה-bot רץ עם asyncio.run() בלולאה נפרדת.
                    # לפשטות כאן, נניח שניתן לקרוא ישירות, אך זה עלול לדרוש התאמה.
                    # application_instance.bot.send_message(chat_id=int(telegram_user_id), text=message_text)
                    # עדיף להשתמש ב- job_queue.run_once כדי שההודעה תישלח מה-event loop של הבוט
                    application_instance.job_queue.run_once(
                        send_async_message,
                        0, # שלח מיד
                        chat_id=int(telegram_user_id),
                        data={'text': message_text},
                        name=f"gumroad_confirm_{telegram_user_id}"
                    )

                    logger.info(f"Sent payment confirmation to Telegram user {telegram_user_id} for Gumroad sale {sale_id}")
                    # כאן גם תוכל להוסיף את המשתמש לערוץ אם הוא עוד לא שם והיה בתקופת ניסיון שהסתיימה
                    # או לוודא שהוא לא יוסר.
                else:
                    logger.error("Telegram application_instance not available to send Gumroad confirmation.")
            except Exception as e:
                logger.error(f"Error sending Gumroad payment confirmation to user {telegram_user_id}: {e}")
        else:
            logger.warning(f"Gumroad sale processed for email {email}, but no matching Telegram user ID found in GSheet.")
    else:
        logger.error(f"Gumroad webhook missing email or sale_id: {data}")
        return "Missing data", 400

    return "Webhook received successfully", 200

async def send_async_message(context: ContextTypes.DEFAULT_TYPE):
    """פונקציית עזר לשליחת הודעה אסינכרונית מה-JobQueue."""
    job_data = context.job.data
    await context.bot.send_message(chat_id=job_data['chat_id'], text=job_data['text'])


# --- משימות מתוזמנות (APScheduler או JobQueue) ---
scheduler = BackgroundScheduler(timezone="Asia/Jerusalem") # חשוב להגדיר Timezone

def check_trials_and_reminders():
    """בודק תקופות ניסיון, שולח תזכורות או מסיר משתמשים."""
    logger.info("APScheduler: Running check_trials_and_reminders job.")
    users_to_process = g_sheets.get_users_for_trial_reminder_or_removal()

    for item in users_to_process:
        action = item['action']
        user_data = item['data']
        user_id = int(user_data.get(g_sheets.COL_USER_ID))
        email = user_data.get(g_sheets.COL_EMAIL)

        if action == 'send_trial_end_reminder':
            logger.info(f"APScheduler: Sending trial end reminder to user {user_id} (email: {email})")
            # שלח הודעת תזכורת עם קישור לתשלום
            reminder_text = (
                f"היי, כאן צוות TRADECORE– שוק ההון 👋\n\n"
                f"שבוע הניסיון שלך בערוץ ״חדר vip -TradeCore״ עומד להסתיים.\n"
                f"איך היה? הרגשת שיפור בתיק שלך? קיבלת ידע וניתוחים שלא יצא לך לדעת? הרגשת יחס אישי?\n\n"
                f"אם אתה רוצה להמשיך – העלות {config.PAYMENT_AMOUNT_ILS}₪ לחודש.\n"
                f"🔗 קישור לתשלום דרך Gumroad (תומך PayPal ועוד): {config.GUMROAD_PRODUCT_PERMALINK}\n"
                f"(או ישירות דרך PayPal: {config.PAYPAL_ME_LINK} - אם תבחר בזה, אנא שלח צילום מסך של התשלום למנהל לאישור ידני)\n\n"
                f"מי שלא מחדש – מוסר אוטומטית מהערוץ.\n"
                f"עסקה אחת ואתה משלש את ההשקעה!! 😉"
            )
            # השתמש ב-JobQueue של הבוט כדי לשלוח את ההודעה האסינכרונית
            if application_instance:
                application_instance.job_queue.run_once(
                    send_async_message, 0, chat_id=user_id, data={'text': reminder_text}, name=f"trial_reminder_{user_id}"
                )
                g_sheets.update_user_status(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.PENDING_PAYMENT_AFTER_TRIAL.value})
            else:
                logger.error("APScheduler: Telegram application_instance not available for trial reminder.")

        elif action == 'remove_user_no_payment':
            logger.info(f"APScheduler: Removing user {user_id} (email: {email}) due to no payment after trial.")
            if application_instance:
                try:
                    # נסה להסיר מהערוץ
                    # application_instance.bot.kick_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id)
                    # application_instance.bot.unban_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id) # כדי שיוכל להצטרף שוב אם ישלם
                    # logger.info(f"APScheduler: Kicked user {user_id} from channel {config.CHANNEL_ID}")

                    # לשליטה טובה יותר, נבטל את קישור ההזמנה שלו (אם היה כזה) ונסמוך על זה שהוא לא יוכל להצטרף שוב
                    # ההסרה בפועל יכולה להיות מאתגרת אם הוא הצטרף דרך קישור כללי או אם אין לבוט הרשאות מלאות תמיד.
                    # התמקדות בסטטוס ב-GSHEETS היא קריטית.

                    removal_text = f"הגישה שלך לערוץ {config.CHANNEL_USERNAME} הסתיימה מכיוון שלא התקבל תשלום לאחר תקופת הניסיון. נשמח לראותך שוב אם תחליט להצטרף!"
                    application_instance.job_queue.run_once(
                        send_async_message, 0, chat_id=user_id, data={'text': removal_text}, name=f"removal_notice_{user_id}"
                    )
                    g_sheets.update_user_status(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.EXPIRED_NO_PAYMENT.value})
                except Exception as e:
                    logger.error(f"APScheduler: Error removing user {user_id} or sending notice: {e}")
            else:
                logger.error("APScheduler: Telegram application_instance not available for user removal.")


def post_scheduled_content_job():
    """בוחר מניה, יוצר גרף ושולח לערוץ."""
    # המשימה הזו מופעלת על ידי תזמון דינמי יותר (ראה בהמשך)
    logger.info("APScheduler: Attempting to post scheduled content.")

    if not application_instance:
        logger.error("APScheduler: Telegram application_instance not available for posting content.")
        return

    selected_stock = random.choice(config.STOCK_SYMBOLS_LIST)
    logger.info(f"APScheduler: Selected stock {selected_stock} for posting.")

    try:
        # כאן תקרא לפונקציה מיצירת הגרפים
        # image_path, analysis_text = graph_generator.create_stock_graph_and_analysis(selected_stock)
        # בשלב זה נשים Placeholder:
        image_path = None # החלף בנתיב לתמונה או אובייקט BytesIO
        analysis_text = f"📊 ניתוח טכני למניית {selected_stock} 📈\n\n[כאן יופיע ניתוח טקסטואלי קצר. זכור, זו אינה המלצה!]"
        
        # אם אין גרף, שלח רק טקסט (או דלג על הפוסט)
        if not image_path: # במציאות, תרצה לשלוח תמונה
            logger.warning(f"APScheduler: No graph generated for {selected_stock}. Sending text only or skipping.")
            # application_instance.bot.send_message(chat_id=config.CHANNEL_ID, text=analysis_text)
            # לדוגמה, נשלח בינתיים רק טקסט
            # application_instance.job_queue.run_once(
            #     send_async_message, 0, chat_id=config.CHANNEL_ID, data={'text': analysis_text}, name=f"content_post_text_{selected_stock}"
            # )
            return # כרגע נדלג אם אין גרף אמיתי

        # שלח תמונה עם כיתוב לערוץ
        # with open(image_path, 'rb') as photo_file:
        #     application_instance.bot.send_photo(
        #         chat_id=config.CHANNEL_ID,
        #         photo=photo_file,
        #         caption=analysis_text
        #     )
        # logger.info(f"APScheduler: Posted content for {selected_stock} to channel {config.CHANNEL_ID}")
        # if image_path == config.TEMP_GRAPH_PATH: # נקה קובץ זמני
        #     import os
        #     os.remove(image_path)

    except Exception as e:
        logger.error(f"APScheduler: Error posting scheduled content for {selected_stock}: {e}")

# --- אתחול הבוט והשרת ---
application_instance = None # ישמש גלובלית (בזהירות) לגישה מה-Webhook וה-Scheduler

def run_flask_app():
    """מריץ את אפליקציית Flask ב-thread נפרד."""
    # חשוב: בסביבת פרודקשן אמיתית כמו Render, משתמשים בשרת WSGI כמו gunicorn
    # ולא בשרת הפיתוח של Flask. הקונפיגורציה ב-render.yaml תטפל בזה.
    # לצורך הרצה מקומית או פשטות, זה יכול לעבוד.
    logger.info("Starting Flask app for Gumroad webhooks.")
    flask_app.run(host=config.WEBHOOK_LISTEN_HOST, port=config.WEBHOOK_PORT, debug=False)


async def main() -> None:
    """הפונקציה הראשית שמאתחלת ומריצה את הכל."""
    global application_instance

    # אתחול החיבור ל-Google Sheets (רק כדי לוודא שהוא תקין בהתחלה)
    if not g_sheets.get_sheet():
        logger.error("CRITICAL: Could not connect to Google Sheets. Bot will not function correctly.")
        # בסביבת פרודקשן, אולי נרצה שהאפליקציה תיכשל כאן אם זה קריטי
        # return

    # יצירת אובייקט ה-Application
    builder = Application.builder().token(config.TELEGRAM_BOT_TOKEN)
    # אם רוצים להגביל את סוגי העדכונים שהבוט מקבל
    # builder.allowed_updates(Update.ALL_TYPES)
    application_instance = builder.build()

    # הגדרת ה-ConversationHandler לאישור תנאים
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_command)],
        states={
            WAITING_FOR_DISCLAIMER_CONFIRMATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_disclaimer_confirmation)
            ],
            # ניתן להוסיף מצבים נוספים אם צריך
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)], # פקודה לביטול השיחה
        # persistent=True, name="disclaimer_conversation" # אם רוצים לשמור מצב בין ריסטים (דורש הגדרה נוספת)
    )
    application_instance.add_handler(conv_handler)

    # פקודות נוספות (למשל, פקודות אדמין)
    # application_instance.add_handler(CommandHandler('admin_approve', admin_approve_command, filters=filters.User(user_id=config.ADMIN_USER_ID)))


    # --- הגדרת תזמונים עם APScheduler ---
    # 1. בדיקת תקופות ניסיון ותזכורות
    scheduler.add_job(check_trials_and_reminders, 'cron', hour=9, minute=0, timezone="Asia/Jerusalem") # כל יום ב-09:00
    logger.info("APScheduler: Scheduled job 'check_trials_and_reminders' daily at 09:00 Asia/Jerusalem.")

    # 2. תזמון דינמי לשליחת תוכן (עד X פוסטים ביום בשעות אקראיות)
    # ניצור X משימות רנדומליות כל יום
    def schedule_daily_content_posts():
        # הסר משימות קיימות של תוכן מהיום הקודם
        for job in scheduler.get_jobs():
            if job.name and job.name.startswith("daily_content_post_"):
                scheduler.remove_job(job.id)
        
        num_posts = random.randint(1, config.MAX_POSTS_PER_DAY)
        logger.info(f"APScheduler: Scheduling {num_posts} content posts for today.")
        for i in range(num_posts):
            hour = random.randint(config.POSTING_SCHEDULE_HOURS_START, config.POSTING_SCHEDULE_HOURS_END -1) # -1 כדי שהדקה לא תחרוג
            minute = random.randint(0, 59)
            scheduler.add_job(
                post_scheduled_content_job, 
                'cron', 
                hour=hour, 
                minute=minute, 
                timezone="Asia/Jerusalem",
                name=f"daily_content_post_{i}" # שם ייחודי למשימה
            )
            logger.info(f"APScheduler: Scheduled content post at {hour:02d}:{minute:02d} Asia/Jerusalem.")

    # הפעל את תזמון התוכן בפעם הראשונה, ואז כל יום בחצות
    schedule_daily_content_posts() # תזמן להיום
    scheduler.add_job(schedule_daily_content_posts, 'cron', hour=0, minute=5, timezone="Asia/Jerusalem") # תזמן מחדש כל יום קצת אחרי חצות
    logger.info("APScheduler: Scheduled job 'schedule_daily_content_posts' daily at 00:05 Asia/Jerusalem.")

    scheduler.start()
    logger.info("APScheduler: Scheduler started.")


    # הרצת שרת Flask ב-thread נפרד
    # הערה: עבור Render, אולי עדיף להריץ את Flask כ-Web Service ואת הבוט כ-Background Worker.
    # אם מריצים יחד, חשוב לוודא ש-Flask לא חוסם את לולאת האירועים של הבוט.
    # שימוש ב-threading הוא דרך אחת פשוטה להשיג זאת.
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()
    logger.info("Flask app thread started.")

    # הרצת הבוט (Polling)
    logger.info("Starting Telegram bot polling...")
    application_instance.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    # ודא שקובץ ההגדרות נכון ושהטוקן קיים
    if config.TELEGRAM_BOT_TOKEN == 'הכנס_כאן_את_הטוקן_של_הבוט_שלך':
        logger.error("נא הגדר את TELEGRAM_BOT_TOKEN בקובץ config.py או כמשתנה סביבה!")
    else:
        # מאחר והפונקציה main היא async, צריך להריץ אותה עם asyncio.run() בפייתון 3.7+
        # אך ספריית python-telegram-bot מנהלת את הלולאה האסינכרונית בעצמה עם application.run_polling()
        # לכן פשוט נקרא ל-main.
        # asyncio.run(main()) # לא נדרש כאן אם run_polling הוא הקריאה האחרונה

        # במקום זאת, נאתחל את main באופן סינכרוני והיא תריץ את ה-polling בסופה
        import asyncio
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.info("Bot shutdown requested via KeyboardInterrupt.")
        except Exception as e:
            logger.critical(f"Critical error in main execution: {e}", exc_info=True)
        finally:
            if scheduler.running:
                scheduler.shutdown()
            logger.info("Bot and scheduler shut down.")

async def send_async_photo_message(context: ContextTypes.DEFAULT_TYPE):
    """פונקציית עזר לשליחת הודעת תמונה אסינכרונית מה-JobQueue."""
    job_data = context.job.data
    await context.bot.send_photo(
        chat_id=job_data['chat_id'],
        photo=job_data['photo'],
        caption=job_data['caption']
    )

# ... ב-bot.py, בתוך הגדרות ה-Flask app ...
@flask_app.route('/health', methods=['GET'])
def health_check():
    return "OK", 200

image_stream, analysis_text = graph_generator.create_stock_graph_and_text(selected_stock)

if image_stream and analysis_text:
    image_stream.seek(0) # ודא שהסמן בתחילת ה-stream
    # שלח דרך ה-JobQueue של הבוט
    if application_instance:
        job_data = {
            'chat_id': config.CHANNEL_ID,
            'photo': image_stream, # שלח את אובייקט ה-BytesIO ישירות
            'caption': analysis_text
        }
        application_instance.job_queue.run_once(
            send_async_photo_message, # פונקציית עזר חדשה לשליחת תמונה
            0,
            data=job_data,
            name=f"content_post_photo_{selected_stock}"
        )
        logger.info(f"APScheduler: Queued photo content for {selected_stock} to channel {config.CHANNEL_ID}")
else:
    logger.warning(f"APScheduler: Failed to generate graph or text for {selected_stock}. Details: {analysis_text}")