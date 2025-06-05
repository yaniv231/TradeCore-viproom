# config.py
import os
import logging

logger = logging.getLogger(__name__)

# === הגדרות טלגרם ===
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    logger.critical("CRITICAL: TELEGRAM_BOT_TOKEN environment variable is not set in Render!")
    # מומלץ לגרום לקריסה אם הטוקן לא מוגדר בסביבת פרודקשן
    # raise ValueError("CRITICAL: TELEGRAM_BOT_TOKEN environment variable not set!")

ADMIN_USER_ID_STR = os.environ.get('ADMIN_USER_ID', 591679360) # <<< שנה ל-ID שלך!
try:
    ADMIN_USER_ID = int(ADMIN_USER_ID_STR)
except ValueError:
    logger.error(f"ADMIN_USER_ID ('{ADMIN_USER_ID_STR}') is not a valid integer. Using 0 (admin commands may fail).")
    ADMIN_USER_ID = 0

CHANNEL_ID = int(os.environ.get('CHANNEL_ID', '-100591679360')) # מזהה הערוץ שסיפקת
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME', "@TradeCoreVIP") # שם תצוגה לערוץ (אם יש)

# === הגדרות Google Sheets ===
# עדיפות לתוכן ה-JSON ממשתנה סביבה GSHEET_SERVICE_ACCOUNT_JSON_CONTENT ב-Render
# GSHEET_SERVICE_ACCOUNT_FILE_PATH ישמש רק אם הראשון לא קיים (לפיתוח מקומי)
GSHEET_SERVICE_ACCOUNT_FILE_PATH = os.environ.get('GSHEET_SERVICE_ACCOUNT_FILE_PATH', 'credentials.json') # שם קובץ ברירת מחדל לפיתוח מקומי
GSHEET_SPREADSHEET_ID = os.environ.get('GSHEET_SPREADSHEET_ID', '1KABh1HP7aa2KmvnUKZDpn8USsueJ_7_wVBjrP5DyFCw') # מזהה הגיליון שסיפקת
if not GSHEET_SPREADSHEET_ID:
    logger.warning("GSHEET_SPREADSHEET_ID environment variable is not set. Google Sheets integration will fail.")
GSHEET_SHEET_NAME = os.environ.get('GSHEET_SHEET_NAME', 'Sheet1')
# === הגדרות Gumroad ===
GUMROAD_PRODUCT_PERMALINK = os.environ.get('GUMROAD_PRODUCT_PERMALINK', 'irexdq') # <<< תקין תחבירית
if not GUMROAD_PRODUCT_PERMALINK:
    logger.critical("CRITICAL: GUMROAD_PRODUCT_PERMALINK environment variable is not set in Render!")
    # raise ValueError("CRITICAL: GUMROAD_PRODUCT_PERMALINK environment variable not set!")
else:
    logger.info(f"GUMROAD_PRODUCT_PERMALINK loaded from environment: {GUMROAD_PRODUCT_PERMALINK}")

# === הגדרות תשלום (למשל, להודעת תזכורת) ===
PAYPAL_ME_LINK = os.environ.get('PAYPAL_ME_LINK', 'https://www.paypal.me/ylevi376/120ILS') # תקין תחבירית
PAYMENT_AMOUNT_ILS_STR = os.environ.get('PAYMENT_AMOUNT_ILS', '120')
try:
    PAYMENT_AMOUNT_ILS = int(PAYMENT_AMOUNT_ILS_STR)
except ValueError:
    logger.error(f"PAYMENT_AMOUNT_ILS ('{PAYMENT_AMOUNT_ILS_STR}') is not a valid integer. Using 120.")
    PAYMENT_AMOUNT_ILS = 120


# === הגדרות כלליות לבוט ===
TRIAL_PERIOD_DAYS = 7
REMINDER_MESSAGE_HOURS_BEFORE_WARNING = 24
HOURS_FOR_FINAL_CONFIRMATION_AFTER_WARNING = 4 # שעות להמתנה אחרי אזהרה אחרונה לאישור תנאים

# === הגדרות תוכן אוטומטי ===
STOCK_SYMBOLS_LIST_STR = os.environ.get('STOCK_SYMBOLS_LIST', 'AAPL,MSFT,GOOGL,TSLA,AMZN')
STOCK_SYMBOLS_LIST = [symbol.strip() for symbol in STOCK_SYMBOLS_LIST_STR.split(',') if symbol.strip()]

POSTING_SCHEDULE_HOURS_START = int(os.environ.get('POSTING_SCHEDULE_HOURS_START', '10'))
POSTING_SCHEDULE_HOURS_END = int(os.environ.get('POSTING_SCHEDULE_HOURS_END', '22')) # עד שעה זו (לא כולל)
MAX_POSTS_PER_DAY = int(os.environ.get('MAX_POSTS_PER_DAY', '10'))

# === הגדרות שרת Webhook (Flask) ===
WEBHOOK_LISTEN_HOST = '0.0.0.0'
WEBHOOK_PORT = int(os.environ.get('PORT', '10000')) # Render מספק את PORT, ברירת מחדל ל-10000 כפי שנצפה בלוגים

TEMP_GRAPH_PATH = 'temp_graph.png'

# הדפסת לוג לבדיקה שהערכים נטענו
logger.info(f"Config loaded: TELEGRAM_BOT_TOKEN is {'SET (from env)' if TELEGRAM_BOT_TOKEN else 'NOT SET (critical error if in production)'}")
logger.info(f"Config loaded: ADMIN_USER_ID = {ADMIN_USER_ID}")
logger.info(f"Config loaded: CHANNEL_ID = {CHANNEL_ID}")
logger.info(f"Config loaded: GSHEET_SPREADSHEET_ID = {GSHEET_SPREADSHEET_ID}")
logger.info(f"Config loaded: GUMROAD_PRODUCT_PERMALINK = {GUMROAD_PRODUCT_PERMALINK}")
