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
    """
    try:
        logger.info(f"Attempting to generate graph for {symbol} ({period}, {interval})")
        stock_data = yf.Ticker(symbol)
        hist_data = stock_data.history(period=period, interval=interval)

        if hist_data.empty:
            logger.warning(f"No historical data found for symbol {symbol} with period {period} and interval {interval}.")
            return None, f"לא נמצאו נתונים היסטוריים עבור הסימול {symbol}."

        last_close = hist_data['Close'].iloc[-1] if not hist_data['Close'].empty else "N/A"
        first_date = hist_data.index[0].strftime('%d/%m/%Y') if not hist_data.empty else "N/A"
        last_date = hist_data.index[-1].strftime('%d/%m/%Y') if not hist_data.empty else "N/A"
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

        mc = mpf.make_marketcolors(up='g', down='r', inherit=True)
        s  = mpf.make_mpf_style(marketcolors=mc, gridstyle=':', base_mpf_style='yahoo')
        
        sma_short = 20
        sma_long = 50
        apds = []
        if len(hist_data) >= sma_short:
            hist_data[f'SMA{sma_short}'] = hist_data['Close'].rolling(window=sma_short).mean()
            apds.append(mpf.make_addplot(hist_data[f'SMA{sma_short}'], color='blue', width=0.7))
        if len(hist_data) >= sma_long:
            hist_data[f'SMA{sma_long}'] = hist_data['Close'].rolling(window=sma_long).mean()
            apds.append(mpf.make_addplot(hist_data[f'SMA{sma_long}'], color='orange', width=0.7))

        image_stream = io.BytesIO()
        fig, axes = mpf.plot(
            hist_data, type='candle', style=s,
            title=f"\n{company_name} ({symbol.upper()}) - {interval} Chart",
            ylabel='מחיר', volume=True, ylabel_lower='נפח מסחר',
            addplot=apds if apds else None,
            figsize=(12, 7), datetime_format='%b %d, %Y', xrotation=20,
            returnfig=True
        )
        legend_text = []
        if f'SMA{sma_short}' in hist_data.columns: legend_text.append(f'SMA{sma_short}')
        if f'SMA{sma_long}' in hist_data.columns: legend_text.append(f'SMA{sma_long}')
        if legend_text and axes and len(axes) > 0: # ודא ש-axes אינו ריק ויש לו לפחות אלמנט אחד
             axes[0].legend(legend_text, loc='upper left')

        fig.savefig(image_stream, format='png', bbox_inches='tight')
        image_stream.seek(0)
        plt = mpf. देख # הוסף כדי לנקות את התמונה מהזיכרון של matplotlib
        plt.close(fig)


        logger.info(f"Successfully generated graph for {symbol}")
        return image_stream, descriptive_text
    except Exception as e:
        logger.error(f"Error generating graph for {symbol}: {e}", exc_info=True)
        return None, f"שגיאה ביצירת גרף עבור {symbol}: {e}"

# הוסף את הייבוא החסר אם אתה משתמש ב-plt.close(fig)
import matplotlib.pyplot as plt
