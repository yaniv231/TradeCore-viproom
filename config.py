# config.py
import os # הוסף בראש הקובץ אם עדיין אין
# === הגדרות טלגרם ===
TELEGRAM_BOT_TOKEN = os.environ.get(('7811056626:AAF7BgT637Ari9HN7jgyK8qBeNHTcQtXfR0')
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set!")

ADMIN_USER_ID = 123456789  # החלף ב-ID שלך בטלגרם (לפקודות ניהול)
CHANNEL_ID = -100591679360 # מזהה הערוץ הפרטי שלך (כפי שסיפקת)
CHANNEL_USERNAME = "@TradeCoreVIP" # (אופציונלי) שם המשתמש של הערוץ אם יש, לשימוש בהודעות

# === הגדרות Google Sheets ===
GSHEET_SERVICE_ACCOUNT_FILE = 'path/to/your/google-service-account-credentials.json' # נתיב לקובץ ה-JSON (יוגדר כמשתנה סביבה ב-Render, או שהתוכן שלו יועבר)
GSHEET_SPREADSHEET_ID = '1KABh1HP7aa2KmvnUKZDpn8USsueJ_7_wVBjrP5DyFCw' # מזהה הגיליון שלך
GSHEET_SHEET_NAME = 'Sheet1' # שם הגיליון הספציפי בתוך ה-Spreadsheet

# === הגדרות Gumroad ===
GUMROAD_PRODUCT_PERMALINK = 'your_gumroad_product_permalink' # הקישור הקבוע למוצר שלך ב-Gumroad (למשל, xyz12)
GUMROAD_WEBHOOK_SECRET = 'your_gumroad_webhook_secret_if_any' # אם גאמרוד מספקים Secret לאימות ה-Webhook

# === הגדרות תשלום (למשל, להודעת תזכורת) ===
PAYPAL_ME_LINK = 'https://www.paypal.me/ylevi376/120ILS' # שים לב ששיניתי ל-ILS, התאם אם צריך מטבע אחר
PAYMENT_AMOUNT_ILS = 120

# === הגדרות כלליות לבוט ===
TRIAL_PERIOD_DAYS = 7
REMINDER_MESSAGE_HOURS_BEFORE_WARNING = 24 # כמה שעות לפני שליחת אזהרה אחרונה לאישור תנאים
HOURS_FOR_FINAL_CONFIRMATION_AFTER_WARNING = 4 # כמה שעות לתת לאישור אחרי האזהרה האחרונה לפני ביטול אוטומטי

# === הגדרות תוכן אוטומטי ===
STOCK_SYMBOLS_LIST = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'AMZN'] # רשימת מניות לבחירה רנדומלית
POSTING_SCHEDULE_HOURS_START = 10 # שעת התחלה לשליחת פוסטים (0-23)
POSTING_SCHEDULE_HOURS_END = 22   # שעת סיום לשליחת פוסטים (0-23)
MAX_POSTS_PER_DAY = 10

# === הגדרות שרת Webhook (Flask) ===
WEBHOOK_LISTEN_HOST = '0.0.0.0' # להאזנה על כל הממשקים (חשוב ל-Render)
WEBHOOK_PORT = 8080 # הפורט ש-Render מצפה שהאפליקציה תאזין לו (או שיוגדר אוטומטית על ידי Render)

# === נתיבים (אם רלוונטי לאחסון מקומי זמני) ===
TEMP_GRAPH_PATH = 'temp_graph.png'
