# g_sheets.py
import gspread
# from oauth2client.service_account import ServiceAccountCredentials # הישן
from google.oauth2.service_account import Credentials # החדש והמומלץ
import datetime
from enum import Enum
import json
import os
import logging

import config

logger = logging.getLogger(__name__)

# הגדרת עמודות
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

EXPECTED_HEADERS = [
    COL_USER_ID, COL_USERNAME, COL_EMAIL, COL_DISCLAIMER_SENT_TIME,
    COL_CONFIRMATION_STATUS, COL_TRIAL_START_DATE, COL_TRIAL_END_DATE,
    COL_PAYMENT_STATUS, COL_GUMROAD_SALE_ID, COL_GUMROAD_SUBSCRIPTION_ID,
    COL_LAST_UPDATE
]

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

_sheet_instance = None

def get_sheet():
    global _sheet_instance
    if _sheet_instance:
        try:
            # בדיקה פשוטה אם החיבור עדיין תקין על ידי קריאת הכותרות
            _sheet_instance.row_values(1)
            return _sheet_instance
        except Exception as e:
            logger.warning(f"Re-connecting to Google Sheet due to potential stale connection: {e}")
            _sheet_instance = None # אפס כדי לאלץ חיבור מחדש

    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        
        gsa_json_content_str = os.environ.get('GSHEET_SERVICE_ACCOUNT_JSON_CONTENT')
        
        if gsa_json_content_str:
            logger.info("Attempting to use GSHEET_SERVICE_ACCOUNT_JSON_CONTENT from environment variable.")
            creds_json = json.loads(gsa_json_content_str)
            # השתמש ב-google.oauth2.service_account.Credentials
            creds = Credentials.from_service_account_info(creds_json, scopes=scope)
        elif config.GSHEET_SERVICE_ACCOUNT_FILE_PATH and os.path.exists(config.GSHEET_SERVICE_ACCOUNT_FILE_PATH):
            logger.info(f"GSHEET_SERVICE_ACCOUNT_JSON_CONTENT not found, attempting to use GSHEET_SERVICE_ACCOUNT_FILE_PATH: {config.GSHEET_SERVICE_ACCOUNT_FILE_PATH}")
            # השתמש ב-google.oauth2.service_account.Credentials
            creds = Credentials.from_service_account_file(config.GSHEET_SERVICE_ACCOUNT_FILE_PATH, scopes=scope)
        else:
            logger.error("Google Sheets credentials not found. "
                           "Set GSHEET_SERVICE_ACCOUNT_JSON_CONTENT (Render) or GSHEET_SERVICE_ACCOUNT_FILE_PATH (local).")
            return None

        client = gspread.authorize(creds)
        if not config.GSHEET_SPREADSHEET_ID:
             logger.error("GSHEET_SPREADSHEET_ID is not configured.")
             return None
        spreadsheet = client.open_by_key(config.GSHEET_SPREADSHEET_ID)
        sheet = spreadsheet.worksheet(config.GSHEET_SHEET_NAME)
        
        # ודא שהכותרות קיימות
        current_headers = sheet.row_values(1) if sheet.row_count > 0 else []
        if not current_headers or any(h not in current_headers for h in EXPECTED_HEADERS[:3]): # בדוק רק כמה כותרות מרכזיות
            logger.warning(f"Sheet headers seem to be missing or incorrect. Expected something like: {EXPECTED_HEADERS}")
            # אפשר להוסיף כאן לוגיקה ליצירת כותרות אם הגיליון ריק לגמרי
            if sheet.row_count == 0:
                sheet.append_row(EXPECTED_HEADERS)
                logger.info("Appended headers to empty sheet.")

        _sheet_instance = sheet
        logger.info("Successfully connected to Google Sheet.")
        return _sheet_instance
    except FileNotFoundError as e_fnf:
        logger.error(f"Google Sheets credentials file (local fallback) not found: {e_fnf}")
        return None
    except json.JSONDecodeError as e_json:
        logger.error(f"Error decoding Google Sheets credentials JSON from environment variable: {e_json}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while connecting to Google Sheets: {e}", exc_info=True)
        return None

def find_user_row(sheet, user_id_to_find: int):
    if not sheet: return None
    try:
        user_id_str_to_find = str(user_id_to_find)
        headers = sheet.row_values(1)
        if COL_USER_ID not in headers:
            logger.error(f"Column '{COL_USER_ID}' not found in sheet header. Cannot find user.")
            return None
        user_id_col_index = headers.index(COL_USER_ID) + 1
        
        # נסה למצוא עם batch get כדי להיות יעיל יותר אם הגיליון גדול מאוד
        # אבל find פשוט יותר למימוש ראשוני
        cell = sheet.find(user_id_str_to_find, in_column=user_id_col_index)
        return cell.row
    except gspread.exceptions.CellNotFound:
        return None
    except Exception as e:
        logger.error(f"Error finding user {user_id_to_find} in sheet: {e}")
        return None

def get_user_data(user_id: int):
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

def add_new_user_for_disclaimer(user_id: int, username: str | None):
    sheet = get_sheet()
    if not sheet: return False
    
    effective_username = username or f"User_{user_id}"

    if find_user_row(sheet, user_id):
        logger.info(f"User {user_id} already exists. Updating disclaimer sent time.")
        # ודא שהסטטוס חוזר להיות pending_disclaimer אם הוא כבר אישר פעם ומתחיל מחדש
        return update_user_data(user_id, {
            COL_DISCLAIMER_SENT_TIME: datetime.datetime.now().isoformat(),
            COL_CONFIRMATION_STATUS: ConfirmationStatus.PENDING_DISCLAIMER.value
        })

    now_iso = datetime.datetime.now().isoformat()
    new_row_data_dict = {
        COL_USER_ID: str(user_id),
        COL_USERNAME: effective_username,
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
    
    current_headers = sheet.row_values(1) if sheet.row_count > 0 and sheet.row_values(1) else EXPECTED_HEADERS
    if not sheet.row_values(1): # אם השורה הראשונה ריקה (גיליון חדש לגמרי)
        try:
            sheet.append_row(EXPECTED_HEADERS)
            current_headers = EXPECTED_HEADERS
            logger.info("Appended headers to empty sheet.")
        except Exception as e:
            logger.error(f"Failed to append headers to empty sheet: {e}")
            return False
            
    new_row_values = [new_row_data_dict.get(header, '') for header in current_headers]

    try:
        sheet.append_row(new_row_values)
        logger.info(f"Added new user {user_id} ({effective_username}) for disclaimer.")
        return True
    except Exception as e:
        logger.error(f"Error appending new user row for {user_id}: {e}")
        return False

def update_user_data(user_id: int, updates: dict):
    sheet = get_sheet()
    if not sheet: return False
    row_num = find_user_row(sheet, user_id)
    if not row_num:
        logger.warning(f"Cannot update data, user {user_id} not found in GSheet.")
        return False

    updates[COL_LAST_UPDATE] = datetime.datetime.now().isoformat()
    
    cells_to_update = []
    try:
        headers = sheet.row_values(1)
        if not headers:
            logger.error("Cannot update cells: Sheet headers are missing.")
            return False

        for col_name, value in updates.items():
            try:
                col_index = headers.index(col_name) + 1
                cells_to_update.append(gspread.Cell(row_num, col_index, str(value) if value is not None else ''))
            except ValueError:
                logger.error(f"Column '{col_name}' not found in sheet header. Cannot update value: {value}")
            except Exception as e_cell:
                logger.error(f"Error preparing cell update for user {user_id}, column {col_name}: {e_cell}")
                return False # עצור אם יש שגיאה בהכנת אחד התאים
                
        if cells_to_update:
            sheet.update_cells(cells_to_update, value_input_option='USER_ENTERED')
            logger.info(f"Successfully updated GSheet data for user {user_id}. Updated fields: {list(updates.keys())}")
            return True
    except Exception as e_update:
        logger.error(f"Error bulk updating cells for user {user_id}: {e_update}", exc_info=True)
        return False
    return False

def update_user_email_and_confirmation(user_id: int, email: str, confirmation_status_enum: ConfirmationStatus):
    updates = {
        COL_EMAIL: email,
        COL_CONFIRMATION_STATUS: confirmation_status_enum.value
    }
    return update_user_data(user_id, updates)

def start_user_trial(user_id: int):
    now = datetime.datetime.now()
    trial_start_date_iso = now.isoformat()
    trial_end_date_iso = (now + datetime.timedelta(days=config.TRIAL_PERIOD_DAYS)).isoformat()
    updates = {
        COL_TRIAL_START_DATE: trial_start_date_iso,
        COL_TRIAL_END_DATE: trial_end_date_iso,
        COL_PAYMENT_STATUS: PaymentStatus.TRIAL.value,
        COL_CONFIRMATION_STATUS: ConfirmationStatus.CONFIRMED_DISCLAIMER.value # ודא שגם זה מתעדכן
    }
    return update_user_data(user_id, updates)

def update_user_disclaimer_status(user_id: int, status_enum: ConfirmationStatus, disclaimer_sent_time_iso=None):
    updates = {COL_CONFIRMATION_STATUS: status_enum.value}
    if disclaimer_sent_time_iso:
        updates[COL_DISCLAIMER_SENT_TIME] = disclaimer_sent_time_iso
    return update_user_data(user_id, updates)

def update_user_payment_status_from_gumroad(email: str, gumroad_sale_id: str, gumroad_subscription_id: str | None = None):
    sheet = get_sheet()
    if not sheet: return None

    try:
        headers = sheet.row_values(1)
        if COL_EMAIL not in headers or COL_USER_ID not in headers:
            logger.error(f"Required columns ('{COL_EMAIL}' or '{COL_USER_ID}') not found in sheet header.")
            return None
            
        email_col_index = headers.index(COL_EMAIL) + 1
        cell = sheet.find(email, in_column=email_col_index) # חפש לפי אימייל
        if not cell:
            logger.warning(f"User with email {email} not found for Gumroad sale {gumroad_sale_id}.")
            return None
        
        row_num = cell.row
        user_id_col_index = headers.index(COL_USER_ID) + 1
        telegram_user_id_str = sheet.cell(row_num, user_id_col_index).value
        if not telegram_user_id_str:
            logger.warning(f"Telegram user ID not found for user with email {email} at row {row_num}.")
            return None
        telegram_user_id = int(telegram_user_id_str)

    except gspread.exceptions.CellNotFound:
        logger.warning(f"User with email {email} not found for Gumroad sale {gumroad_sale_id}.")
        return None
    except ValueError as ve: # אם המרת ה-ID למספר נכשלת או index() נכשל
        logger.error(f"ValueError during Gumroad payment update for email {email}: {ve}")
        return None
    except Exception as e:
        logger.error(f"Error finding user by email {email} during Gumroad payment update: {e}", exc_info=True)
        return None

    updates = {
        COL_PAYMENT_STATUS: PaymentStatus.PAID_SUBSCRIBER.value,
        COL_GUMROAD_SALE_ID: str(gumroad_sale_id),
        COL_CONFIRMATION_STATUS: ConfirmationStatus.CONFIRMED_DISCLAIMER.value, # תשלום מאשר גם תנאים
        # אפשר לאפס תאריכי ניסיון אם רוצים
        # COL_TRIAL_START_DATE: '',
        # COL_TRIAL_END_DATE: '',
    }
    if gumroad_subscription_id:
        updates[COL_GUMROAD_SUBSCRIPTION_ID] = str(gumroad_subscription_id)
    
    if update_user_data(telegram_user_id, updates):
        logger.info(f"User {email} (TG ID: {telegram_user_id}) payment status updated from Gumroad sale {gumroad_sale_id}.")
        return telegram_user_id
    return None

def get_users_for_disclaimer_warning():
    sheet = get_sheet()
    if not sheet: return []
    users_to_warn = []
    try:
        all_users = sheet.get_all_records() # מחזיר רשימה של מילונים
        for user_data_dict in all_users:
            if user_data_dict.get(COL_CONFIRMATION_STATUS) == ConfirmationStatus.PENDING_DISCLAIMER.value:
                disclaimer_sent_time_str = user_data_dict.get(COL_DISCLAIMER_SENT_TIME)
                if disclaimer_sent_time_str and user_data_dict.get(COL_USER_ID): # ודא שיש user_id
                    try:
                        disclaimer_sent_time = datetime.datetime.fromisoformat(disclaimer_sent_time_str)
                        if datetime.datetime.now() > disclaimer_sent_time + datetime.timedelta(hours=config.REMINDER_MESSAGE_HOURS_BEFORE_WARNING):
                            users_to_warn.append(user_data_dict)
                    except ValueError:
                        logger.warning(f"Could not parse disclaimer_sent_time '{disclaimer_sent_time_str}' for user {user_data_dict.get(COL_USER_ID)}")
        return users_to_warn
    except Exception as e:
        logger.error(f"Error in get_users_for_disclaimer_warning: {e}", exc_info=True)
        return []

def get_users_for_trial_reminder_or_removal():
    sheet = get_sheet()
    if not sheet: return []
    users_to_process = []
    now = datetime.datetime.now()
    try:
        all_users = sheet.get_all_records()
        for user_data_dict in all_users:
            user_id_val = user_data_dict.get(COL_USER_ID)
            if not user_id_val: continue # דלג אם אין user_id

            payment_status_val = user_data_dict.get(COL_PAYMENT_STATUS)
            trial_end_date_str = user_data_dict.get(COL_TRIAL_END_DATE)

            if payment_status_val == PaymentStatus.TRIAL.value and trial_end_date_str:
                try:
                    trial_end_date = datetime.datetime.fromisoformat(trial_end_date_str)
                    # אם הניסיון הסתיים או מסתיים ב-24 שעות הקרובות
                    if now >= trial_end_date - datetime.timedelta(days=1): 
                        users_to_process.append({'action': 'send_trial_end_reminder', 'data': user_data_dict})
                except ValueError:
                    logger.warning(f"Could not parse trial_end_date '{trial_end_date_str}' for user {user_id_val}")
            
            elif payment_status_val == PaymentStatus.PENDING_PAYMENT_AFTER_TRIAL.value and trial_end_date_str:
                try:
                    trial_end_date = datetime.datetime.fromisoformat(trial_end_date_str)
                    # המתן יומיים אחרי סוף הניסיון המקורי לפני הסרה (סה"כ 3 ימים אחרי תזכורת)
                    if now >= trial_end_date + datetime.timedelta(days=config.HOURS_FOR_FINAL_CONFIRMATION_AFTER_WARNING / 24 + 1): # המר שעות לימים והוסף יום
                         users_to_process.append({'action': 'remove_user_no_payment', 'data': user_data_dict})
                except ValueError:
                     logger.warning(f"Could not parse trial_end_date '{trial_end_date_str}' for user {user_id_val} in PENDING_PAYMENT_AFTER_TRIAL state.")
        return users_to_process
    except Exception as e:
        logger.error(f"Error in get_users_for_trial_reminder_or_removal: {e}", exc_info=True)
        return []
