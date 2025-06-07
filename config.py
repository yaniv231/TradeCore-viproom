# config.py
import os
import logging

logger = logging.getLogger(__name__)

# === הגדרות טלגרם ===
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    error_message = "CRITICAL CONFIG ERROR: TELEGRAM_BOT_TOKEN environment variable is NOT SET or EMPTY in Render!"
    logger.critical(error_message)
    raise ValueError(error_message)

ADMIN_USER_ID_STR = os.environ.get('ADMIN_USER_ID', 'YOUR_ACTUAL_ADMIN_ID_HERE') # <<< שנה ל-ID האמיתי שלך, או הגדר כמשתנה סביבה
try:
    ADMIN_USER_ID = int(ADMIN_USER_ID_STR)
except ValueError:
    logger.error(f"CONFIG: ADMIN_USER_ID ('{ADMIN_USER_ID_STR}') is not a valid integer. Using 0.")
    ADMIN_USER_ID = 0

CHANNEL_ID = int(os.environ.get('CHANNEL_ID', '-100591679360'))
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME', "TradeCore VIP")

# === הגדרות Google Sheets ===
GSHEET_SERVICE_ACCOUNT_FILE_PATH = os.environ.get('GSHEET_SERVICE_ACCOUNT_FILE_PATH', 'credentials.json')
GSHEET_SPREADSHEET_ID = os.environ.get('GSHEET_SPREADSHEET_ID', '1KABh1HP7aa2KmvnUKZDpn8USsueJ_7_wVBjrP5DyFCw')
GSHEET_SHEET_NAME = os.environ.get('GSHEET_SHEET_NAME', 'Sheet1')

if not os.environ.get('GSHEET_SERVICE_ACCOUNT_JSON_CONTENT') and not os.path.exists(GSHEET_SERVICE_ACCOUNT_FILE_PATH):
    logger.warning("CONFIG: Neither GSHEET_SERVICE_ACCOUNT_JSON_CONTENT (for Render) nor a valid GSHEET_SERVICE_ACCOUNT_FILE_PATH (for local) is set. Google Sheets will likely fail.")

if not GSHEET_SPREADSHEET_ID:
    logger.warning("CONFIG: GSHEET_SPREADSHEET_ID environment variable is not set. Google Sheets integration will fail.")

# === הגדרות Gumroad ===
GUMROAD_PRODUCT_PERMALINK = os.environ.get('GUMROAD_PRODUCT_PERMALINK', 'YOUR_GUMROAD_PRODUCT_PERMALINK_HERE') # <<< שנה למזהה המוצר שלך!
if not GUMROAD_PRODUCT_PERMALINK or GUMROAD_PRODUCT_PERMALINK == 'YOUR_GUMROAD_PRODUCT_PERMALINK_HERE':
    logger.warning(f"CONFIG: GUMROAD_PRODUCT_PERMALINK is not properly set or is using a placeholder.")

# === הגדרות תשלום (להודעת תזכורת) ===
PAYPAL_ME_LINK = os.environ.get('PAYPAL_ME_LINK', 'https://www.paypal.me/ylevi376/120ILS')
PAYMENT_AMOUNT_ILS_STR = os.environ.get('PAYMENT_AMOUNT_ILS', '120')
try:
    PAYMENT_AMOUNT_ILS = int(PAYMENT_AMOUNT_ILS_STR)
except ValueError:
    PAYMENT_AMOUNT_ILS = 120

# === הגדרות כלליות לבוט ===
TRIAL_PERIOD_DAYS = 7
REMINDER_MESSAGE_HOURS_BEFORE_WARNING = 24
HOURS_FOR_FINAL_CONFIRMATION_AFTER_WARNING = int(os.environ.get('HOURS_FOR_FINAL_CONFIRMATION_AFTER_WARNING', '4'))

# === הגדרות תוכן אוטומטי ===
STOCK_SYMBOLS_LIST_STR = os.environ.get('STOCK_SYMBOLS_LIST', 'AAPL,MSFT,GOOGL,TSLA,AMZN')
STOCK_SYMBOLS_LIST = [symbol.strip() for symbol in STOCK_SYMBOLS_LIST_STR.split(',') if symbol.strip()]

POSTING_SCHEDULE_HOURS_START = int(os.environ.get('POSTING_SCHEDULE_HOURS_START', '10'))
POSTING_SCHEDULE_HOURS_END = int(os.environ.get('POSTING_SCHEDULE_HOURS_END', '22'))
MAX_POSTS_PER_DAY = int(os.environ.get('MAX_POSTS_PER_DAY', '10'))
