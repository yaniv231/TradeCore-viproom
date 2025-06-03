# config.py
import os
import logging # הוספת לוגינג לבדיקות

logger = logging.getLogger(__name__)

# === הגדרות טלגרם ===
TELEGRAM_BOT_TOKEN = os.environ.get(7811056626:AAF7BgT637Ari9HN7jgyK8qBeNHTcQtXfR0)
if not TELEGRAM_BOT_TOKEN:
    logger.critical("CRITICAL: TELEGRAM_BOT_TOKEN environment variable is not set!")
    # ברוב המקרים נרצה שהאפליקציה תיכשל כאן אם הטוקן חסר.
    # אפשר להוסיף raise ValueError("CRITICAL: TELEGRAM_BOT_TOKEN environment variable not set!")
    # אך לצורך הפריסה הראשונית, נסתפק בלוג קריטי. ודא שהגדרת אותו ב-Render!

ADMIN_USER_ID_STR = os.environ.get('ADMIN_USER_ID', '0') # קרא כסטרינג
try:
    ADMIN_USER_ID = int(ADMIN_USER_ID_STR)
    if ADMIN_USER_ID == 0:
        logger.warning("ADMIN_USER_ID is not set or set to 0. Admin commands might not work as expected.")
except ValueError:
    logger.error(f"ADMIN_USER_ID ('{ADMIN_USER_ID_STR}') is not a valid integer. Using 0.")
    ADMIN_USER_ID = 0

CHANNEL_ID_STR = os.environ.get('CHANNEL_ID', '-100591679360') # ערך שסיפקת
try:
    CHANNEL_ID = int(CHANNEL_ID_STR)
except ValueError:
    logger.error(f"CHANNEL_ID ('{CHANNEL_ID_STR}') is not a valid integer. Using 0 as fallback (will likely fail).")
    CHANNEL_ID = 0 # זה כנראה יגרום לשגיאות אם לא תקין

CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME', "@TradeCoreVIP") # הערך שהצעת

# === הגדרות Google Sheets ===
# עדיפות לתוכן ה-JSON ממשתנה סביבה GSHEET_SERVICE_ACCOUNT_JSON_CONTENT
# GSHEET_SERVICE_ACCOUNT_FILE ישמש רק אם הראשון לא קיים (לפיתוח מקומי)
GSHEET_SERVICE_ACCOUNT_FILE = os.environ.get('GSHEET_SERVICE_ACCOUNT_FILE_PATH') # נתיב לקובץ בפיתוח מקומי
GSHEET_SPREADSHEET_ID = os.environ.get('GSHEET_SPREADSHEET_ID')
if not GSHEET_SPREADSHEET_ID:
    logger.warning("GSHEET_SPREADSHEET_ID environment variable is not set. Google Sheets integration will fail.")

GSHEET_SHEET_NAME = os.environ.get('GSHEET_SHEET_NAME', 'Sheet1')

# === הגדרות Gumroad ===
GUMROAD_PRODUCT_PERMALINK = os.environ.get('GUMROAD_PRODUCT_PERMALINK')
if not GUMROAD_PRODUCT_PERMALINK:
    logger.warning("GUMROAD_PRODUCT_PERMALINK environment variable is not set. Gumroad integration will be affected.")

GUMROAD_WEBHOOK_SECRET = os.environ.get('GUMROAD_WEBHOOK_SECRET', '') # השאר ריק אם אין Secret ספציפי מ-Gumroad

# === הגדרות תשלום (למשל, להודעת תזכורת) ===
PAYPAL_ME_LINK = os.environ.get('PAYPAL_ME_LINK', 'https://www.paypal.me/ylevi376/120ILS') # ערך שסיפקת
PAYMENT_AMOUNT_ILS_STR = os.environ.get('PAYMENT_AMOUNT_ILS', '120')
try:
    PAYMENT_AMOUNT_ILS = int(PAYMENT_AMOUNT_ILS_STR)
except ValueError:
    logger.error(f"PAYMENT_AMOUNT_ILS ('{PAYMENT_AMOUNT_ILS_STR}') is not a valid integer. Using 120.")
    PAYMENT_AMOUNT_ILS = 120

# === הגדרות כלליות לבוט ===
TRIAL_PERIOD_DAYS = 7
REMINDER_MESSAGE_HOURS_BEFORE_WARNING = 24
HOURS_FOR_FINAL_CONFIRMATION_AFTER_WARNING = 4

# === הגדרות תוכן אוטומטי ===
STOCK_SYMBOLS_LIST_STR = os.environ.get('STOCK_SYMBOLS_LIST', 'AAPL,MSFT,GOOGL,TSLA,AMZN')
STOCK_SYMBOLS_LIST = [symbol.strip() for symbol in STOCK_SYMBOLS_LIST_STR.split(',') if symbol.strip()]

POSTING_SCHEDULE_HOURS_START = int(os.environ.get('POSTING_SCHEDULE_HOURS_START', '10'))
POSTING_SCHEDULE_HOURS_END = int(os.environ.get('POSTING_SCHEDULE_HOURS_END', '22'))
MAX_POSTS_PER_DAY = int(os.environ.get('MAX_POSTS_PER_DAY', '10'))

# === הגדרות שרת Webhook (Flask) ===
WEBHOOK_LISTEN_HOST = '0.0.0.0'
# Render מספק את הפורט דרך משתנה סביבה PORT. אם לא, נשתמש בברירת מחדל (למשל, לפיתוח מקומי).
WEBHOOK_PORT = int(os.environ.get('PORT', '8080')) # Gunicorn ישתמש ב-$PORT מ-render.yaml

TEMP_GRAPH_PATH = 'temp_graph.png' # נתיב לקובץ גרף זמני אם צריך (עדיף להשתמש ב-BytesIO)

# הדפסת לוג לבדיקה שהערכים נטענו (יופיע בלוגים של Render בהתחלה)
logger.info(f"Config loaded: TELEGRAM_BOT_TOKEN is {'SET' if TELEGRAM_BOT_TOKEN else 'NOT SET'}")
logger.info(f"Config loaded: ADMIN_USER_ID = {ADMIN_USER_ID}")
logger.info(f"Config loaded: CHANNEL_ID = {CHANNEL_ID}")
logger.info(f"Config loaded: GSHEET_SPREADSHEET_ID is {'SET' if GSHEET_SPREADSHEET_ID else 'NOT SET'}")
logger.info(f"Config loaded: GUMROAD_PRODUCT_PERMALINK is {'SET' if GUMROAD_PRODUCT_PERMALINK else 'NOT SET'}")
