import asyncio
import threading
from bot import PeakTradeBot
from webhook_server import app
import os

def run_flask_app():
    """הרצת שרת Flask ברקע"""
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)

def run_bot():
    """הרצת הבוט"""
    bot = PeakTradeBot()
    asyncio.run(bot.run())

if __name__ == "__main__":
    # הפעלת שרת Flask בthread נפרד
    flask_thread = threading.Thread(target=run_flask_app)
    flask_thread.daemon = True
    flask_thread.start()
    
    # הפעלת הבוט בthread הראשי
    run_bot()
