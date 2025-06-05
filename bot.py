import os
import logging
from datetime import datetime, timedelta
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackContext
)
from apscheduler.schedulers.background import BackgroundScheduler
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf
import mplfinance as mpf
import matplotlib.pyplot as plt # נראה שלא בשימוש בקוד שסופק, אך מיובא
import requests # נראה שלא בשימוש בקוד שסופק, אך מיובא
from pytz import timezone
from typing import cast # נראה שלא בשימוש בקוד שסופק, אך מיובא
import asyncio

# --- הגדרות בסיסיות ---
# !!! חשוב: שנה את הערכים הבאים לערכים האמיתיים שלך !!!
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"  # החלף בטוקן האמיתי של הבוט שלך
CHANNEL_ID = "YOUR_CHANNEL_ID"  # החלף ב-ID האמיתי של הערוץ (אם רלוונטי ל-async_task)

# הגדרת לוגינג (מומלץ)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# הגדרת אפליקציית Flask עם השם הנדרש
flask_app = Flask(__name__)

# ... (הגדרת משתנים ופונקציות עוזר נוספות יכולות לבוא כאן) ...
# אם יש פונקציות שהוגדרו כאן, ודא שגם להן יש גוף מוזח כראוי.

# --- פונקציות הבוט של טלגרם ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    effective_username = user.username or user.first_name or f"User_{user.id}"
    logger.info(f"--- FULL BOT: /start received by user {user.id} ({effective_username}) ---") # <--- לוג ראשון

    try:
        logger.info(f"--- FULL BOT: Step 1 - Checking existing user data for {user.id} ---")
        user_gs_data = g_sheets.get_user_data(user.id) # קריאה ראשונה ל-Google Sheets
        if user_gs_data is not None:
            logger.info(f"--- FULL BOT: User {user.id} data found in GSheets. Confirmation: {user_gs_data.get(g_sheets.COL_CONFIRMATION_STATUS)}, Payment: {user_gs_data.get(g_sheets.COL_PAYMENT_STATUS)} ---")
        else:
            logger.info(f"--- FULL BOT: User {user.id} not found in GSheets or error fetching. ---")


        # --- כאן מתחילה הלוגיקה המקורית שלך, עם תוספות לוג ---
        if user_gs_data:
            confirmation_status_str = user_gs_data.get(g_sheets.COL_CONFIRMATION_STATUS)
            payment_status_str = user_gs_data.get(g_sheets.COL_PAYMENT_STATUS)
            is_confirmed = confirmation_status_str == ConfirmationStatus.CONFIRMED_DISCLAIMER.value
            is_trial_or_paid = payment_status_str in [PaymentStatus.TRIAL.value, PaymentStatus.PAID_SUBSCRIBER.value]

            if is_confirmed and is_trial_or_paid:
                logger.info(f"--- FULL BOT: User {user.id} is already registered and active. Sending reply. ---")
                await update.message.reply_text("אתה כבר רשום ופעיל בערוץ! 😊")
                logger.info(f"--- FULL BOT: 'Already registered' reply sent to {user.id}. Ending conversation. ---")
                return ConversationHandler.END

            elif confirmation_status_str in [ConfirmationStatus.PENDING_DISCLAIMER.value, ConfirmationStatus.WARNED_NO_DISCLAIMER.value]:
                logger.info(f"--- FULL BOT: User {user.id} started but did not finish disclaimer. Prompting again. ---")
                await update.message.reply_text(
                    "נראה שהתחלת בתהליך ההרשמה אך לא סיימת.\n"
                    "אנא שלח את כתובת האימייל שלך (לצורך תשלום עתידי ב-Gumroad) ואת המילה 'מאשר' או 'מקובל'.\n"
                    "לדוגמה: `myemail@example.com מאשר`"
                )
                logger.info(f"--- FULL BOT: Re-prompt message sent to {user.id}. Returning AWAITING_EMAIL_AND_CONFIRMATION. ---")
                return AWAITING_EMAIL_AND_CONFIRMATION

        logger.info(f"--- FULL BOT: User {user.id} is new or needs to restart disclaimer. Preparing disclaimer message. ---")
        today_str, trial_end_str = get_disclaimer_dates()
        disclaimer_message = (
            # ... (הודעת התנאים המקורית שלך) ...
            f"היי, זה מצוות הערוץ ״חדר vip -TradeCore״\n\n"
            f"המנוי שלך (לתקופת הניסיון) יתחיל עם אישור התנאים ויסתיים כעבור {config.TRIAL_PERIOD_DAYS} ימים.\n"
            f"(לתשומת ליבך, אם תאשר היום {today_str}, הניסיון יסתיים בערך ב-{trial_end_str}).\n\n"
            f"חשוב להבהיר: 🚫התוכן כאן אינו מהווה ייעוץ או המלצה פיננסית מכל סוג! "
            f"📌 ההחלטות בסופו של דבר בידיים שלכם – איך לפעול, מתי להיכנס ומתי לצאת מהשוק.\n\n"
            f"כדי להמשיך, אנא שלח את כתובת האימייל שלך (זו שתשמש לתשלום ב-Gumroad אם תבחר להמשיך) ולאחר מכן את המילה 'מאשר' או 'מקובל'.\n"
            f"לדוגמה: `myemail@example.com מאשר`"
        )
        await update.message.reply_text(disclaimer_message)
        logger.info(f"--- FULL BOT: Disclaimer message sent to {user.id}. ---")

        logger.info(f"--- FULL BOT: Step 2 - Adding/updating user {user.id} in GSheets for disclaimer. ---")
        add_success = g_sheets.add_new_user_for_disclaimer(user.id, effective_username)
        logger.info(f"--- FULL BOT: g_sheets.add_new_user_for_disclaimer returned: {add_success} ---")
        if not add_success and config.ADMIN_USER_ID and config.ADMIN_USER_ID != 0:
            await context.bot.send_message(config.ADMIN_USER_ID, f"שגיאה בהוספת משתמש {user.id} ל-GSheets בשלב ההצהרה.")

        logger.info(f"--- FULL BOT: Step 3 - Scheduling 24h warning job for {user.id}. ---")
        job_name = f"disclaimer_warning_{user.id}"
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()
        context.job_queue.run_once(
            disclaimer_24h_warning_job_callback,
            datetime.timedelta(hours=config.REMINDER_MESSAGE_HOURS_BEFORE_WARNING),
            chat_id=user.id,
            name=job_name,
            data={'user_id': user.id}
        )
        logger.info(f"--- FULL BOT: Scheduled 24h disclaimer warning for user {user.id}. Returning AWAITING_EMAIL_AND_CONFIRMATION. ---")
        return AWAITING_EMAIL_AND_CONFIRMATION

    except Exception as e:
        logger.error(f"--- FULL BOT: EXCEPTION in start_command for user {user.id}: {e} ---", exc_info=True)
        try:
            await update.message.reply_text("מצטער, אירעה שגיאה פנימית בשרת. אנא נסה שוב מאוחר יותר או פנה למנהל.")
        except Exception as e_reply_err:
            logger.error(f"--- FULL BOT: Failed to send error reply to user {user.id}: {e_reply_err} ---")
        return ConversationHandler.END # במקרה של שגיאה, סיים את השיחה
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """שולח הודעת פתיחה כאשר הפקודה /start מופעלת."""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.first_name}) started the bot.")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"שלום {user.first_name}! ברוך הבא לבוט VIP."
    )

async def handle_user_removal(context: CallbackContext) -> None:
    """
    פונקציה לטיפול בהסרת משתמשים (לדוגמה).
    הלוגיקה המקורית שלך אמורה להיות כאן.
    כרגע מכילה 'pass' כדי למנוע שגיאת IndentationError אם היא הייתה ריקה.
    """
    logger.info("Running scheduled task: handle_user_removal")
    # ... כאן אמור להיות הקוד המקורי שלך לטיפול בהסרת משתמשים ...
    # לדוגמה, בדיקה מול Google Sheets, שליחת הודעות וכו'.
    # await context.bot.send_message(chat_id="SOME_ADMIN_ID", text="User removal check executed.")
    pass  # הוספנו pass למקרה שהגוף היה ריק או הכיל רק הערות

# --- Flask Webhook ---
@flask_app.route('/webhook', methods=['POST'])
def webhook():
    """
    מקבל עדכונים מה-webhook של טלגרם (אם מוגדר כך) או משמש לצרכים אחרים.
    כרגע בעיקר מדגים קריאה אסינכרונית מתוך Flask.
    """
    logger.info("Webhook called")
    data = request.json
    logger.debug(f"Webhook data: {data}")
    # ... כאן אמורה להיות לוגיקת ה-webhook שלך ...

    # דוגמה לשימוש ב-async בתוך Flask (אם נדרש)
    # שים לב: הרצת asyncio.run בצורה זו בתוך כל קריאת webhook עשויה להיות לא אופטימלית
    # לסביבות פרודקשן עתירות תעבורה. יש לשקול פתרונות מתקדמים יותר אם יש צורך.
    async def async_task_in_webhook():
        logger.info("Executing async_task_in_webhook")
        # אם אתה צריך להשתמש ב-Bot כאן, ודא שהוא מאותחל כראוי.
        # אם TELEGRAM_TOKEN או CHANNEL_ID אינם מוגדרים, השורות הבאות יגרמו לשגיאה.
        # לכן, כרגע הוספנו 'pass' כדי למנוע קריסה אם המשתנים חסרים.
        if TELEGRAM_TOKEN != "YOUR_TELEGRAM_BOT_TOKEN" and CHANNEL_ID != "YOUR_CHANNEL_ID":
            try:
                bot_instance = Bot(token=TELEGRAM_TOKEN)
                await bot_instance.send_message(chat_id=CHANNEL_ID, text="הודעה חדשה התקבלה דרך ה-webhook")
                logger.info("Message sent from async_task_in_webhook")
            except Exception as e:
                logger.error(f"Error in async_task_in_webhook: {e}")
        else:
            logger.warning("TELEGRAM_TOKEN or CHANNEL_ID not configured for async_task_in_webhook.")
            pass # מונע שגיאה אם הטוקנים לא הוגדרו

    asyncio.run(async_task_in_webhook())

    return 'OK', 200

# --- פונקציה ראשית להפעלת הבוט ---
async def simple_start_command_for_full_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"--- FULL BOT (SIMPLIFIED HANDLER): /start received by user {user.id} ({user.username or user.first_name}) ---")
    try:
        await update.message.reply_text('FULL BOT (SIMPLIFIED HANDLER) responding to /start!')
        logger.info(f"--- FULL BOT (SIMPLIFIED HANDLER): Reply sent to user {user.id} ---")
    except Exception as e:
        logger.error(f"--- FULL BOT (SIMPLIFIED HANDLER): Error sending reply to user {user.id}: {e} ---", exc_info=True)

async def general_error_handler_for_full_bot(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """רושם שגיאות שנגרמו על ידי עדכונים ומנסה להודיע למשתמש אם אפשר."""
    logger.error("--- FULL BOT: Exception during update processing by dispatcher ---", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("אופס! משהו השתבש בעיבוד הבקשה. אנא נסה שוב מאוחר יותר או פנה למנהל.")
        except Exception as e_reply:
            logger.error(f"--- FULL BOT: Failed to send error reply message to user: {e_reply} ---")
    elif isinstance(update, Update) and update.callback_query:
         try:
             await update.callback_query.answer("אופס! משהו השתבש בעיבוד הבקשה.", show_alert=True)
             if update.effective_message: # נסה לשלוח גם הודעה אם אפשר
                await update.effective_message.reply_text("אופס! משהו השתבש בעיבוד הבקשה. אנא נסה שוב מאוחר יותר או פנה למנהל.")
         except Exception as e_cb_reply:
             logger.error(f"--- FULL BOT: Failed to send error answer/reply to callback_query: {e_cb_reply} ---")


application_instance.add_handler(CommandHandler("start", simple_start_command_for_full_bot))
application_instance.add_error_handler(general_error_handler_for_full_bot) # חשוב מאוד!

# ... (הקוד שמפעיל את ה-Scheduler וה-Polling נשאר כמו שהוא) ...
async def main() -> None:
    """הפונקציה הראשית שמגדירה ומריצה את בוט הטלגרם."""
    if TELEGRAM_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error("TELEGRAM_TOKEN is not configured. Please set your bot token.")
        return

    logger.info("Starting bot application...")
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # הוספת פקודות (Handlers)
    application.add_handler(CommandHandler("start", start))
    # ... הוסף כאן את שאר ההאנדלרים שלך ...
    # לדוגמה:
    # application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # הגדרת מתזמן (Scheduler) למשימות רקע
    # ודא ש-handle_user_removal מוגדרת כראוי ומקבלת את הארגומנטים הנכונים
    # application.job_queue נותן לך גישה ל-JobQueue של הבוט, שהוא עדיף לשימוש עם ה-application context
    # במקום BackgroundScheduler נפרד אם המשימות קשורות ישירות לבוט.
    # עם זאת, אם אתה משתמש ב-BackgroundScheduler, הקוד שלך נראה תקין מבחינת ההגדרה.

    # שימוש ב-JobQueue של ספריית python-telegram-bot (מומלץ יותר למשימות הקשורות לבוט)
    if application.job_queue:
        application.job_queue.run_repeating(
            handle_user_removal,
            interval=timedelta(hours=24), # כל 24 שעות
            first=timedelta(minutes=1), # הרצה ראשונה בעוד דקה
            name="handle_user_removal_job"
            # context יכול להיות מועבר כאן אם הפונקציה צריכה context מסוים.
            # handle_user_removal צריכה לקבל `context: CallbackContext` כארגומנט.
        )
        logger.info("Scheduled job 'handle_user_removal_job' using JobQueue.")
    else:
        # אם אתה חייב להשתמש ב-BackgroundScheduler נפרד:
        scheduler = BackgroundScheduler(timezone=timezone('Asia/Jerusalem'))
        # כדי להעביר את ה-application context ל-handle_user_removal בצורה בטוחה עם apscheduler,
        # עדיף שהפונקציה תקבל את ה-bot instance או משהו דומה, ולא את כל ה-application.
        # עם זאת, אם handle_user_removal מצפה ל-CallbackContext עם ה-application,
        # ייתכן שתצטרך לעטוף את הקריאה.
        # כרגע, `handle_user_removal` מקבלת `CallbackContext` אך לא משתמשת בו בצורה שמצריכה את ה-application ישירות ב-args.
        # אם היא כן צריכה, עדיף להשתמש ב-JobQueue.
        # דוגמה פשוטה אם הפונקציה לא צריכה את האובייקט application ישירות:
        # scheduler.add_job(handle_user_removal, 'interval', hours=24, next_run_time=datetime.now(timezone('Asia/Jerusalem')) + timedelta(minutes=1))
        # scheduler.start()
        # logger.info("BackgroundScheduler started for handle_user_removal.")
        logger.warning("JobQueue not available or chosen not to use. BackgroundScheduler example commented out.")
        pass # אם לא משתמשים באף אחד מהם

    # הפעלת הבוט (polling)
    logger.info("Starting bot polling...")
    try:
        await application.initialize() # מומלץ להפעיל לפני run_polling
        await application.start()
        await application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Error during bot execution: {e}", exc_info=True)
    finally:
        logger.info("Stopping bot application...")
        await application.stop()
        await application.shutdown() # מומלץ להפעיל בסיום

# --- הרצת האפליקציה ---
# כאשר הקובץ רץ ישירות (לא מיובא כמודול)
if __name__ == '__main__':
    # הערה חשובה לגבי הרצת Flask ובוט Telegram יחד:
    # הרצת `flask_app.run()` ו-`asyncio.run(main())` באותו תהליך ראשי בצורה סדרתית
    # תגרום לכך שרק הראשון ירוץ (כי `flask_app.run()` חוסם, וגם `run_polling` חוסם).
    # אם אתה מריץ את זה עם Gunicorn (כפי שהיה בלוג המקורי שלך: `gunicorn bot:flask_app`),
    # אז Gunicorn אחראי להרצת אפליקציית ה-Flask (flask_app).
    # הבוט של טלגרם (main) צריך לרוץ בתהליך נפרד או ב-thread נפרד,
    # או שאם ה-webhook של Flask משמש להעברת עדכונים מה-Telegram API לבוט שלך,
    # אז הלוגיקה של `main()` (כמו `application.run_polling()`) אולי לא נחוצה כלל,
    # ובמקומה `application.process_update()` יקרא מתוך ה-webhook.

    # תרחיש 1: Gunicorn מריץ את Flask, וה-Webhook מטפל בעדכונים (אין צורך ב-run_polling).
    # במקרה כזה, הקוד ב-`if __name__ == '__main__':` אולי לא רלוונטי לפרודקשן עם Gunicorn.
    # Gunicorn יריץ את `flask_app`. תצטרך לוודא שה-Application של הבוט מאותחל
    # וזמין לפונקציית ה-webhook כדי שתוכל לעשות `application.process_update()`.

    # תרחיש 2: אתה מריץ את Flask וגם את הבוט (polling) מאותו קובץ מקומית לפיתוח.
    # זה דורש טיפול מורכב יותר עם threads או asyncio event loops נפרדים.

    # להלן דוגמה פשוטה להרצה מקומית של הבוט בלבד (ללא Flask):
    logger.info("Attempting to run Telegram bot locally (main function)...")
    asyncio.run(main())

    # אם אתה רוצה להריץ גם את Flask במקביל לפיתוח מקומי (לא מומלץ לפרודקשן באותה צורה):
    # import threading
    # def run_flask():
    # flask_app.run(port=5000, debug=False, use_reloader=False) # use_reloader=False חשוב עם threads
    #
    # flask_thread = threading.Thread(target=run_flask)
    # flask_thread.start()
    #
    # asyncio.run(main())
    #
    # (זהירות: הרצה כזו יכולה להיות מורכבת לניהול ולדיבאגינג)
