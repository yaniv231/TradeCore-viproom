# config.py
import os
import logging

logger = logging.getLogger(__name__)

# === הגדרות טלגרם ===
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    # זה יגרום לקריסה ברורה אם משתנה הסביבה לא מוגדר ב-Render
    # מה שעוזר לזהות את הבעיה מהר.
    error_message = "CRITICAL CONFIG ERROR: TELEGRAM_BOT_TOKEN environment variable is NOT SET or EMPTY in Render!"
    logger.critical(error_message)
    raise ValueError(error_message)

# השתמש בערכים שסיפקת כברירת מחדל, אך תן עדיפות למשתני סביבה אם קיימים
ADMIN_USER_ID_STR = os.environ.get('ADMIN_USER_ID', 'YOUR_ACTUAL_ADMIN_ID_HERE') # <<< שנה ל-ID האמיתי שלך, או הגדר כמשתנה סביבה
try:
    ADMIN_USER_ID = int(ADMIN_USER_ID_STR)
    if ADMIN_USER_ID == 0 and ADMIN_USER_ID_STR != '0': # אם ברירת המחדל היא לא '0' וההתקנה נכשלה
         logger.warning(f"CONFIG: ADMIN_USER_ID was '{ADMIN_USER_ID_STR}', failed to parse as int. Using 0. Admin commands might fail.")
         ADMIN_USER_ID = 0
    elif ADMIN_USER_ID == 0:
         logger.warning("CONFIG: ADMIN_USER_ID is 0 (default or set). Admin commands might not function as expected.")

except ValueError:
    logger.error(f"CONFIG: ADMIN_USER_ID ('{ADMIN_USER_ID_STR}') is not a valid integer. Using 0.")
    ADMIN_USER_ID = 0

CHANNEL_ID = int(os.environ.get('CHANNEL_ID', '-100591679360')) # מזהה הערוץ שלך
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME', "TradeCore VIP") # שם תצוגה לערוץ

# === הגדרות Google Sheets ===
GSHEET_SERVICE_ACCOUNT_FILE_PATH = os.environ.get('GSHEET_SERVICE_ACCOUNT_FILE_PATH', 'credentials.json') # לפיתוח מקומי
GSHEET_SPREADSHEET_ID = os.environ.get('GSHEET_SPREADSHEET_ID', '1KABh1HP7aa2KmvnUKZDpn8USsueJ_7_wVBjrP5DyFCw') # מזהה הגיליון שלך
GSHEET_SHEET_NAME = os.environ.get('GSHEET_SHEET_NAME', 'Sheet1')

if not os.environ.get('GSHEET_SERVICE_ACCOUNT_JSON_CONTENT') and \
   not (GSHEET_SERVICE_ACCOUNT_FILE_PATH and os.path.exists(GSHEET_SERVICE_ACCOUNT_FILE_PATH)):
    logger.warning("CONFIG: Neither GSHEET_SERVICE_ACCOUNT_JSON_CONTENT (for Render) nor a valid GSHEET_SERVICE_ACCOUNT_FILE_PATH (for local) is set. Google Sheets will fail.")

if not GSHEET_SPREADSHEET_ID:
    logger.warning("CONFIG: GSHEET_SPREADSHEET_ID environment variable is not set. Google Sheets integration will fail.")

# === הגדרות Gumroad ===
GUMROAD_PRODUCT_PERMALINK = os.environ.get('GUMROAD_PRODUCT_PERMALINK', 'YOUR_GUMROAD_PRODUCT_PERMALINK_HERE') # <<< שנה למזהה המוצר שלך!
if not GUMROAD_PRODUCT_PERMALINK or GUMROAD_PRODUCT_PERMALINK == 'YOUR_GUMROAD_PRODUCT_PERMALINK_HERE':
    logger.warning(f"CONFIG: GUMROAD_PRODUCT_PERMALINK is not properly set or is using a placeholder: '{GUMROAD_PRODUCT_PERMALINK}'")
GUMROAD_WEBHOOK_SECRET = os.environ.get('GUMROAD_WEBHOOK_SECRET', '')

# === הגדרות תשלום (להודעת תזכורת) ===
PAYPAL_ME_LINK = os.environ.get('PAYPAL_ME_LINK', 'https://www.paypal.me/ylevi376/120ILS') # הקישור שלך
PAYMENT_AMOUNT_ILS_STR = os.environ.get('PAYMENT_AMOUNT_ILS', '120')
try:
    PAYMENT_AMOUNT_ILS = int(PAYMENT_AMOUNT_ILS_STR)
except ValueError:
    logger.error(f"CONFIG: PAYMENT_AMOUNT_ILS ('{PAYMENT_AMOUNT_ILS_STR}') is not a valid integer. Using 120.")
    PAYMENT_AMOUNT_ILS = 120

# === הגדרות כלליות לבוט ===
TRIAL_PERIOD_DAYS = 7
REMINDER_MESSAGE_HOURS_BEFORE_WARNING = 24
HOURS_FOR_FINAL_CONFIRMATION_AFTER_WARNING = int(os.environ.get('HOURS_FOR_FINAL_CONFIRMATION_AFTER_WARNING', '4'))

# === הגדרות תוכן אוטומטי ===
STOCK_SYMBOLS_LIST_STR = os.environ.get('STOCK_SYMBOLS_LIST', 'AAPL,MSFT,GOOGL,TSLA,AMZN')
STOCK_SYMBOLS_LIST = [symbol.strip() for symbol in STOCK_SYMBOLS_LIST_STR.split(',') if symbol.strip()]
if not STOCK_SYMBOLS_LIST:
    logger.warning("CONFIG: STOCK_SYMBOLS_LIST is empty. No scheduled content will be posted.")

POSTING_SCHEDULE_HOURS_START = int(os.environ.get('POSTING_SCHEDULE_HOURS_START', '10'))
POSTING_SCHEDULE_HOURS_END = int(os.environ.get('POSTING_SCHEDULE_HOURS_END', '22'))
MAX_POSTS_PER_DAY = int(os.environ.get('MAX_POSTS_PER_DAY', '10'))

# === הגדרות שרת Webhook (Flask) & Render ===
WEBHOOK_LISTEN_HOST = '0.0.0.0'
WEBHOOK_PORT = int(os.environ.get('PORT', '10000'))

TEMP_GRAPH_PATH = 'temp_graph.png'

logger.info(f"--- CONFIGURATION LOADED ---")
logger.info(f"ADMIN_USER_ID: {ADMIN_USER_ID}")
logger.info(f"CHANNEL_ID: {CHANNEL_ID}")
logger.info(f"GSHEET_SPREADSHEET_ID: {GSHEET_SPREADSHEET_ID}")
logger.info(f"GUMROAD_PRODUCT_PERMALINK: {GUMROAD_PRODUCT_PERMALINK}")
logger.info(f"--- END CONFIGURATION ---")
