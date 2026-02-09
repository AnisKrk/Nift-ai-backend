import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import asyncio
from indicators import clean_val

async def get_market_data(interval="5m"):
    loop = asyncio.get_event_loop()
    # Run download in background thread
    data = await loop.run_in_executor(None, lambda: yf.download("^NSEI", period="5d", interval=interval, progress=False))
    
    if data.empty:
        return None, "No data received"

    # MultiIndex cleanup
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    # Calculate Market Status
    # If the last candle is older than 10 minutes, market is likely closed
    last_time = data.index[-1]
    now_utc = datetime.utcnow()
    # Adjust last_time to UTC if it's naive, assuming input is UTC-ish from Yahoo
    if last_time.tzinfo is None:
        # Yahoo often returns naive timestamps, usually in local market time or UTC
        # We'll assume the difference check handles the "live" status roughly
        pass
        
    is_market_open = (datetime.utcnow() - last_time.replace(tzinfo=None)) < timedelta(minutes=15)
    status = "OPEN" if is_market_open else "CLOSED"

    return {
        "data": data,
        "status": status,
        "last_updated": last_time.strftime("%H:%M:%S")
    }, None

