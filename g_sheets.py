# g_sheets.py
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import datetime
from enum import Enum
import json # חשוב לייבוא json
import os   # חשוב לייבוא os
import logging # הוספת לוגינג למודול הזה

import config # ייבוא קובץ ההגדרות

logger = logging.getLogger(__name__) # הגדרת לוגר ספציפי למודול זה

# הגדרת עמודות (ודא שהן תואמות למה שיש לך בגיליון)
COL_USER_ID = 'telegram_user_id'
COL_USERNAME = 'telegram_username'
COL_EMAIL = 'email'
COL_DISCLAIMER_SENT_TIME = 'disclaimer_sent_time'
COL_CONFIRMATION_STATUS = 'confirmation_status'
COL_TRIAL_START_DATE = 'trial_start_date'
COL_TRIAL_END_DATE = 'trial_end_date'
COL_PAYMENT_STATUS = 'payment_status'
COL_GUMROAD_SALE_ID = 'gumroad_sale_id'
COL_GUMROAD_SUBSCRIPTION_ID = 'gumroad_subscription_id'
COL_LAST_UPDATE = 'last_update_timestamp'

class ConfirmationStatus(Enum):
    PENDING_DISCLAIMER = "pending_disclaimer"
    CONFIRMED_DISCLAIMER = "confirmed_disclaimer"
    WARNED_NO_DISCLAIMER = "warned_no_disclaimer_approval"
    CANCELLED_NO_DISCLAIMER = "cancelled_no_disclaimer_approval"

class PaymentStatus(Enum):
    TRIAL = "trial"
    PENDING_PAYMENT_AFTER_TRIAL = "pending_payment_after_trial"
    PAID_SUBSCRIBER = "paid_subscriber"
    EXPIRED_NO_PAYMENT = "expired_no_payment"
    CANCELLED_BY_USER = "cancelled_by_user"

def get_sheet():
    """מתחבר ל-Google Sheet ומחזיר אובייקט של הגיליון."""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        
        # קודם כל, נסה לקרוא את תוכן ה-JSON ממשתנה הסביבה שהגדרנו במיוחד עבור זה
        # ב-Render נגדיר את GSHEET_SERVICE_ACCOUNT_JSON_CONTENT
        gsa_json_content_str = os.environ.get('GSHEET_SERVICE_ACCOUNT_JSON_CONTENT')
        
        if gsa_json_content_str:
            logger.info("Attempting to use GSHEET_SERVICE_ACCOUNT_JSON_CONTENT from environment variable.")
            creds_json = json.loads(gsa_json_content_str)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
        elif config.GSHEET_SERVICE_ACCOUNT_FILE and os.path.exists(config.GSHEET_SERVICE_ACCOUNT_FILE):
            # אם משתנה הסביבה לא קיים, אבל משתנה הקונפיג כן מצביע על קובץ קיים (לפיתוח מקומי)
            logger.info(f"GSHEET_SERVICE_ACCOUNT_JSON_CONTENT not found, attempting to use GSHEET_SERVICE_ACCOUNT_FILE: {config.GSHEET_SERVICE_ACCOUNT_FILE}")
            creds = ServiceAccountCredentials.from_json_keyfile_name(config.GSHEET_SERVICE_ACCOUNT_FILE, scope)
        else:
            logger.error("Google Sheets credentials not found. "
                           "Please set GSHEET_SERVICE_ACCOUNT_JSON_CONTENT env var in Render "
                           "or a valid GSHEET_SERVICE_ACCOUNT_FILE path in config.py for local development.")
            return None

        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(config.GSHEET_SPREADSHEET_ID)
        sheet = spreadsheet.worksheet(config.GSHEET_SHEET_NAME)
        logger.info("Successfully connected to Google Sheet.")
        return sheet
    except FileNotFoundError as e_fnf:
        logger.error(f"Google Sheets credentials file (local fallback) not found: {e_fnf}")
        return None
    except json.JSONDecodeError as e_json:
        logger.error(f"Error decoding Google Sheets credentials JSON from environment variable: {e_json}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while connecting to Google Sheets: {e}", exc_info=True)
        return None

# --- (שאר הפונקציות בקובץ g_sheets.py נשארות כפי שהיו בגרסה שסיפקתי קודם) ---
# --- כלומר, find_user_row, get_user_data, add_new_user_for_disclaimer, וכו' ---

def find_user_row(sheet, user_id):
    """מוצא שורה של משתמש לפי user_id. מחזיר את מספר השורה או None."""
    if not sheet: return None
    try:
        user_id_col_index = gspread.utils.find_richtext_value_in_row(sheet.row_values(1), COL_USER_ID) + 1
        if user_id_col_index == 0: # find_richtext_value_in_row returns -1 if not found
            logger.error(f"Column '{COL_USER_ID}' not found in sheet header.")
            return None
        cell = sheet.find(str(user_id), in_column=user_id_col_index)
        return cell.row
    except gspread.exceptions.CellNotFound:
        return None
    except Exception as e:
        logger.error(f"Error finding user {user_id}: {e}")
        return None

def get_user_data(user_id):
    """מחזיר נתונים של משתמש ספציפי או None אם לא נמצא."""
    sheet = get_sheet()
    if not sheet: return None
    row_num = find_user_row(sheet, user_id)
    if row_num:
        try:
            user_record_values = sheet.row_values(row_num)
            headers = sheet.row_values(1) 
            return dict(zip(headers, user_record_values))
        except Exception as e:
            logger.error(f"Error fetching row values for user {user_id} at row {row_num}: {e}")
            return None
    return None

def add_new_user_for_disclaimer(user_id, username):
    sheet = get_sheet()
    if not sheet: return False
    
    # בדוק אם הגיליון ריק והוסף כותרות אם צריך
    headers_exist = False
    try:
        if sheet.row_count > 0 and sheet.row_values(1):
            headers_exist = True
    except Exception as e:
        logger.warning(f"Could not check existing headers, assuming they don't exist: {e}")

    expected_headers = [
        COL_USER_ID, COL_USERNAME, COL_EMAIL, COL_DISCLAIMER_SENT_TIME,
        COL_CONFIRMATION_STATUS, COL_TRIAL_START_DATE, COL_TRIAL_END_DATE,
        COL_PAYMENT_STATUS, COL_GUMROAD_SALE_ID, COL_GUMROAD_SUBSCRIPTION_ID,
        COL_LAST_UPDATE
    ]

    if not headers_exist:
        try:
            sheet.append_row(expected_headers)
            logger.info("Appended headers to empty sheet.")
        except Exception as e:
            logger.error(f"Failed to append headers to empty sheet: {e}")
            return False

    if find_user_row(sheet, user_id):
        logger.info(f"User {user_id} already exists. Updating disclaimer sent time.")
        return update_user_disclaimer_status(user_id, ConfirmationStatus.PENDING_DISCLAIMER, datetime.datetime.now().isoformat())

    now_iso = datetime.datetime.now().isoformat()
    new_row_data_dict = {
        COL_USER_ID: str(user_id),
        COL_USERNAME: username,
        COL_EMAIL: '',
        COL_DISCLAIMER_SENT_TIME: now_iso,
        COL_CONFIRMATION_STATUS: ConfirmationStatus.PENDING_DISCLAIMER.value,
        COL_TRIAL_START_DATE: '',
        COL_TRIAL_END_DATE: '',
        COL_PAYMENT_STATUS: '',
        COL_GUMROAD_SALE_ID: '',
        COL_GUMROAD_SUBSCRIPTION_ID: '',
        COL_LAST_UPDATE: now_iso
    }
    # סדר את הנתונים לפי סדר הכותרות הצפוי
    current_headers = sheet.row_values(1) if sheet.row_count > 0 else expected_headers
    new_row_values = [new_row_data_dict.get(header, '') for header in current_headers]

    try:
        sheet.append_row(new_row_values)
        logger.info(f"Added new user {user_id} ({username}) for disclaimer.")
        return True
    except Exception as e:
        logger.error(f"Error appending new user row for {user_id}: {e}")
        return False


def update_user_data(user_id, updates: dict):
    """מעדכן שדות ספציפיים עבור משתמש. הפונקציה המרכזית לעדכונים."""
    sheet = get_sheet()
    if not sheet: return False
    row_num = find_user_row(sheet, user_id)
    if not row_num:
        logger.warning(f"Cannot update data, user {user_id} not found in GSheet.")
        return False

    updates[COL_LAST_UPDATE] = datetime.datetime.now().isoformat()
    
    cells_to_update = []
    headers = sheet.row_values(1) # קבל כותרות כדי למצוא אינדקס עמודה

    for col_name, value in updates.items():
        try:
            # מצא את אינדקס העמודה (מבוסס 1)
            col_index = headers.index(col_name) + 1 
            cells_to_update.append(gspread.Cell(row_num, col_index, str(value)))
        except ValueError:
            logger.error(f"Column '{col_name}' not found in sheet header. Cannot update value: {value}")
        except Exception as e_cell:
            logger.error(f"Error preparing cell update for user {user_id}, column {col_name}: {e_cell}")
            return False
            
    if cells_to_update:
        try:
            sheet.update_cells(cells_to_update, value_input_option='USER_ENTERED')
            logger.info(f"Successfully updated data for user {user_id}: {updates.keys()}")
            return True
        except Exception as e_update:
            logger.error(f"Error bulk updating cells for user {user_id}: {e_update}")
            return False
    return False # אם לא היו עדכונים בפועל

def update_user_email_and_confirmation(user_id, email, confirmation_status_enum: ConfirmationStatus):
    updates = {
        COL_EMAIL: email,
        COL_CONFIRMATION_STATUS: confirmation_status_enum.value
    }
    return update_user_data(user_id, updates)

def start_user_trial(user_id):
    now = datetime.datetime.now()
    trial_start_date_iso = now.isoformat()
    trial_end_date_iso = (now + datetime.timedelta(days=config.TRIAL_PERIOD_DAYS)).isoformat()
    updates = {
        COL_TRIAL_START_DATE: trial_start_date_iso,
        COL_TRIAL_END_DATE: trial_end_date_iso,
        COL_PAYMENT_STATUS: PaymentStatus.TRIAL.value
    }
    return update_user_data(user_id, updates)

def update_user_disclaimer_status(user_id, status_enum: ConfirmationStatus, disclaimer_sent_time_iso=None):
    updates = {COL_CONFIRMATION_STATUS: status_enum.value}
    if disclaimer_sent_time_iso:
        updates[COL_DISCLAIMER_SENT_TIME] = disclaimer_sent_time_iso
    return update_user_data(user_id, updates)

def update_user_payment_status_from_gumroad(email, gumroad_sale_id, gumroad_subscription_id=None):
    sheet = get_sheet()
    if not sheet: return None # מחזיר None במקום False כדי שנוכל להבדיל

    try:
        headers = sheet.row_values(1)
        email_col_index = headers.index(COL_EMAIL) + 1
        cell = sheet.find(email, in_column=email_col_index)
        row_num = cell.row
        user_id_col_index = headers.index(COL_USER_ID) + 1
        telegram_user_id = sheet.cell(row_num, user_id_col_index).value
    except (gspread.exceptions.CellNotFound, ValueError):
        logger.warning(f"User with email {email} not found for Gumroad sale {gumroad_sale_id}.")
        return None
    except Exception as e:
        logger.error(f"Error finding user by email {email}: {e}")
        return None

    updates = {
        COL_PAYMENT_STATUS: PaymentStatus.PAID_SUBSCRIBER.value,
        COL_GUMROAD_SALE_ID: str(gumroad_sale_id),
        COL_CONFIRMATION_STATUS: ConfirmationStatus.CONFIRMED_DISCLAIMER.value,
    }
    if gumroad_subscription_id:
        updates[COL_GUMROAD_SUBSCRIPTION_ID] = str(gumroad_subscription_id)
    
    if update_user_data(int(telegram_user_id), updates): # המר את ה-ID למספר
        logger.info(f"User {email} (TG ID: {telegram_user_id}) payment status updated from Gumroad sale {gumroad_sale_id}.")
        return telegram_user_id # החזר את ה-ID של טלגרם
    return None


def get_users_for_disclaimer_warning():
    sheet = get_sheet()
    if not sheet: return []
    users_to_warn = []
    try:
        all_users = sheet.get_all_records()
        for user_data_dict in all_users:
            if user_data_dict.get(COL_CONFIRMATION_STATUS) == ConfirmationStatus.PENDING_DISCLAIMER.value:
                disclaimer_sent_time_str = user_data_dict.get(COL_DISCLAIMER_SENT_TIME)
                if disclaimer_sent_time_str:
                    try:
                        disclaimer_sent_time = datetime.datetime.fromisoformat(disclaimer_sent_time_str)
                        if datetime.datetime.now() > disclaimer_sent_time + datetime.timedelta(hours=config.REMINDER_MESSAGE_HOURS_BEFORE_WARNING):
                            users_to_warn.append(user_data_dict)
                    except ValueError:
                        logger.warning(f"Could not parse disclaimer_sent_time '{disclaimer_sent_time_str}' for user {user_data_dict.get(COL_USER_ID)}")
        return users_to_warn
    except Exception as e:
        logger.error(f"Error in get_users_for_disclaimer_warning: {e}")
        return []


def get_users_for_trial_reminder_or_removal():
    sheet = get_sheet()
    if not sheet: return []
    users_to_process = []
    now = datetime.datetime.now()
    try:
        all_users = sheet.get_all_records()
        for user_data_dict in all_users:
            payment_status_val = user_data_dict.get(COL_PAYMENT_STATUS)
            trial_end_date_str = user_data_dict.get(COL_TRIAL_END_DATE)

            if payment_status_val == PaymentStatus.TRIAL.value and trial_end_date_str:
                try:
                    trial_end_date = datetime.datetime.fromisoformat(trial_end_date_str)
                    if now >= trial_end_date - datetime.timedelta(days=1): # אם הניסיון הסתיים או מסתיים היום
                        users_to_process.append({'action': 'send_trial_end_reminder', 'data': user_data_dict})
                except ValueError:
                    logger.warning(f"Could not parse trial_end_date '{trial_end_date_str}' for user {user_data_dict.get(COL_USER_ID)}")
            
            elif payment_status_val == PaymentStatus.PENDING_PAYMENT_AFTER_TRIAL.value and trial_end_date_str:
                try:
                    trial_end_date = datetime.datetime.fromisoformat(trial_end_date_str)
                    if now >= trial_end_date + datetime.timedelta(days=2): # יומיים אחרי סוף הניסיון המקורי
                         users_to_process.append({'action': 'remove_user_no_payment', 'data': user_data_dict})
                except ValueError:
                     logger.warning(f"Could not parse trial_end_date '{trial_end_date_str}' for user {user_data_dict.get(COL_USER_ID)} in PENDING_PAYMENT_AFTER_TRIAL state.")
        return users_to_process
    except Exception as e:
        logger.error(f"Error in get_users_for_trial_reminder_or_removal: {e}")
        return []


def update_user_status(user_id, updates: dict): # שם הפונקציה שונה ל-update_user_status (כבר קיים, לוודא שזה זה)
    return update_user_data(user_id, updates)
