import io
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

def create_stock_graph_and_text(stock_symbol: str):
    try:
        # הורדת נתוני המניה
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)  # שנה אחורה
        stock_data = yf.download(stock_symbol, start=start_date, end=end_date)
        
        if stock_data.empty:
            return None, "⚠️ לא נמצאו נתונים למניה זו"
        
        # יצירת גרף
        plt.figure(figsize=(10, 6))
        plt.plot(stock_data['Close'], label='מחיר סגירה', color='blue')
        plt.title(f'{stock_symbol} - מגמת מחירים אחרונה')
        plt.xlabel('תאריך')
        plt.ylabel('מחיר ($)')
        plt.legend()
        plt.grid(True)
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%m/%y'))
        plt.gca().xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        plt.gcf().autofmt_xdate()
        
        # המרה לזרם נתונים
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png', bbox_inches='tight')
        img_buffer.seek(0)
        plt.close()
        
        # יצירת טקסט ניתוח
        last_close = stock_data['Close'][-1]
        analysis_text = (
            f"📊 ניתוח טכני עבור {stock_symbol}\n"
            f"▫️ מחיר נוכחי: ${last_close:.2f}\n"
            f"▫️ תנודתיות שבועית: {calculate_volatility(stock_data):.2%}\n"
            f"▫️ מגמה: {'עולה 📈' if last_close > stock_data['Close'][-30] else 'יורדת 📉'}\n\n"
            "📌 זכרו: זה אינו ייעוץ השקעות!"
        )
        
        return img_buffer, analysis_text
        
    except Exception as e:
        error_msg = f"שגיאה ביצירת גרף: {str(e)}"
        return None, error_msg

def calculate_volatility(data, days=7):
    """ חישוב תנודתיות שבועית """
    if len(data) < days:
        return 0.0
    returns = data['Close'].pct_change().dropna()
    return returns[-days:].std() * np.sqrt(days)
