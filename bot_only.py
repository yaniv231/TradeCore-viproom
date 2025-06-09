import logging
import os
import asyncio
import json
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.error import TelegramError
import gspread
from google.oauth2.service_account import Credentials
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import yfinance as yf
import mplfinance as mpf
import matplotlib.pyplot as plt
import io
import random
import contextlib
import uvicorn
from asgiref.wsgi import WsgiToAsgi
from flask import Flask, request, jsonify

# הגדרת לוגינג
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# הגדרות המערכת
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or "7619055199:AAEL28DJ-E1Xl7iEfdPqTXJ0in1Lps0VOtM"
CHANNEL_ID = os.getenv('CHANNEL_ID') or "-1002886874719"
GOOGLE_CREDENTIALS = os.getenv('GOOGLE_CREDENTIALS')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')

# מצבי השיחה
WAITING_FOR_EMAIL = 1

class PeakTradeBot:
    def __init__(self):
        self.application = None
        self.scheduler = None
        self.google_client = None
        self.sheet = None
        self.setup_google_sheets()
        
    def setup_google_sheets(self):
        """הגדרת חיבור ל-Google Sheets"""
        try:
            if GOOGLE_CREDENTIALS:
                creds_dict = json.loads(GOOGLE_CREDENTIALS)
                scope = [
                    'https://spreadsheets.google.com/feeds',
                    'https://www.googleapis.com/auth/drive'
                ]
                creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
                self.google_client = gspread.authorize(creds)
                self.sheet = self.google_client.open_by_key(SPREADSHEET_ID).sheet1
                
                try:
                    headers = self.sheet.row_values(1)
                    if not headers:
                        header_row = [
                            'telegram_user_id', 'telegram_username', 'email', 
                            'disclaimer_sent_time', 'confirmation_status', 
                            'trial_start_date', 'trial_end_date', 'payment_status',
                            'gumroad_sale_id', 'gumroad_subscription_id', 'last_update_timestamp'
                        ]
                        self.sheet.append_row(header_row)
                        logger.info("✅ Headers added to Google Sheets")
                except Exception as e:
                    logger.error(f"❌ Error checking headers: {e}")
                
                logger.info("✅ Google Sheets connected successfully")
            else:
                logger.warning("⚠️ Google Sheets credentials not found")
        except Exception as e:
            logger.error(f"❌ Error setting up Google Sheets: {e}")

    def check_user_exists(self, user_id):
        """בדיקה אם משתמש כבר קיים ב-Google Sheets"""
        try:
            if not self.sheet:
                return False
            
            records = self.sheet.get_all_records()
            for record in records:
                if str(record.get('telegram_user_id')) == str(user_id):
                    status = record.get('payment_status', '')
                    if status in ['trial_active', 'paid_subscriber']:
                        return True
            return False
        except Exception as e:
            logger.error(f"❌ Error checking user existence: {e}")
            return False

    def get_mixed_stock_recommendations(self):
        """קבלת המלצות מניות מעורבות - אמריקאיות וישראליות"""
        try:
            us_symbols = [
                'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META', 'NFLX', 
                'AMD', 'INTC', 'IBM', 'CSCO', 'ORCL', 'CRM', 'ADBE', 'PYPL',
                'UBER', 'LYFT', 'SPOT', 'ZOOM', 'SHOP', 'SQ', 'ROKU',
                'SNAP', 'PINS', 'DOCU', 'ZM', 'PLTR', 'COIN', 'RBLX', 'HOOD'
            ]
            
            israeli_nasdaq_symbols = [
                'CHKP', 'CYBR', 'NICE', 'MNDY', 'WIX', 'FVRR', 'TEVA',
                'CELG', 'PLTK', 'SSYS', 'NNDM', 'RDWR', 'MGIC', 'GILT',
                'ELBM', 'OPRX', 'KRNT', 'INMD', 'SMWB', 'SPNS'
            ]
            
            israeli_ta_symbols = [
                'TEVA.TA', 'ICL.TA', 'BANK.TA', 'LUMI.TA', 'ELCO.TA',
                'AZRM.TA', 'DORL.TA', 'ISCN.TA', 'ALHE.TA', 'MZTF.TA'
            ]
            
            all_symbols = us_symbols + israeli_nasdaq_symbols + israeli_ta_symbols
            recommendations = []
            
            for symbol in all_symbols:
                try:
                    stock = yf.Ticker(symbol)
                    hist = stock.history(period='2d')
                    
                    if hist.empty or len(hist) < 2:
                        continue
                    
                    close_today = hist['Close'][-1]
                    close_yesterday = hist['Close'][-2]
                    change_percent = ((close_today - close_yesterday) / close_yesterday) * 100
                    
                    if abs(change_percent) > 1.5:
                        if symbol in israeli_nasdaq_symbols:
                            stock_type = "🇮🇱 ישראלית (נאסד\"ק)"
                        elif symbol.endswith('.TA'):
                            stock_type = "🇮🇱 ישראלית (ת\"א)"
                        else:
                            stock_type = "🇺🇸 אמריקאית"
                            
                        recommendations.append({
                            'symbol': symbol,
                            'change_percent': change_percent,
                            'current_price': close_today,
                            'stock_type': stock_type
                        })
                        
                except Exception as e:
                    logger.error(f"Error processing {symbol}: {e}")
                    continue
            
            recommendations.sort(key=lambda x: abs(x['change_percent']), reverse=True)
            return recommendations[:12]
            
        except Exception as e:
            logger.error(f"❌ Error getting mixed stock recommendations: {e}")
            return [
                {'symbol': 'AAPL', 'change_percent': 0, 'current_price': 150, 'stock_type': '🇺🇸 אמריקאית'},
                {'symbol': 'CHKP', 'change_percent': 0, 'current_price': 120, 'stock_type': '🇮🇱 ישראלית (נאסד"ק)'},
                {'symbol': 'TEVA.TA', 'change_percent': 0, 'current_price': 50, 'stock_type': '🇮🇱 ישראלית (ת"א)'}
            ]

    def get_crypto_recommendations(self):
        """קבלת המלצות קריפטו מובילות"""
        try:
            crypto_symbols = [
                'BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'BNB-USD',
                'ADA-USD', 'DOGE-USD', 'TRX-USD', 'AVAX-USD', 'DOT-USD',
                'MATIC-USD', 'LINK-USD'
            ]
            
            recommendations = []
            
            for symbol in crypto_symbols:
                try:
                    crypto = yf.Ticker(symbol)
                    hist = crypto.history(period='2d')
                    
                    if hist.empty or len(hist) < 2:
                        continue
                    
                    close_today = hist['Close'][-1]
                    close_yesterday = hist['Close'][-2]
                    change_percent = ((close_today - close_yesterday) / close_yesterday) * 100
                    
                    if abs(change_percent) > 2:
                        recommendations.append({
                            'symbol': symbol,
                            'change_percent': change_percent,
                            'current_price': close_today,
                            'crypto_type': '🪙 קריפטו'
                        })
                        
                except Exception as e:
                    logger.error(f"Error processing crypto {symbol}: {e}")
                    continue
            
            recommendations.sort(key=lambda x: abs(x['change_percent']), reverse=True)
            return recommendations[:6]
            
        except Exception as e:
            logger.error(f"❌ Error getting crypto recommendations: {e}")
            return [
                {'symbol': 'BTC-USD', 'change_percent': 0, 'current_price': 50000, 'crypto_type': '🪙 קריפטו'},
                {'symbol': 'ETH-USD', 'change_percent': 0, 'current_price': 3000, 'crypto_type': '🪙 קריפטו'},
                {'symbol': 'SOL-USD', 'change_percent': 0, 'current_price': 100, 'crypto_type': '🪙 קריפטו'}
            ]

    def create_advanced_chart_with_stoploss(self, symbol):
        """יצירת גרף נרות מתקדם עם סטופלוס מומלץ"""
        try:
            stock = yf.Ticker(symbol)
            data = stock.history(period="30d")
            
            if data.empty:
                return None, None
            
            last_close = data['Close'][-1]
            stoploss = last_close * 0.98
            
            plt.style.use('dark_background')
            fig, ax = plt.subplots(figsize=(12, 8))
            
            mpf.plot(data, type='candle', style='charles', 
                    title=f'{symbol} - 30 Days Candlestick Chart',
                    ylabel='Price', ax=ax)
            
            ax.axhline(stoploss, color='red', linestyle='--', linewidth=2, 
                      label=f'Stop Loss: {stoploss:.2f} (-2%)', alpha=0.8)
            ax.axhline(last_close, color='yellow', linestyle='-', linewidth=1.5, 
                      label=f'Current: {last_close:.2f}', alpha=0.8)
            
            profit_target = last_close * 1.05
            ax.axhline(profit_target, color='green', linestyle=':', linewidth=1.5, 
                      label=f'Target: {profit_target:.2f} (+5%)', alpha=0.8)
            
            ax.legend(loc='upper left')
            ax.grid(True, alpha=0.3)
            
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight', 
                       facecolor='black', edgecolor='none')
            buffer.seek(0)
            plt.close()
            
            return buffer, stoploss
            
        except Exception as e:
            logger.error(f"❌ Error creating chart for {symbol}: {e}")
            return None, None

    async def send_mixed_content(self):
        """שליחת תוכן מעורב עם מניות אמריקאיות וישראליות"""
        try:
            recommendations = self.get_mixed_stock_recommendations()
            
            if not recommendations:
                logger.warning("No mixed stock recommendations available")
                return
            
            selected_stock = random.choice(recommendations)
            symbol = selected_stock['symbol']
            stock_type = selected_stock['stock_type']
            
            chart_buffer, stoploss = self.create_advanced_chart_with_stoploss(symbol)
            
            if not chart_buffer:
                logger.error(f"Failed to create chart for {symbol}")
                return
            
            stock = yf.Ticker(symbol)
            data = stock.history(period="2d")
            
            current_price = data['Close'][-1]
            change = data['Close'][-1] - data['Close'][-2] if len(data) > 1 else 0
            change_percent = (change / data['Close'][-2] * 100) if len(data) > 1 and data['Close'][-2] != 0 else 0
            volume = data['Volume'][-1] if len(data) > 0 else 0
            
            profit_target = current_price * 1.05
            risk_reward = (profit_target - current_price) / (current_price - stoploss) if stoploss else 0
            
            currency = "₪" if symbol.endswith('.TA') else "$"
            
            caption = f"""{stock_type} 📈 {symbol} - ניתוח טכני מתקדם

💰 מחיר נוכחי: {currency}{current_price:.2f}
📊 שינוי יומי: {change:+.2f} ({change_percent:+.2f}%)
📈 נפח מסחר: {volume:,.0f}

🎯 המלצות מסחר:
🔴 Stop Loss: {currency}{stoploss:.2f} (-2.0%)
🟢 יעד רווח: {currency}{profit_target:.2f} (+5.0%)
⚖️ יחס סיכון/תשואה: 1:{risk_reward:.1f}

🔍 נקודות מפתח:
• מגמה: {'עלייה חזקה' if change_percent > 3 else 'עלייה' if change_percent > 0 else 'ירידה'}
• נפח: {'גבוה מהממוצע' if volume > 1000000 else 'נמוך מהממוצע'}
• תנודתיות: {'גבוהה' if abs(change_percent) > 3 else 'בינונית'}

💡 אסטרטגיה מומלצת:
• כניסה: מעל {currency}{current_price:.2f}
• סטופלוס: מתחת ל-{currency}{stoploss:.2f}
• יעד: {currency}{profit_target:.2f}

⚠️ זה לא ייעוץ השקעה - לצרכי חינוך בלבד

#PeakTradeVIP #{symbol.replace('.TA', '')} #TechnicalAnalysis #Stocks"""
            
            await self.application.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=chart_buffer,
                caption=caption
            )
            
            logger.info(f"✅ Stock content sent for {symbol} ({stock_type}) - Change: {change_percent:.2f}%")
            
        except Exception as e:
            logger.error(f"❌ Error sending stock content: {e}")
    
    async def send_crypto_content(self):
        """שליחת תוכן קריפטו עם גרף וסטופלוס"""
        try:
            recommendations = self.get_crypto_recommendations()
            
            if not recommendations:
                logger.warning("No crypto recommendations available")
                return
            
            selected_crypto = random.choice(recommendations)
            symbol = selected_crypto['symbol']
            crypto_type = selected_crypto['crypto_type']
            
            chart_buffer, stoploss = self.create_advanced_chart_with_stoploss(symbol)
            
            if not chart_buffer:
                logger.error(f"Failed to create chart for {symbol}")
                return
            
            crypto = yf.Ticker(symbol)
            data = crypto.history(period="2d")
            
            current_price = data['Close'][-1]
            change = data['Close'][-1] - data['Close'][-2] if len(data) > 1 else 0
            change_percent = (change / data['Close'][-2] * 100) if len(data) > 1 and data['Close'][-2] != 0 else 0
            volume = data['Volume'][-1] if len(data) > 0 else 0
            
            profit_target = current_price * 1.05
            risk_reward = (profit_target - current_price) / (current_price - stoploss) if stoploss else 0
            
            crypto_name = symbol.replace('-USD', '')
            
            caption = f"""{crypto_type} {crypto_name} - ניתוח טכני מתקדם

💰 מחיר נוכחי: ${current_price:.2f}
📊 שינוי יומי: {change:+.2f} ({change_percent:+.2f}%)
📈 נפח מסחר: {volume:,.0f}

🎯 המלצות מסחר:
🔴 Stop Loss: ${stoploss:.2f} (-2.0%)
🟢 יעד רווח: ${profit_target:.2f} (+5.0%)
⚖️ יחס סיכון/תשואה: 1:{risk_reward:.1f}

🔍 נקודות מפתח:
• מגמה: {'עלייה חזקה' if change_percent > 5 else 'עלייה' if change_percent > 0 else 'ירידה'}
• נפח: {'גבוה מהממוצע' if volume > 100000 else 'נמוך מהממוצע'}
• תנודתיות: {'גבוהה מאוד' if abs(change_percent) > 10 else 'גבוהה' if abs(change_percent) > 5 else 'בינונית'}

💡 אסטרטגיה מומלצת:
• כניסה: מעל ${current_price:.2f}
• סטופלוס: מתחת ל-${stoploss:.2f}
• יעד: ${profit_target:.2f}

⚠️ זה לא ייעוץ השקעה - לצרכי חינוך בלבד
⚠️ קריפטו כרוך בסיכון גבוה במיוחד

#PeakTradeVIP #{crypto_name} #Crypto #TechnicalAnalysis"""
            
            await self.application.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=chart_buffer,
                caption=caption
            )
            
            logger.info(f"✅ Crypto content sent for {symbol} - Change: {change_percent:.2f}%")
            
        except Exception as e:
            logger.error(f"❌ Error sending crypto content: {e}")

    def setup_scheduler(self):
        """הגדרת תזמון משימות - 10 מניות + 3 קריפטו"""
        self.scheduler = AsyncIOScheduler()
        
        # 10 משימות מניות (ישראל+חו"ל)
        for i in range(10):
            random_hour = random.randint(10, 22)
            random_minute = random.randint(0, 59)
            
            self.scheduler.add_job(
                self.send_mixed_content,
                CronTrigger(hour=random_hour, minute=random_minute),
                id=f'stock_content_{i}'
            )
        
        # 3 משימות קריפטו
        for i in range(3):
            random_hour = random.randint(10, 22)
            random_minute = random.randint(0, 59)
            
            self.scheduler.add_job(
                self.send_crypto_content,
                CronTrigger(hour=random_hour, minute=random_minute),
                id=f'crypto_content_{i}'
            )
        
        self.scheduler.start()
        logger.info("✅ Scheduler configured: 10 stocks + 3 crypto daily")

    async def run(self):
        """הפעלת הבוט"""
        logger.info("🚀 Starting PeakTrade VIP Bot...")
        
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.setup_scheduler()
        
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            logger.info("✅ PeakTrade VIP Bot is running successfully!")
            logger.info("📊 Daily content: 10 stocks + 3 crypto = 13 messages")
            
            while True:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"❌ Bot error: {e}")
        finally:
            if self.scheduler:
                self.scheduler.shutdown()
            if self.application:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()

# יצירת אפליקציית Flask לWebhooks
flask_app = Flask(__name__)

@flask_app.route('/health', methods=['GET'])
def health_check():
    return "OK", 200

# מתאם WSGI -> ASGI עבור אפליקציית ה-Flask
flask_asgi_app = WsgiToAsgi(flask_app)

# יצירת אפליקציית ASGI ראשית שתשלב את הכל
async def asgi_app(scope, receive, send):
    """אפליקציית ה-ASGI הראשית ש-Uvicorn יריץ"""
    if scope['type'] == 'lifespan':
        bot = PeakTradeBot()
        asyncio.create_task(bot.run())
        await flask_asgi_app(scope, receive, send)
    else:
        await flask_asgi_app(scope, receive, send)

if __name__ == "__main__":
    bot = PeakTradeBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
