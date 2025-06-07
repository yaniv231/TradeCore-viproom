# g_sheets.py
import gspread
from google.oauth2.service_account import Credentials
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
        return _sheet_instance

    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        gsa_json_content_str = os.environ.get('GSHEET_SERVICE_ACCOUNT_JSON_CONTENT')
        
        if gsa_json_content_str:
            logger.info("Attempting to use GSHEET_SERVICE_ACCOUNT_JSON_CONTENT from environment variable.")
            creds_json = json.loads(gsa_json_content_str)
            creds = Credentials.from_service_account_info(creds_json, scopes=scope)
        elif config.GSHEET_SERVICE_ACCOUNT_FILE_PATH and os.path.exists(config.GSHEET_SERVICE_ACCOUNT_FILE_PATH):
            logger.info(f"Using local credentials file: {config.GSHEET_SERVICE_ACCOUNT_FILE_PATH}")
            creds = Credentials.from_service_account_file(config.GSHEET_SERVICE_ACCOUNT_FILE_PATH, scopes=scope)
        else:
            logger.error("Google Sheets credentials not found. Set GSHEET_SERVICE_ACCOUNT_JSON_CONTENT (Render) or GSHEET_SERVICE_ACCOUNT_FILE_PATH (local).")
            return None

        client = gspread.authorize(creds)
        if not config.GSHEET_SPREADSHEET_ID:
            logger.error("GSHEET_SPREADSHEET_ID is not configured.")
            return None
        spreadsheet = client.open_by_key(config.GSHEET_SPREADSHEET_ID)
        sheet = spreadsheet.worksheet(config.GSHEET_SHEET_NAME)
        
        if sheet.row_count == 0:
            sheet.append_row(EXPECTED_HEADERS)
            logger.info(f"Appended headers to empty sheet '{config.GSHEET_SHEET_NAME}'.")
        
        _sheet_instance = sheet
        logger.info("Successfully connected to Google Sheet.")
        return _sheet_instance
    except Exception as e:
        logger.error(f"An error occurred while connecting to Google Sheets: {e}", exc_info=True)
        return None

# ... (כל שאר הפונקציות מ-`g_sheets.py` כפי שהיו בגרסה האחרונה - #60)
# לדוגמה, find_user_row, get_user_data, add_new_user_for_disclaimer, וכו'.

def find_user_row(sheet, user_id_to_find: int):
    # ...
    pass
# וכן הלאה...
