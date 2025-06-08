from flask import Flask, request, jsonify
import os
import json
import gspread
from google.oauth2.service_account import Credentials
import logging
from datetime import datetime
import asyncio
from telegram import Bot

# הגדרת לוגינג
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# הגדרות עם הפרטים החדשים שלך
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or "7619055199:AAEL28DJ-E1Xl7iEfdPqTXJ0in1Lps0VOtM"
GOOGLE_CREDENTIALS = os.getenv('GOOGLE_CREDENTIALS')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
GUMROAD_WEBHOOK_SECRET = os.getenv('GUMROAD_WEBHOOK_SECRET')

# חיבור ל-Google Sheets
google_client = None
sheet = None

def setup_google_sheets():
    global google_client, sheet
    try:
        if GOOGLE_CREDENTIALS:
            creds_dict = json.loads(GOOGLE_CREDENTIALS)
            scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
            google_client = gspread.authorize(creds)
            sheet = google_client.open_by_key(SPREADSHEET_ID).sheet1
            logger.info("✅ Google Sheets connected")
    except Exception as e:
        logger.error(f"❌ Error setting up Google Sheets: {e}")

setup_google_sheets()

@app.route('/webhook/gumroad', methods=['POST'])
def gumroad_webhook():
    """קבלת Webhook מ-Gumroad לאימות תשלום"""
    try:
        data = request.get_json()
        
        # חילוץ נתונים
        sale_id = data.get('sale_id')
        email = data.get('email')
        product_name = data.get('product_name')
        
        logger.info(f"Received Gumroad webhook: {sale_id}, {email}")
        
        # עדכון Google Sheets
        if sheet and email:
            records = sheet.get_all_records()
            
            for i, record in enumerate(records):
                if record.get('email') == email:
                    row_index = i + 2
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # עדכון סטטוס תשלום
                    sheet.update_cell(row_index, 8, "paid_subscriber")  # payment_status
                    sheet.update_cell(row_index, 9, sale_id)  # gumroad_sale_id
                    sheet.update_cell(row_index, 11, current_time)  # last_update_timestamp
                    
                    # שליחת הודעת אישור למשתמש
                    user_id = record.get('telegram_user_id')
                    if user_id:
                        asyncio.create_task(send_payment_confirmation(user_id))
                    
                    logger.info(f"✅ Payment confirmed for {email}")
                    break
        
        return jsonify({'status': 'success'}), 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return jsonify({'error': 'Internal error'}), 500

async def send_payment_confirmation(user_id):
    """שליחת הודעת אישור תשלום"""
    try:
        bot = Bot(token=BOT_TOKEN)
        
        confirmation_message = """
✅ *תשלום אושר בהצלחה!*

🎉 ברוך הבא כמנוי קבוע ב-PeakTrade VIP!

💎 *המנוי שלך כולל:*
• גישה מלאה לכל התוכן הפרמיום
• ניתוחים טכניים יומיים
• גרפי נרות בזמן אמת
• רעיונות מסחר מקצועיים
• תמיכה אישית

🔄 *המנוי שלך מתחדש אוטומטית*

*תודה שהצטרפת למשפחת PeakTrade VIP! 🚀*
        """
        
        await bot.send_message(
            chat_id=user_id,
            text=confirmation_message,
            parse_mode='Markdown'
        )
        
        logger.info(f"✅ Payment confirmation sent to {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Error sending confirmation to {user_id}: {e}")

@app.route('/health', methods=['GET'])
def health_check():
    """בדיקת תקינות השרת"""
    return jsonify({'status': 'healthy', 'bot': 'PeakTrade VIP'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
