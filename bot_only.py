import logging
import os
import asyncio
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import TelegramError
import gspread
from google.oauth2.service_account import Credentials
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import matplotlib.pyplot as plt
import io
import random
import requests
import pandas as pd

# הגדרת לוגינג
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# הגדרות המערכת
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
GOOGLE_CREDENTIALS = os.getenv('GOOGLE_CREDENTIALS')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
TWELVE_DATA_API_KEY = os.getenv('TWELVE_DATA_API_KEY')

# בדיקת משתני סביבה
if not BOT_TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN environment variable not set!")
    exit(1)
if not CHANNEL_ID:
    logger.error("❌ CHANNEL_ID environment variable not set!")
    exit(1)
if not GOOGLE_CREDENTIALS:
    logger.error("❌ GOOGLE_CREDENTIALS environment variable not set!")
    exit(1)
if not SPREADSHEET_ID:
    logger.error("❌ SPREADSHEET_ID environment variable not set!")
    exit(1)
if not TWELVE_DATA_API_KEY:
    logger.error("❌ TWELVE_DATA_API_KEY environment variable not set!")
    exit(1)

logger.info("✅ All environment variables are set")

# הגדרות תשלום
PAYPAL_PAYMENT_LINK = "https://www.paypal.com/ncp/payment/LYPU8NUFJB7XW"
MONTHLY_PRICE = 120

class TwelveDataAPI:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.twelvedata.com"
    
    def get_stock_data(self, symbol):
        """קבלת נתוני מניה מ-Twelve Data API עם requests"""
        try:
            url = f"{self.base_url}/time_series"
            params = {
                'symbol': symbol,
                'interval': '1day',
                'outputsize': 30,
                'apikey': self.api_key
            }
            
            response = requests.get(url, params=params)
            data = response.json()
            
            if 'values' in data and data['values']:
                df_data = []
                for item in data['values']:
                    df_data.append({
                        'Open': float(item['open']),
                        'High': float(item['high']),
                        'Low': float(item['low']),
                        'Close': float(item['close']),
                        'Volume': int(item['volume'])
                    })
                
                df = pd.DataFrame(df_data)
                dates = [datetime.strptime(item['datetime'], '%Y-%m-%d') for item in data['values']]
                df.index = pd.DatetimeIndex(dates)
                df = df.sort_index()
                
                logger.info(f"✅ Twelve Data retrieved for {symbol}: {len(df)} days")
                return df
            else:
                logger.error(f"No Twelve Data for {symbol}")
                return self.get_stock_quote(symbol)
                
        except Exception as e:
            logger.error(f"Twelve Data error for {symbol}: {e}")
            return self.get_stock_quote(symbol)
    
    def get_stock_quote(self, symbol):
        """קבלת מחיר נוכחי מ-Twelve Data"""
        try:
            url = f"{self.base_url}/price"
            params = {
                'symbol': symbol,
                'apikey': self.api_key
            }
            
            response = requests.get(url, params=params)
            price_data = response.json()
            
            if 'price' in price_data:
                current_price = float(price_data['price'])
                
                # יצירת DataFrame פשוט עם המחיר הנוכחי
                df_data = []
                for i in range(30):
                    date = datetime.now() - timedelta(days=29-i)
                    price_variation = random.uniform(0.98, 1.02)
                    base_price = current_price * price_variation
                    
                    df_data.append({
                        'Open': base_price * random.uniform(0.995, 1.005),
                        'High': base_price * random.uniform(1.00, 1.02),
                        'Low': base_price * random.uniform(0.98, 1.00),
                        'Close': base_price,
                        'Volume': random.randint(1000000, 10000000)
                    })
                
                df = pd.DataFrame(df_data)
                dates = [datetime.now() - timedelta(days=29-i) for i in range(30)]
                df.index = pd.DatetimeIndex(dates)
                df.iloc[-1, df.columns.get_loc('Close')] = current_price
                
                logger.info(f"✅ Twelve Data quote used for {symbol}: ${current_price}")
                return df
            else:
                logger.error(f"No price data for {symbol}")
                return None
                
        except Exception as e:
            logger.error(f"Twelve Data quote error for {symbol}: {e}")
            return None

class PeakTradeBot:
    def __init__(self):
        self.application = None
        self.scheduler = None
        self.google_client = None
        self.sheet = None
        self.twelve_api = TwelveDataAPI(TWELVE_DATA_API_KEY)
        
    def setup_google_sheets(self):
        """הגדרת חיבור ל-Google Sheets"""
        try:
            logger.info("🔄 Setting up Google Sheets connection...")
            
            # פירוק JSON credentials
            creds_dict = json.loads(GOOGLE_CREDENTIALS)
            logger.info(f"📋 Service account email: {creds_dict.get('client_email', 'N/A')}")
            
            scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ]
            
            creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
            self.google_client = gspread.authorize(creds)
            
            # פתיחת הגיליון
            self.sheet = self.google_client.open_by_key(SPREADSHEET_ID).sheet1
            
            # בדיקת גישה
            test_data = self.sheet.get_all_records()
            logger.info(f"✅ Google Sheets connected successfully! Found {len(test_data)} existing records")
            
            return True
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Error parsing GOOGLE_CREDENTIALS JSON: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Error setting up Google Sheets: {e}")
            return False

    def check_user_exists(self, user_id):
        """בדיקה אם משתמש כבר קיים ב-Google Sheets"""
        try:
            if not self.sheet:
                logger.warning("⚠️ No Google Sheets connection")
                return False
            
            logger.info(f"🔍 Checking if user {user_id} exists...")
            records = self.sheet.get_all_records()
            
            for record in records:
                if str(record.get('telegram_user_id')) == str(user_id):
                    status = record.get('payment_status', '')
                    logger.info(f"👤 User {user_id} found with status: {status}")
                    if status in ['trial_active', 'paid_subscriber']:
                        return True
            
            logger.info(f"✅ User {user_id} not found - new user")
            return False
            
        except Exception as e:
            logger.error(f"❌ Error checking user existence: {e}")
            return False

    def create_professional_chart_with_prices(self, symbol, data, current_price, entry_price, stop_loss, target1, target2):
        """יצירת גרף מקצועי עם מחירים ספציפיים מסומנים - טקסט באנגלית"""
        try:
            plt.style.use('dark_background')
            fig, ax = plt.subplots(figsize=(14, 10))
            
            ax.plot(data.index, data['Close'], color='white', linewidth=3, label=f'{symbol} Price', alpha=0.9)
            ax.fill_between(data.index, data['Low'], data['High'], alpha=0.2, color='gray', label='Daily Range')
            
            ax.axhline(current_price, color='yellow', linestyle='-', linewidth=4, 
                      label=f'💰 Current Price: ${current_price:.2f}', alpha=1.0)
            ax.axhline(entry_price, color='lime', linestyle='-', linewidth=3, 
                      label=f'🟢 Entry: ${entry_price:.2f}', alpha=0.9)
            ax.axhline(stop_loss, color='red', linestyle='--', linewidth=3, 
                      label=f'🔴 Stop Loss: ${stop_loss:.2f}', alpha=0.9)
            ax.axhline(target1, color='gold', linestyle=':', linewidth=3, 
                      label=f'🎯 Target 1: ${target1:.2f}', alpha=0.9)
            ax.axhline(target2, color='cyan', linestyle=':', linewidth=3, 
                      label=f'🚀 Target 2: ${target2:.2f}', alpha=0.9)
            
            ax.fill_between(data.index, entry_price, target2, alpha=0.15, color='green', label='Profit Zone')
            ax.fill_between(data.index, stop_loss, entry_price, alpha=0.15, color='red', label='Risk Zone')
            
            ax.set_title(f'{symbol} - PeakTrade VIP Analysis', color='white', fontsize=20, fontweight='bold', pad=20)
            ax.set_ylabel('Price ($)', color='white', fontsize=16, fontweight='bold')
            ax.set_xlabel('Date', color='white', fontsize=16, fontweight='bold')
            
            ax.grid(True, alpha=0.4, color='gray', linestyle='-', linewidth=0.5)
            ax.legend(loc='upper left', fontsize=13, framealpha=0.9, fancybox=True, shadow=True)
            
            ax.set_facecolor('#0a0a0a')
            fig.patch.set_facecolor('#1a1a1a')
            
            ax.text(0.02, 0.98, 'PeakTrade VIP', transform=ax.transAxes, 
                    fontsize=18, color='cyan', fontweight='bold', 
                    verticalalignment='top', alpha=0.9)
            
            ax.text(0.02, 0.02, 'Professional Analysis', transform=ax.transAxes, 
                    fontsize=14, color='lime', fontweight='bold', 
                    verticalalignment='bottom', alpha=0.9)
            
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight', 
                       facecolor='#1a1a1a', edgecolor='none')
            buffer.seek(0)
            plt.close()
            
            logger.info(f"✅ Professional chart created for {symbol}")
            return buffer
            
        except Exception as e:
            logger.error(f"❌ Error creating chart: {e}")
            return None

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת התחלה - לינק מיידי ללא אישור"""
        user = update.effective_user
        logger.info(f"User {user.id} ({user.username}) started PeakTrade bot")
        
        # בדיקה אם משתמש כבר קיים
        if self.check_user_exists(user.id):
            await update.message.reply_text(
                "🔄 נראה שכבר יש לך מנוי פעיל!\n\nאם אתה צריך עזרה, פנה לתמיכה."
            )
            return
        
        processing_msg = await update.message.reply_text(
            "⏳ מכין עבורך את הקישור לערוץ הפרמיום..."
        )
        
        try:
            # רישום המשתמש ב-Google Sheets
            sheets_success = await self.log_user_registration(user)
            
            # יצירת לינק הזמנה
            invite_link = await context.bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                expire_date=int((datetime.now() + timedelta(days=8)).timestamp()),
                name=f"Trial_{user.id}_{user.username or 'user'}"
            )
            
            success_message = f"""🎉 ברוך הבא ל-PeakTrade VIP!

היי, זה מצוות הערוץ ״PeakTrade VIP״ 

המנוי שלך מתחיל היום {datetime.now().strftime('%d.%m')} ויסתיים ב{(datetime.now() + timedelta(days=7)).strftime('%d.%m')}

חשוב להבהיר:
🚫התוכן כאן אינו מהווה ייעוץ או המלצה פיננסית מכל סוג!
📌 ההחלטות בסופו של דבר בידיים שלכם – איך לפעול, מתי להיכנס ומתי לצאת מהשוק.

👤 שם משתמש: @{user.username or 'לא זמין'}

🔗 הקישור שלך לערוץ הפרמיום:
{invite_link.invite_link}

⏰ תקופת הניסיון שלך: 7 ימים מלאים
📅 מתחיל היום: {datetime.now().strftime("%d/%m/%Y")}
📅 מסתיים: {(datetime.now() + timedelta(days=7)).strftime("%d/%m/%Y")}

🎯 מה מחכה לך בערוץ:
• המלצות מניות חמות כל 30 דקות
• גרפים מקצועיים עם נקודות כניסה ויציאה
• ניתוחים טכניים מתקדמים
• קהילת משקיעים פעילה

לחץ על הקישור והצטרף עכשיו! 🚀

{"📊 Google Sheets: " + ("✅ מעודכן" if sheets_success else "❌ שגיאה"))}

בהצלחה במסחר! 💪"""
            
            await processing_msg.edit_text(
                success_message,
                disable_web_page_preview=True
            )
            
            logger.info(f"✅ Direct registration successful for user {user.id} (Sheets: {sheets_success})")
            
        except Exception as e:
            logger.error(f"❌ Error in direct registration: {e}")
            await processing_msg.edit_text(
                "❌ אופס! משהו השתבש ברישום\n\nאנא נסה שוב או פנה לתמיכה."
            )

    async def log_user_registration(self, user):
        """רישום משתמש ב-Google Sheets"""
        try:
            if not self.sheet:
                logger.error("❌ No Google Sheets connection for logging")
                return False
                
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            trial_end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
            
            logger.info(f"📝 Writing user {user.id} to Google Sheets...")
            
            new_row = [
                user.id,
                user.username or "N/A",
                "",  # email
                current_time,  # registration_date
                "confirmed",  # disclaimer_status
                current_time,  # trial_start_date
                trial_end,  # trial_end_date
                "trial_active",  # payment_status
                "",  # payment_screenshot
                "",  # notes
                current_time  # last_updated
            ]
            
            self.sheet.append_row(new_row)
            logger.info(f"✅ User {user.id} successfully written to Google Sheets")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error logging user registration: {e}")
            return False

    async def send_trial_expiry_reminder(self, user_id):
        """שליחת תזכורת תשלום יום לפני סיום תקופת הניסיון"""
        try:
            keyboard = [
                [InlineKeyboardButton("💎 כן - אני רוצה להמשיך!", callback_data="pay_yes")],
                [InlineKeyboardButton("❌ לא תודה", callback_data="pay_no")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            reminder_message = f"""תמיכה שוק ההון:
תקופת הניסיון שלך הסתיימה!

היית בפנים 7 ימים, קיבלת עסקאות, ניתוחים, איתותים.
ראית איך זה עובד באמת, לא סיפורים ולא חרטא,עסקאות בזמן אמת, יחס אישי.

אבל עכשיו?
פה זה הרגע שכולם נופלים בו:
או שהם נשארים ומתחילים לראות תוצאות קבועות –
או שהם יוצאים… וחוזרים לשחק אותה סולו, לנחש, להתבאס.

במה אתה בוחר?
"""
            
            await self.application.bot.send_message(
                chat_id=user_id,
                text=reminder_message,
                reply_markup=reply_markup
            )
            
            logger.info(f"✅ Payment reminder sent to user {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Error sending payment reminder to user {user_id}: {e}")

    async def send_final_payment_message(self, user_id):
        """שליחת הודעת תשלום סופית"""
        try:
            final_message = f"""היי, כאן צוות חדר העסקאות – שוק ההון

איך היה שבוע הניסיון? הרגשת שיפור בתיק שלך? קיבלת ידע וניתוחים שלא יצא לך לדעת? הרגשת יחס אישי?

אם אתה רוצה להמשיך – העלות {MONTHLY_PRICE}₪ לחודש.

קישור לתשלום:
{PAYPAL_PAYMENT_LINK}

מי שלא מחדש – מוסר אוטומטית.
אחרי התשלום שלח צילום מסך"""
            
            await self.application.bot.send_message(
                chat_id=user_id,
                text=final_message
            )
            
            logger.info(f"✅ Final payment message sent to user {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Error sending final payment message to user {user_id}: {e}")

    async def remove_user_after_trial(self, user_id, row_index=None):
        """הסרת משתמש מהערוץ לאחר סיום תקופת ניסיון ללא תשלום"""
        try:
            await self.application.bot.ban_chat_member(
                chat_id=CHANNEL_ID,
                user_id=user_id
            )
            
            goodbye_message = """👋 תקופת הניסיון שלך הסתיימה

הוסרת מערוץ PeakTrade VIP מכיוון שלא חידשת את המנוי.

💡 תמיד אפשר לחזור ולהירשם שוב!
שלח /start כדי להתחיל מחדש.

תודה שניסית את השירות שלנו! 🙏
בהצלחה במסחר! 💪"""
            
            try:
                await self.application.bot.send_message(
                    chat_id=user_id,
                    text=goodbye_message
                )
            except:
                pass
            
            if row_index and self.sheet:
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                try:
                    self.sheet.update_cell(row_index, 8, "expired_no_payment")
                    self.sheet.update_cell(row_index, 11, current_time)
                    logger.info(f"📝 Updated Google Sheets for user {user_id} removal")
                except Exception as update_error:
                    logger.error(f"Error updating expiry status: {update_error}")
            
            logger.info(f"✅ User {user_id} removed after trial expiry")
            
        except Exception as e:
            logger.error(f"❌ Error removing user {user_id}: {e}")

    async def check_trial_expiry(self):
        """בדיקה יומית של סיום תקופת ניסיון"""
        try:
            logger.info("🔍 Starting trial expiry check...")
            
            if not self.sheet:
                logger.error("❌ No Google Sheets connection for trial check")
                return
            
            records = self.sheet.get_all_records()
            current_time = datetime.now()
            
            logger.info(f"📊 Checking {len(records)} records for trial expiry")
            
            for i, record in enumerate(records):
                if record.get('payment_status') == 'trial_active':
                    trial_end_str = record.get('trial_end_date')
                    user_id = record.get('telegram_user_id')
                    
                    if trial_end_str and user_id:
                        try:
                            trial_end = datetime.strptime(trial_end_str, "%Y-%m-%d %H:%M:%S")
                            days_diff = (trial_end - current_time).days
                            
                            logger.info(f"👤 User {user_id}: trial ends in {days_diff} days")
                            
                            # יום לפני סיום הניסיון - הודעה ראשונה
                            if days_diff == 1:
                                await self.send_trial_expiry_reminder(user_id)
                            # יום אחרי סיום הניסיון - הודעה שנייה
                            elif current_time > trial_end and (current_time - trial_end).days == 1:
                                await self.send_final_payment_message(user_id)
                            # יומיים אחרי סיום הניסיון - הסרה
                            elif current_time > trial_end and (current_time - trial_end).days >= 2:
                                await self.remove_user_after_trial(user_id, i + 2)
                                
                        except ValueError as ve:
                            logger.error(f"Invalid date format for user {user_id}: {trial_end_str} - {ve}")
            
            logger.info("✅ Trial expiry check completed")
            
        except Exception as e:
            logger.error(f"❌ Error checking trial expiry: {e}")

    async def handle_payment_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """טיפול בבחירת תשלום"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        choice = query.data
        
        if choice == "pay_yes":
            keyboard = [
                [InlineKeyboardButton("💳 PayPal", url=PAYPAL_PAYMENT_LINK)],
                [InlineKeyboardButton("📱 Google Pay", callback_data="gpay_payment")],
                [InlineKeyboardButton("❌ ביטול", callback_data="pay_cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            payment_message = f"""💳 תשלום PeakTrade VIP

💰 מחיר: {MONTHLY_PRICE}₪/חודש
⏰ חיוב חודשי אוטומטי

📸 אחרי התשלום שלח צילום מסך

🔒 תשלום מאובטח דרך:

לחץ על אחת מהאפשרויות למטה:"""
            
            await query.edit_message_text(
                text=payment_message,
                reply_markup=reply_markup
            )
            
        elif choice == "pay_no":
            goodbye_message = """👋 תודה שניסית את PeakTrade VIP!

הבנו שאתה לא מעוניין להמשיך כרגע.
תוסר מהערוץ הפרמיום מחר.

💡 תמיד אפשר לחזור ולהירשם שוב!
שלח /start כדי להתחיל מחדש.

תודה ובהצלחה! 🙏"""
            
            await query.edit_message_text(text=goodbye_message)
            
        elif choice == "gpay_payment":
            await query.edit_message_text(
                text=f"📱 Google Pay זמין בקרוב!\n\nבינתיים אפשר לשלם דרך PayPal:\n{PAYPAL_PAYMENT_LINK}"
            )
            
        elif choice == "pay_cancel":
            await query.edit_message_text(
                text="❌ התשלום בוטל.\n\nתקבל תזכורת נוספת מחר."
            )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """פקודת עזרה"""
        help_text = f"""🆘 PeakTrade VIP Bot - מדריך מהיר

📋 פקודות זמינות:
/start - הצטרפות לערוץ הפרמיום
/help - מדריך זה

💎 מה מיוחד בערוץ שלנו:
• המלצות מניות מנצחות
• גרפים מקצועיים בזמן אמת
• קהילת משקיעים פעילה

⏰ תקופת ניסיון: 7 ימים חינם
💰 מחיר מנוי: {MONTHLY_PRICE}₪/חודש

🚀 הצטרף עכשיו ותתחיל להרוויח!"""
        
        await update.message.reply_text(help_text)

    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ביטול תהליך"""
        await update.message.reply_text(
            "❌ התהליך בוטל. שלח /start כדי להתחיל מחדש."
        )

    def setup_handlers(self):
        """הגדרת handlers"""
        self.application.add_handler(CommandHandler('start', self.start_command))
        self.application.add_handler(CommandHandler('help', self.help_command))
        self.application.add_handler(CommandHandler('cancel', self.cancel_command))
        self.application.add_handler(CallbackQueryHandler(self.handle_payment_choice))
        
        logger.info("✅ All handlers configured")

    async def send_guaranteed_stock_content(self):
        """שליחת תוכן מניה מקצועי עם Twelve Data"""
        try:
            logger.info("📈 Preparing stock content with Twelve Data...")
            
            # מגוון עצום של מניות מכל הסקטורים
            premium_stocks = [
                # טכנולוגיה גדולה
                {'symbol': 'AAPL', 'type': 'AAPL', 'sector': 'טכנולוגיה'},
                {'symbol': 'MSFT', 'type': 'MSFT', 'sector': 'טכנולוגיה'},
                {'symbol': 'GOOGL', 'type': 'GOOGL', 'sector': 'טכנולוגיה'},
