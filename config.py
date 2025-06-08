# הגדרות בסיסיות
TELEGRAM_BOT_TOKEN = "7592108692:AAFMyhtTSo-DD_dPakPIEDQdHz2xr_klzgk"
CHANNEL_ID = "@Stockcore_bot"
CHANNEL_USERNAME = "@TradeCore -vip room"
ADMIN_USER_ID = 591679360  # המזהה שלך

# הגדרות ניסיון ותשלום
TRIAL_PERIOD_DAYS = 7
PAYMENT_AMOUNT_ILS = 299
GUMROAD_PRODUCT_PERMALINK = "קישור למוצר בגמרוד"
REMINDER_MESSAGE_HOURS_BEFORE_WARNING = 24

# רשימת מניות לניתוח
STOCK_SYMBOLS_LIST = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA"]

# זמני פרסום תוכן אוטומטי
CONTENT_POSTING_TIMES = ["09:00", "12:00", "15:00", "18:00"]

# הגדרות גוגל שיטס (יובאו מקובץ אחר אם קיים)
try:
    from local_config import *
except ImportError:
    pass
