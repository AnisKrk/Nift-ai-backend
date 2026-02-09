from fastapi import FastAPI, Query
import yfinance as yf
from fastapi.responses import HTMLResponse
import pandas as pd
from datetime import datetime

app = FastAPI()

# ────────────────────────────────────────────────
# Prediction Endpoint
# ────────────────────────────────────────────────
@app.get("/")
def predict():
    try:
        # NOTE: We removed the custom session here. 
        # yfinance will now automatically use 'curl_cffi' (if installed) to bypass blocks.
        data = yf.download("^NSEI", period="1d", interval="5m", progress=False)

        # Fallback: Try fetching 5 days if 1 day fails or is empty
        if data.empty or len(data) < 5:
            data = yf.download("^NSEI", period="5d", interval="5m", progress=False)
        
        last_time = data.index[-1] if not data.empty else datetime.utcnow()
        
        # Check if data is still empty after fallback
        if data.empty or len(data) < 5:
            return {
                "signal": "DATA ERROR",
                "message": "Yahoo Finance is blocking data. Ensure 'curl-cffi' is in requirements.txt"
            }

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        
        close = data["Close"]
        high = data["High"]
        low = data["Low"]
        price = float(close.iloc[-1])

        # --- INDICATORS ---
        ema_fast = close.ewm(span=9, adjust=False).mean()
        ema_slow = close.ewm(span=21, adjust=False).mean()
        fast = float(ema_fast.iloc[-1])
        slow = float(ema_slow.iloc[-1])

        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
        rs = gain / loss.replace(0, float('inf'))
        rsi = 100 - (100 / (1 + rs))
        rsi_last = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50.0

        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=14).mean()
        atr_last = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else 1.0

        # Supertrend
        st_period = 10
        st_multiplier = 3.0
        hl2 = (high + low) / 2
        atr_st = tr.rolling(window=st_period).mean()
        upper_band = hl2 + (st_multiplier * atr_st)
        lower_band = hl2 - (st_multiplier * atr_st)

        supertrend = pd.Series(index=data.index, dtype=float)
        direction = pd.Series(index=data.index, dtype=int)
        supertrend.iloc[0] = lower_band.iloc[0]
        direction.iloc[0] = 1

        for i in range(1, len(data)):
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
            
            if pd.isna(supertrend.iloc[i]):
                 supertrend.iloc[i] = supertrend.iloc[i-1]

        st_last = float(supertrend.iloc[-1])
        st_dir = direction.iloc[-1]

        ema_bullish = fast > slow
        ema_bearish = fast < slow
        st_bullish = st_dir == 1
        st_bearish = st_dir == -1

        if ema_bullish and rsi_last > 53 and st_bullish:
            signal = "BUY"
        elif ema_bearish and rsi_last < 47 and st_bearish:
            signal = "SELL"
        else:
            signal = "NEUTRAL"

        # Logic for strength/confidence
        ema_diff = abs(fast - slow)
        ema_strength = min(ema_diff / atr_last * 20, 40) if atr_last > 0 else 0
        rsi_strength = 0
        if signal == "BUY":
            rsi_strength = max(min((rsi_last - 50) * 1.5, 30), 0)
        elif signal == "SELL":
            rsi_strength = max(min((50 - rsi_last) * 1.5, 30), 0)
        st_strength = 30 if (signal == "BUY" and st_bullish) or (signal == "SELL" and st_bearish) else 0
        confidence = round(ema_strength + rsi_strength + st_strength, 1)

        risk_atr = atr_last * 1.2
        reward_atr = atr_last * 2.4
        if signal == "BUY":
            target = price + reward_atr
            stop_loss = price - risk_atr
        elif signal == "SELL":
            target = price - reward_atr
            stop_loss = price + risk_atr
        else:
            target = price
            stop_loss = price

        return {
            "price": round(price, 2),
            "signal": signal,
            "ema_fast": round(fast, 2),
            "ema_slow": round(slow, 2),
            "rsi": round(rsi_last, 1),
            "atr": round(atr_last, 2),
            "supertrend": round(st_last, 2),
            "st_dir": "BULLISH" if st_dir == 1 else "BEARISH" if st_dir == -1 else "N/A",
            "confidence": confidence,
            "target": round(target, 2),
            "stop_loss": round(stop_loss, 2),
            "time": str(last_time),
            "ema_strength": ema_strength,
            "rsi_strength": rsi_strength,
            "st_strength": st_strength
        }

    except Exception as e:
        return {"signal": "ERROR", "message": f"Server Error: {str(e)}"}

# ────────────────────────────────────────────────
# Reasoning Endpoint
# ────────────────────────────────────────────────
@app.get("/reasoning")
def get_reasoning():
    pred = predict()
    if "signal" in pred and pred["signal"] in ["ERROR", "DATA ERROR", "CLOSED"]:
         return {"reasoning": pred["message"]}

    signal = pred.get("signal", "NEUTRAL")
    price = pred.get("price", 0)
    ema_fast = pred.get("ema_fast", 0)
    ema_slow = pred.get("ema_slow", 0)
    rsi = pred.get("rsi", 0)
    st_dir = pred.get("st_dir", "N/A")

    lines = [f"Signal: {signal} @ {price}"]
    
    if signal == "BUY":
        lines.append("Bullish Confluence:")
        lines.append(f"1. EMA 9 ({ema_fast}) > EMA 21 ({ema_slow})")
        lines.append(f"2. RSI {rsi} indicates momentum")
        lines.append(f"3. Supertrend is {st_dir}")
    elif signal == "SELL":
        lines.append("Bearish Confluence:")
        lines.append(f"1. EMA 9 ({ema_fast}) < EMA 21 ({ema_slow})")
        lines.append(f"2. RSI {rsi} shows weakness")
        lines.append(f"3. Supertrend is {st_dir}")
    else:
        lines.append("Market Indecision:")
        lines.append(f"EMA spread is tight or RSI {rsi} is neutral.")
    
    return {"reasoning": "\n".join(lines)}

# ────────────────────────────────────────────────
# Chart Endpoint
# ────────────────────────────────────────────────
@app.get("/chart")
def chart(interval: str = Query("5m")):
    try:
        valid_intervals = ["1m", "5m", "15m"]
        if interval not in valid_intervals:
            interval = "5m"

        # No custom session here either!
        data = yf.download("^NSEI", period="5d", interval=interval, progress=False)
        
        if data.empty:
            return {"error": "No chart data available from Yahoo"}

        data = data.tail(200)

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        close = data["Close"]
        high = data["High"]
        low = data["Low"]

        ema_fast = close.ewm(span=9, adjust=False).mean()
        ema_slow = close.ewm(span=21, adjust=False).mean()

        # Supertrend
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_st = tr.rolling(window=10).mean()
        hl2 = (high + low) / 2
        upper_band = hl2 + (3.0 * atr_st)
        lower_band = hl2 - (3.0 * atr_st)

        supertrend = pd.Series(index=data.index, dtype=float)
        direction = pd.Series(index=data.index, dtype=int)
        supertrend.iloc[0] = lower_band.iloc[0]
        direction.iloc[0] = 1

        for i in range(1, len(data)):
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
            
            if pd.isna(supertrend.iloc[i]):
                 supertrend.iloc[i] = supertrend.iloc[i-1]

        candles = []
        ema_fast_data = []
        ema_slow_data = []
        supertrend_data = []

        for index, row in data.iterrows():
            time_unix = int(index.timestamp())
            candles.append({
                "time": time_unix,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"])
            })
            
            ef_val = float(ema_fast.loc[index]) if pd.notna(ema_fast.loc[index]) else None
            es_val = float(ema_slow.loc[index]) if pd.notna(ema_slow.loc[index]) else None
            st_val = float(supertrend.loc[index]) if pd.notna(supertrend.loc[index]) else None

            if ef_val: ema_fast_data.append({"time": time_unix, "value": ef_val})
            if es_val: ema_slow_data.append({"time": time_unix, "value": es_val})
            if st_val: supertrend_data.append({"time": time_unix, "value": st_val})

        return {
            "candles": candles,
            "ema_fast": ema_fast_data,
            "ema_slow": ema_slow_data,
            "supertrend": supertrend_data
        }

    except Exception as e:
        return {"error": str(e)}

# ────────────────────────────────────────────────
# Dashboard UI
# ────────────────────────────────────────────────
@app.get("/app", response_class=HTMLResponse)
def app_ui():
    return """
<html>
<head>
<title>NIFTY Intraday Predictor</title>
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.min.js"></script>
<style>
body {background:#0b0c10;color:white;font-family:'Segoe UI',sans-serif;margin:0;padding:0;text-align:center;}
header {padding:15px;background:#1f2833;display:flex;flex-direction:column;align-items:center;}
header h2 {margin:8px;font-size:26px;}
#signal {font-size:48px;margin:10px;font-weight:bold;}
p {margin:6px;font-size:18px;}
#interval {margin:15px 0;padding:8px;font-size:18px;}
#chart {width:96%;max-width:1100px;height:480px;margin:20px auto;background:#0b0c10;}
#error-msg {color:#ff4444;font-size:18px;margin:10px;font-weight:bold;}
#confidence-bar {background:#333;border-radius:10px;height:20px;width:200px;margin:10px auto;position:relative;}
#confidence-fill {background:linear-gradient(to right,red,yellow,lime);height:100%;border-radius:10px;transition:width 0.5s;}
#confidence-text {position:absolute;top:0;left:50%;transform:translateX(-50%);color:white;font-weight:bold;}
pre {white-space:pre-wrap;font-family:monospace;color:#aaffcc;margin:10px auto;font-size:14px;line-height:1.4;max-width:700px;background:#1a1f2e;padding:12px;border-radius:8px;text-align:left;}
</style>
</head>
<body>
<header>
<h2>NIFTY Intraday Predictor (EMA + RSI + Supertrend)</h2>
<h1 id="signal">Loading...</h1>
<p id="price"></p>
<p id="indicators"></p>
<div id="confidence-bar">
    <div id="confidence-fill" style="width:0%;"></div>
    <span id="confidence-text">0%</span>
</div>
<p id="target"></p>
<p id="stop_loss"></p>

<pre id="reasoning-text">Loading reasoning...</pre>

<label for="interval">Chart Timeframe: </label>
<select id="interval" onchange="loadData()">
    <option value="1m">1 Minute</option>
    <option value="5m" selected>5 Minutes</option>
    <option value="15m">15 Minutes</option>
</select>
</header>

<div id="chart"></div>
<div id="error-msg"></div>

<script>
let chart, candleSeries, emaFastSeries, emaSlowSeries, supertrendSeries;

async function loadData() {
    const interval = document.getElementById("interval").value;
    const errorEl = document.getElementById("error-msg");
    errorEl.innerText = '';

    try {
        const predRes = await fetch("/");
        const pred = await predRes.json();

        const signalEl = document.getElementById("signal");
        signalEl.innerText = pred.signal || "ERROR";

        if (pred.signal === "BUY") signalEl.style.color = "lime";
        else if (pred.signal === "SELL") signalEl.style.color = "red";
        else signalEl.style.color = "#aaa";

        // If data error, show message and stop
        if (pred.signal === "DATA ERROR" || pred.signal === "ERROR") {
             errorEl.innerText = pred.message;
             return;
        }

        document.getElementById("price").innerText = `Current Price: ${pred.price || '—'}`;
        
        document.getElementById("indicators").innerText = 
            `EMA 9/21: ${pred.ema_fast || '-'} / ${pred.ema_slow || '-'} | RSI: ${pred.rsi || '-'} | Supertrend: ${pred.supertrend || '-'} (${pred.st_dir || '-'})`;

        const conf = pred.confidence || 0;
        document.getElementById("confidence-fill").style.width = `${conf}%`;
        document.getElementById("confidence-text").innerText = `${conf}%`;
        document.getElementById("target").innerText = `Target: ${pred.target || '—'}`;
        document.getElementById("stop_loss").innerText = `Stop Loss: ${pred.stop_loss || '—'}`;

        const reasonRes = await fetch("/reasoning");
        const reasonData = await reasonRes.json();
        document.getElementById("reasoning-text").innerText = reasonData.reasoning || "No reasoning available";

        const chartRes = await fetch(`/chart?interval=${interval}`);
        const chartData = await chartRes.json();
        
        if (chartData.error) throw new Error(chartData.error);

        const chartDiv = document.getElementById("chart");
        if (!chart) {
            chart = LightweightCharts.createChart(chartDiv, {
                width: chartDiv.clientWidth,
                height: 480,
                layout: { backgroundColor: '#0b0c10', textColor: 'white' },
                grid: { vertLines: { color: '#333' }, horzLines: { color: '#333' } },
                timeScale: { timeVisible: true, secondsVisible: false }
            });
            candleSeries = chart.addCandlestickSeries();
            emaFastSeries = chart.addLineSeries({ color: 'yellow', lineWidth: 2 });
            emaSlowSeries = chart.addLineSeries({ color: 'orange', lineWidth: 2 });
            supertrendSeries = chart.addLineSeries({ color: 'purple', lineWidth: 2 });
        }

        if (chartData.candles && chartData.candles.length > 0) {
            candleSeries.setData(chartData.candles);
            emaFastSeries.setData(chartData.ema_fast);
            emaSlowSeries.setData(chartData.ema_slow);
            supertrendSeries.setData(chartData.supertrend);
            chart.timeScale().fitContent();
        }

    } catch (e) {
        errorEl.innerText = "App Error: " + e.message;
    }
}

loadData();
setInterval(loadData, 60000);
</script>
</body>
</html>
"""
