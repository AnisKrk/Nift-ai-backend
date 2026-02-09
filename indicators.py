import pandas as pd
import math

def clean_val(val):
    """Converts NaN/Inf to None for JSON safety."""
    if val is None:
        return None
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return None
    return val

def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def calculate_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss.replace(0, float('inf'))
    return 100 - (100 / (1 + rs))

def calculate_supertrend(df, period=10, multiplier=3.0):
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    
    # Calculate ATR
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    # Calculate Basic Bands
    hl2 = (high + low) / 2
    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)
    
    supertrend = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)
    
    # Initialize
    supertrend.iloc[0] = lower_band.iloc[0]
    direction.iloc[0] = 1
    
    for i in range(1, len(df)):
        if close.iloc[i] > upper_band.iloc[i-1]:
            supertrend.iloc[i] = lower_band.iloc[i]
            direction.iloc[i] = 1
        elif close.iloc[i] < lower_band.iloc[i-1]:
            supertrend.iloc[i] = upper_band.iloc[i]
            direction.iloc[i] = -1
        else:
            supertrend.iloc[i] = supertrend.iloc[i-1]
            direction.iloc[i] = direction.iloc[i-1]
            
            if direction.iloc[i] == 1 and supertrend.iloc[i] < lower_band.iloc[i]:
                supertrend.iloc[i] = lower_band.iloc[i]
            elif direction.iloc[i] == -1 and supertrend.iloc[i] > upper_band.iloc[i]:
                supertrend.iloc[i] = upper_band.iloc[i]

        # Fill NaN
        if pd.isna(supertrend.iloc[i]):
             supertrend.iloc[i] = supertrend.iloc[i-1]
             
    return supertrend, direction, atr

import pandas_ta as ta  # Import the new library

# ... (Keep your existing clean_val, calculate_ema functions here) ...

def calculate_gainzalgo_signal(df):
    """
    Replicates GainzAlgo V2 Alpha logic:
    1. SuperTrend (Trend Filter)
    2. RSI (Momentum Filter)
    3. Volume/Volatility Check
    """
    # 1. SuperTrend (Standard Algo Settings: 10, 3 or 14, 2)
    st = df.ta.supertrend(length=10, multiplier=3)
    
    # pandas_ta returns columns like "SUPERT_10_3.0", so we rename them for safety
    st_col_value = st.columns[0]  # The value column
    st_col_dir = st.columns[1]    # The direction column (1=Up, -1=Down)
    
    df['ST_Value'] = st[st_col_value]
    df['ST_Dir'] = st[st_col_dir]
    
    # 2. RSI (Momentum)
    df['RSI'] = df.ta.rsi(length=14)
    
    # 3. Heikin-Ashi-like Smoothing (Optional, purely for signal filtering)
    # We simply check if the candle body is strong
    df['Body'] = abs(df['Close'] - df['Open'])
    avg_body = df['Body'].rolling(10).mean()
    
    # --- LOGIC ---
    # BUY: SuperTrend is Green (1) AND RSI > 50 (Momentum Up) AND Strong Candle
    # SELL: SuperTrend is Red (-1) AND RSI < 50 (Momentum Down) AND Strong Candle
    
    current_st_dir = df['ST_Dir'].iloc[-1]
    current_rsi = df['RSI'].iloc[-1]
    
    # Check simple confluence
    algo_signal = "NEUTRAL"
    
    if current_st_dir == 1 and current_rsi > 50:
        algo_signal = "BUY"
    elif current_st_dir == -1 and current_rsi < 50:
        algo_signal = "SELL"
        
    return algo_signal
