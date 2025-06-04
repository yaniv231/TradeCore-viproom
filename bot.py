# bot.py

# ... (שאר הקוד ללא שינוי) ...
from telegram.ext import ContextTypes
# --- פונקציות עזר חדשות לשליחה אסינכרונית של פעולות ניהול ---
async def async_handle_user_removal(context: ContextTypes.DEFAULT_TYPE):
    """
    פונקציה אסינכרונית לטיפול בהסרת משתמש מהערוץ, שליחת הודעה ועדכון GSheet.
    נקראת דרך ה-JobQueue.
    """
    job_data = context.job.data
    user_id = job_data['user_id']
    logger.info(f"Async job: Starting removal process for user {user_id}")
    try:
        # ה-bot זמין דרך context.bot
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
        logger.error(f"Async job: Error during removal process for user {user_id}: {e}", exc_info=True)
        # גם אם יש שגיאה בפעולת הטלגרם, נעדכן את הסטטוס ב-GSheet
        g_sheets.update_user_status(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.EXPIRED_NO_PAYMENT.value})
        logger.info(f"Async job: Updated GSheet status for user {user_id} to EXPIRED_NO_PAYMENT despite Telegram API error during removal.")


# --- משימות מתוזמנות עם APScheduler ---
def check_trials_and_reminders_job(): # פונקציה סינכרונית שנקראת על ידי APScheduler
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
            # ... (קוד שליחת הודעת התזכורת, הוא כבר משתמש ב-job_queue וזה בסדר) ...
            reminder_text = (
                f"היי, כאן צוות {config.CHANNEL_USERNAME or 'TradeCore VIP'} 👋\n\n"
                f"שבוע הניסיון שלך בערוץ ״חדר vip -TradeCore״ עומד להסתיים.\n"
                # ... (שאר ההודעה) ...
            )
            application_instance.job_queue.run_once(
                send_async_message, 0, chat_id=user_id, data={'text': reminder_text}, name=f"trial_reminder_{user_id}"
            )
            g_sheets.update_user_status(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.PENDING_PAYMENT_AFTER_TRIAL.value})


        elif action == 'remove_user_no_payment':
            logger.info(f"APScheduler: Queuing removal task for user {user_id} (email: {email}) due to no payment after trial.")
            # כאן התיקון: במקום לבצע await ישירות, קובעים משימה ל-job_queue
            application_instance.job_queue.run_once(
                async_handle_user_removal, # הפונקציה האסינכרונית החדשה
                0, # שלח מיד
                chat_id=user_id, # לזיהוי ה-job
                data={'user_id': user_id}, # העבר את ה-user_id הנדרש
                name=f"exec_removal_{user_id}"
            )
            # את עדכון הסטטוס ב-GSheet העברנו לתוך הפונקציה האסינכרונית
            # g_sheets.update_user_status(user_id, {g_sheets.COL_PAYMENT_STATUS: PaymentStatus.EXPIRED_NO_PAYMENT.value}) # <--- לא כאן

# ... (שאר הקוד) ...
