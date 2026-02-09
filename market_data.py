import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import asyncio

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
    last_time = data.index[-1]
    
    # FIX: Handle Timezones correctly (UTC -> IST)
    # Yahoo often returns data in UTC or local time with offsets.
    # We normalize to naive (no timezone) then add 5:30 manually for display.
    if last_time.tzinfo is not None:
        last_time = last_time.replace(tzinfo=None)
        
    # Add 5 hours and 30 minutes to get IST
    ist_time = last_time + timedelta(hours=5, minutes=30)
    
    # Check if market is open (compare UTC server time vs UTC data time)
    # If the last data point is less than 15 mins old, market is OPEN.
    is_market_open = (datetime.utcnow() - last_time) < timedelta(minutes=15)
    status = "OPEN" if is_market_open else "CLOSED"

    return {
        "data": data,
        "status": status,
        "last_updated": ist_time.strftime("%H:%M:%S") # <--- Sends IST time to your screen
    }, None
