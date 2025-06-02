# graph_generator.py
import yfinance as yf
import mplfinance as mpf
import datetime
import io # לשמירת הגרף בזיכרון במקום בקובץ
import logging

logger = logging.getLogger(__name__)

def create_stock_graph_and_text(symbol: str, period: str = "3mo", interval: str = "1d") -> (io.BytesIO | None, str | None):
    """
    מוריד נתוני מניה, יוצר גרף נרות ומחזיר אותו כאובייקט BytesIO יחד עם טקסט תיאורי.

    Args:
        symbol (str): סימול המניה (למשל, 'AAPL').
        period (str): טווח הזמן לנתונים (למשל, "1mo", "3mo", "1y", "ytd").
        interval (str): אינטרוול הנתונים (למשל, "1d", "1wk", "1h").

    Returns:
        tuple: (io.BytesIO | None, str | None)
               הראשון הוא אובייקט BytesIO המכיל את תמונת הגרף (או None אם נכשל).
               השני הוא טקסט תיאורי קצר (או None אם נכשל).
    """
    try:
        logger.info(f"Attempting to generate graph for {symbol} ({period}, {interval})")
        # 1. הורדת נתוני המניה
        stock_data = yf.Ticker(symbol)
        hist_data = stock_data.history(period=period, interval=interval)

        if hist_data.empty:
            logger.warning(f"No historical data found for symbol {symbol} with period {period} and interval {interval}.")
            return None, f"לא נמצאו נתונים היסטוריים עבור הסימול {symbol}."

        # 2. יצירת טקסט תיאורי בסיסי
        last_close = hist_data['Close'].iloc[-1] if not hist_data['Close'].empty else "N/A"
        first_date = hist_data.index[0].strftime('%d/%m/%Y') if not hist_data.empty else "N/A"
        last_date = hist_data.index[-1].strftime('%d/%m/%Y') if not hist_data.empty else "N/A"

        # קבלת שם החברה (אם זמין)
        company_name = symbol
        try:
            info = stock_data.info
            company_name = info.get('shortName', symbol)
        except Exception as e:
            logger.warning(f"Could not fetch company info for {symbol}: {e}")


        descriptive_text = (
            f"📊 ניתוח טכני למניית {company_name} ({symbol.upper()})\n"
            f"טווח זמן בגרף: מ-{first_date} עד {last_date}\n"
            f"סגירה אחרונה: {last_close:.2f} (במטבע הרלוונטי)\n\n"
            f"💡 הערה: זהו אינו ייעוץ השקעות. בצע בדיקה משלך לפני כל פעולה."
        )

        # 3. יצירת הגרף עם mplfinance
        # הגדרות סגנון (אופציונלי)
        mc = mpf.make_marketcolors(up='g', down='r', inherit=True)
        s  = mpf.make_mpf_style(marketcolors=mc, gridstyle=':', base_mpf_style='yahoo') # אפשר לבחור 'yahoo', 'charles', 'nightclouds' וכו'

        # הוספת ממוצעים נעים פשוטים (SMA)
        sma_short = 20
        sma_long = 50
        if len(hist_data) >= sma_short:
            hist_data[f'SMA{sma_short}'] = hist_data['Close'].rolling(window=sma_short).mean()
        if len(hist_data) >= sma_long:
            hist_data[f'SMA{sma_long}'] = hist_data['Close'].rolling(window=sma_long).mean()
        
        apds = []
        if f'SMA{sma_short}' in hist_data.columns:
            apds.append(mpf.make_addplot(hist_data[f'SMA{sma_short}'], color='blue', width=0.7))
        if f'SMA{sma_long}' in hist_data.columns:
            apds.append(mpf.make_addplot(hist_data[f'SMA{sma_long}'], color='orange', width=0.7))


        # שמירת הגרף ל-BytesIO במקום לקובץ
        image_stream = io.BytesIO()
        
        fig, axes = mpf.plot(
            hist_data,
            type='candle',    # סוג הגרף: נרות
            style=s,
            title=f"\n{company_name} ({symbol.upper()}) - {interval} Chart", # כותרת מעל הגרף
            ylabel='מחיר',
            volume=True,      # הצג נפח מסחר
            ylabel_lower='נפח מסחר',
            addplot=apds if apds else None, # הוספת הממוצעים הנעים
            figsize=(12, 7),  # גודל התמונה
            datetime_format='%b %d, %Y', # פורמט התאריך בציר ה-X
            xrotation=20,     # סיבוב התוויות בציר ה-X
            returnfig=True    # חשוב כדי לקבל את אובייקט התמונה
        )
        
        # הוספת טקסט על הגרף (לדוגמה, הממוצעים)
        legend_text = []
        if f'SMA{sma_short}' in hist_data.columns: legend_text.append(f'SMA{sma_short}')
        if f'SMA{sma_long}' in hist_data.columns: legend_text.append(f'SMA{sma_long}')
        if legend_text:
             axes[0].legend(legend_text, loc='upper left')


        fig.savefig(image_stream, format='png', bbox_inches='tight') # שמור כ-PNG ל-stream
        image_stream.seek(0) # החזר את ה"סמן" לתחילת ה-stream

        logger.info(f"Successfully generated graph for {symbol}")
        return image_stream, descriptive_text

    except Exception as e:
        logger.error(f"Error generating graph for {symbol}: {e}", exc_info=True)
        return None, f"שגיאה ביצירת גרף עבור {symbol}: {e}"


# --- דוגמת שימוש (להרצה מקומית לבדיקה) ---
if __name__ == '__main__':
    # הגדר לוגר בסיסי אם מריצים ישירות
    logging.basicConfig(level=logging.INFO)

    # בדיקה עבור מניה ספציפית
    test_symbol = 'AAPL'
    # test_symbol = 'NONEXISTENT' # לבדיקת שגיאה
    
    image_bytes_io, text_info = create_stock_graph_and_text(test_symbol, period="6mo", interval="1d")

    if image_bytes_io:
        print(f"מידע על המניה:\n{text_info}")
        # שמירת התמונה לקובץ לבדיקה ויזואלית
        try:
            with open(f"{test_symbol}_chart.png", "wb") as f:
                f.write(image_bytes_io.getbuffer())
            print(f"הגרף נשמר בשם {test_symbol}_chart.png")
        except Exception as e:
            print(f"שגיאה בשמירת הגרף לקובץ: {e}")
    else:
        print(f"לא הצלחנו ליצור גרף עבור {test_symbol}.")
        if text_info:
            print(f"הודעת שגיאה/מידע: {text_info}")

    # בדיקה נוספת
    # test_symbol_2 = 'MSFT'
    # image_bytes_io_2, text_info_2 = create_stock_graph_and_text(test_symbol_2, period="1y", interval="1wk")
    # if image_bytes_io_2:
    #     print(f"\nמידע על המניה:\n{text_info_2}")
    #     try:
    #         with open(f"{test_symbol_2}_chart.png", "wb") as f:
    #             f.write(image_bytes_io_2.getbuffer())
    #         print(f"הגרף נשמר בשם {test_symbol_2}_chart.png")
    #     except Exception as e:
    #         print(f"שגיאה בשמירת הגרף לקובץ: {e}")