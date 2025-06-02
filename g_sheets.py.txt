# g_sheets.py
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import datetime
from enum import Enum

import config # ייבוא קובץ ההגדרות

# הגדרת עמודות (ודא שהן תואמות למה שיש לך בגיליון)
COL_USER_ID = 'telegram_user_id'
COL_USERNAME = 'telegram_username' # חדש, מומלץ להוסיף
COL_EMAIL = 'email'
COL_DISCLAIMER_SENT_TIME = 'disclaimer_sent_time'
COL_CONFIRMATION_STATUS = 'confirmation_status' # (pending_disclaimer, confirmed_disclaimer, warned_no_disclaimer, trial_pending_payment, trial_active, paid_subscriber, cancelled, expired)
COL_TRIAL_START_DATE = 'trial_start_date'
COL_TRIAL_END_DATE = 'trial_end_date'
COL_PAYMENT_STATUS = 'payment_status' # (pending, trial, paid, expired, cancelled_by_user)
COL_GUMROAD_SALE_ID = 'gumroad_sale_id'
COL_GUMROAD_SUBSCRIPTION_ID = 'gumroad_subscription_id' # אם גאמרוד מחזירים מזהה מנוי
COL_LAST_UPDATE = 'last_update_timestamp'

# ערכים אפשריים לסטטוס אישור
class ConfirmationStatus(Enum):
    PENDING_DISCLAIMER = "pending_disclaimer"
    CONFIRMED_DISCLAIMER = "confirmed_disclaimer"
    WARNED_NO_DISCLAIMER = "warned_no_disclaimer_approval"
    CANCELLED_NO_DISCLAIMER = "cancelled_no_disclaimer_approval"

# ערכים אפשריים לסטטוס תשלום/מנוי
class PaymentStatus(Enum):
    TRIAL = "trial"
    PENDING_PAYMENT_AFTER_TRIAL = "pending_payment_after_trial"
    PAID_SUBSCRIBER = "paid_subscriber"
    EXPIRED_NO_PAYMENT = "expired_no_payment"
    CANCELLED_BY_USER = "cancelled_by_user" # אם גאמרוד שולחים אירוע כזה

# --- התחברות ל-Google Sheets ---
def get_sheet():
    """מתחבר ל-Google Sheet ומחזיר אובייקט של הגיליון."""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        # כאן נשתמש בתוכן הקובץ אם הוא מועבר כמשתנה סביבה, או בנתיב אם הקובץ קיים בשרת
        if config.GSHEET_SERVICE_ACCOUNT_FILE.endswith('.json'):
             creds = ServiceAccountCredentials.from_json_keyfile_name(config.GSHEET_SERVICE_ACCOUNT_FILE, scope)
        else: # נניח שהתוכן של ה-JSON נמצא במשתנה הסביבה
            import json
            creds_json = json.loads(config.GSHEET_SERVICE_ACCOUNT_FILE)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)

        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(config.GSHEET_SPREADSHEET_ID)
        sheet = spreadsheet.worksheet(config.GSHEET_SHEET_NAME)
        return sheet
    except Exception as e:
        print(f"Error connecting to Google Sheets: {e}")
        return None

# --- פונקציות לניהול משתמשים ---
def find_user_row(sheet, user_id):
    """מוצא שורה של משתמש לפי user_id. מחזיר את מספר השורה או None."""
    try:
        cell = sheet.find(str(user_id), in_column=sheet.find(COL_USER_ID).col) # מצא את עמודת user_id
        return cell.row
    except gspread.exceptions.CellNotFound:
        return None
    except Exception as e:
        print(f"Error finding user {user_id}: {e}")
        return None

def get_user_data(user_id):
    """מחזיר נתונים של משתמש ספציפי או None אם לא נמצא."""
    sheet = get_sheet()
    if not sheet: return None
    row_num = find_user_row(sheet, user_id)
    if row_num:
        user_record_values = sheet.row_values(row_num)
        headers = sheet.row_values(1) # קבלת כותרות העמודות
        return dict(zip(headers, user_record_values))
    return None

def add_new_user_for_disclaimer(user_id, username):
    """מוסיף משתמש חדש שממתין לאישור התנאים."""
    sheet = get_sheet()
    if not sheet: return False
    if find_user_row(sheet, user_id): # בדוק אם המשתמש כבר קיים
        print(f"User {user_id} already exists. Updating disclaimer sent time.")
        return update_user_disclaimer_status(user_id, ConfirmationStatus.PENDING_DISCLAIMER.value, datetime.datetime.now().isoformat())

    now_iso = datetime.datetime.now().isoformat()
    # ודא שהכותרות קיימות בגיליון שלך
    # סדר הכנסת הנתונים חייב להתאים לסדר העמודות או שתשתמש בשמות עמודות
    new_row_data = {
        COL_USER_ID: str(user_id),
        COL_USERNAME: username,
        COL_EMAIL: '', # יתעדכן מאוחר יותר
        COL_DISCLAIMER_SENT_TIME: now_iso,
        COL_CONFIRMATION_STATUS: ConfirmationStatus.PENDING_DISCLAIMER.value,
        COL_TRIAL_START_DATE: '',
        COL_TRIAL_END_DATE: '',
        COL_PAYMENT_STATUS: '',
        COL_GUMROAD_SALE_ID: '',
        COL_GUMROAD_SUBSCRIPTION_ID: '',
        COL_LAST_UPDATE: now_iso
    }
    # אם הגיליון ריק לגמרי, הוסף כותרות
    if sheet.row_count == 0:
        sheet.append_row(list(new_row_data.keys()))
        sheet.append_row(list(new_row_data.values()))
    else:
        # התאם את סדר הערכים לסדר העמודות שלך בפועל אם אתה משתמש ב-append_row
        # עדיף להשתמש ב-update עם cell_list אם הסדר לא מובטח
        # או לוודא שהכותרות כבר קיימות ומסודרות נכון.
        # לצורך פשטות כאן, נניח שאתה דואג לסדר העמודות בגיליון שיתאים ל-keys של new_row_data
        try:
            sheet.append_row([new_row_data.get(col_name, '') for col_name in sheet.row_values(1)])
        except Exception as e: # אם יש בעיה בהתאמת עמודות
             print(f"Error appending row, ensure columns match dictionary keys or handle column mapping: {e}")
             return False
    return True


def update_user_email_and_confirmation(user_id, email, confirmation_status_enum: ConfirmationStatus):
    """מעדכן אימייל וסטטוס אישור תנאים."""
    sheet = get_sheet()
    if not sheet: return False
    row_num = find_user_row(sheet, user_id)
    if not row_num: return False

    updates = {
        COL_EMAIL: email,
        COL_CONFIRMATION_STATUS: confirmation_status_enum.value,
        COL_LAST_UPDATE: datetime.datetime.now().isoformat()
    }
    for col_name, value in updates.items():
        try:
            col_num = sheet.find(col_name).col
            sheet.update_cell(row_num, col_num, value)
        except gspread.exceptions.CellNotFound:
            print(f"Column {col_name} not found in sheet.")
        except Exception as e:
            print(f"Error updating cell for user {user_id}, column {col_name}: {e}")
            return False
    return True

def start_user_trial(user_id):
    """מתחיל תקופת ניסיון למשתמש שאישר תנאים."""
    sheet = get_sheet()
    if not sheet: return False
    row_num = find_user_row(sheet, user_id)
    if not row_num: return False

    now = datetime.datetime.now()
    trial_start_date_iso = now.isoformat()
    trial_end_date_iso = (now + datetime.timedelta(days=config.TRIAL_PERIOD_DAYS)).isoformat()

    updates = {
        COL_TRIAL_START_DATE: trial_start_date_iso,
        COL_TRIAL_END_DATE: trial_end_date_iso,
        COL_PAYMENT_STATUS: PaymentStatus.TRIAL.value,
        COL_LAST_UPDATE: now.isoformat()
    }
    for col_name, value in updates.items():
        try:
            col_num = sheet.find(col_name).col
            sheet.update_cell(row_num, col_num, value)
        except gspread.exceptions.CellNotFound:
            print(f"Column {col_name} not found in sheet.")
        except Exception as e:
            print(f"Error updating cell for user {user_id}, column {col_name}: {e}")
            return False
    return True


def update_user_disclaimer_status(user_id, status_enum: ConfirmationStatus, disclaimer_sent_time_iso=None):
    """מעדכן סטטוס אישור תנאים וזמן שליחת ההודעה."""
    sheet = get_sheet()
    if not sheet: return False
    row_num = find_user_row(sheet, user_id)
    if not row_num:
        print(f"Cannot update disclaimer status, user {user_id} not found.")
        return False

    updates = {
        COL_CONFIRMATION_STATUS: status_enum.value,
        COL_LAST_UPDATE: datetime.datetime.now().isoformat()
    }
    if disclaimer_sent_time_iso:
        updates[COL_DISCLAIMER_SENT_TIME] = disclaimer_sent_time_iso

    for col_name, value in updates.items():
        try:
            col_num = sheet.find(col_name).col
            sheet.update_cell(row_num, col_num, value)
        except gspread.exceptions.CellNotFound:
            print(f"Column {col_name} not found in sheet.")
        except Exception as e:
            print(f"Error updating cell for user {user_id}, column {col_name}: {e}")
            return False
    return True

def update_user_payment_status_from_gumroad(email, gumroad_sale_id, gumroad_subscription_id=None):
    """מעדכן סטטוס תשלום לאחר קבלת Webhook מ-Gumroad."""
    sheet = get_sheet()
    if not sheet: return False

    try:
        # מצא את המשתמש לפי האימייל
        email_col_header = COL_EMAIL
        email_col_num = sheet.find(email_col_header).col
        cell = sheet.find(email, in_column=email_col_num)
        row_num = cell.row
    except gspread.exceptions.CellNotFound:
        print(f"User with email {email} not found for Gumroad sale {gumroad_sale_id}.")
        # כאן אפשר לשקול ליצור משתמש חדש אם רוצים, או פשוט להתעלם אם האימייל לא קיים
        return False
    except Exception as e:
        print(f"Error finding user by email {email}: {e}")
        return False

    updates = {
        COL_PAYMENT_STATUS: PaymentStatus.PAID_SUBSCRIBER.value,
        COL_GUMROAD_SALE_ID: str(gumroad_sale_id),
        COL_CONFIRMATION_STATUS: ConfirmationStatus.CONFIRMED_DISCLAIMER.value, # אם שילם, הוא בהכרח מאושר
        COL_LAST_UPDATE: datetime.datetime.now().isoformat()
    }
    if gumroad_subscription_id:
        updates[COL_GUMROAD_SUBSCRIPTION_ID] = str(gumroad_subscription_id)
    # אם המשתמש שילם, נאפס את תאריכי הניסיון (אם היו) או שנקבע לו מועד תפוגת מנוי חדש
    # זה תלוי אם גאמרוד שולחים תאריך תפוגה למנוי
    # לצורך הפשטות, רק נעדכן שהוא שילם. ניהול תפוגת מנוי הוא שלב מתקדם יותר.
    # updates[COL_TRIAL_START_DATE] = ''
    # updates[COL_TRIAL_END_DATE] = ''


    for col_name, value in updates.items():
        try:
            col_num = sheet.find(col_name).col
            sheet.update_cell(row_num, col_num, value)
        except gspread.exceptions.CellNotFound:
            print(f"Column {col_name} not found in sheet.")
        except Exception as e:
            print(f"Error updating cell for user by email {email}, column {col_name}: {e}")
            return False
    print(f"User {email} payment status updated from Gumroad sale {gumroad_sale_id}.")
    # החזר את ה-user_id של טלגרם אם הוא קיים, כדי שהבוט יוכל לשלוח לו הודעת אישור תשלום
    user_id_col_num = sheet.find(COL_USER_ID).col
    telegram_user_id = sheet.cell(row_num, user_id_col_num).value
    return telegram_user_id


def get_users_for_disclaimer_warning():
    """מחזיר משתמשים שצריך לשלוח להם אזהרה על אי אישור תנאים."""
    sheet = get_sheet()
    if not sheet: return []
    users_to_warn = []
    all_users = sheet.get_all_records() # קל יותר לעבוד עם רשומות כמילונים
    for user_data in all_users:
        if user_data.get(COL_CONFIRMATION_STATUS) == ConfirmationStatus.PENDING_DISCLAIMER.value:
            disclaimer_sent_time_str = user_data.get(COL_DISCLAIMER_SENT_TIME)
            if disclaimer_sent_time_str:
                disclaimer_sent_time = datetime.datetime.fromisoformat(disclaimer_sent_time_str)
                if datetime.datetime.now() > disclaimer_sent_time + datetime.timedelta(hours=config.REMINDER_MESSAGE_HOURS_BEFORE_WARNING):
                    users_to_warn.append(user_data)
    return users_to_warn


def get_users_for_trial_reminder_or_removal():
    """מחזיר משתמשים שתקופת הניסיון שלהם הסתיימה או עומדת להסתיים ולא שילמו."""
    sheet = get_sheet()
    if not sheet: return []
    users_to_process = []
    all_users = sheet.get_all_records()
    now = datetime.datetime.now()

    for user_data in all_users:
        payment_status = user_data.get(COL_PAYMENT_STATUS)
        trial_end_date_str = user_data.get(COL_TRIAL_END_DATE)

        if payment_status == PaymentStatus.TRIAL.value and trial_end_date_str:
            trial_end_date = datetime.datetime.fromisoformat(trial_end_date_str)
            # אם הניסיון הסתיים או עומד להסתיים ב-24 שעות הקרובות (סתם דוגמה, אפשר לשנות)
            if now >= trial_end_date - datetime.timedelta(days=1):
                users_to_process.append({'action': 'send_trial_end_reminder', 'data': user_data})
        elif payment_status == PaymentStatus.PENDING_PAYMENT_AFTER_TRIAL.value and trial_end_date_str:
            # אם נשלחה כבר תזכורת, והוא עדיין לא שילם ועברו X ימים מאז סוף הניסיון
            trial_end_date = datetime.datetime.fromisoformat(trial_end_date_str)
            if now >= trial_end_date + datetime.timedelta(days=2): # יומיים אחרי סוף הניסיון, לדוגמה
                 users_to_process.append({'action': 'remove_user_no_payment', 'data': user_data})
    return users_to_process

def update_user_status(user_id, updates: dict):
    """מעדכן שדות ספציפיים עבור משתמש."""
    sheet = get_sheet()
    if not sheet: return False
    row_num = find_user_row(sheet, user_id)
    if not row_num:
        print(f"Cannot update status, user {user_id} not found.")
        return False

    updates[COL_LAST_UPDATE] = datetime.datetime.now().isoformat() # תמיד עדכן זמן עדכון אחרון

    for col_name, value in updates.items():
        try:
            col_num = sheet.find(col_name).col # מצא את מספר העמודה לפי הכותרת
            sheet.update_cell(row_num, col_num, value)
        except gspread.exceptions.CellNotFound:
            print(f"Column {col_name} not found in sheet. Cannot update value: {value}")
        except Exception as e:
            print(f"Error updating cell for user {user_id}, column {col_name}: {e}")
            return False
    return True


# דוגמה לשימוש (לא חלק מהמודול הסופי, רק לבדיקה)
# if __name__ == '__main__':
#     sheet = get_sheet()
#     if sheet:
#         print("Successfully connected to Google Sheet.")
#         # הדפס כותרות
#         # print(sheet.row_values(1))
#         # add_new_user_for_disclaimer(12345, "testuser")
#         # user = get_user_data(12345)
#         # print(user)
#         # update_user_email_and_confirmation(12345, "test@example.com", ConfirmationStatus.CONFIRMED_DISCLAIMER)
#         # start_user_trial(12345)
#         # user = get_user_data(12345)
#         # print(user)
#         # users_to_warn_list = get_users_for_disclaimer_warning()
#         # print(f"Users to warn (disclaimer): {users_to_warn_list}")
#         # users_for_trial_process = get_users_for_trial_reminder_or_removal()
#         # print(f"Users for trial processing: {users_for_trial_process}")