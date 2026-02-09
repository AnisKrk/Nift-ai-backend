from fastapi import FastAPI, Query
import yfinance as yf
from fastapi.responses import HTMLResponse
import pandas as pd
from datetime import datetime, timedelta

app = FastAPI()

# -----------------------------
# Prediction Endpoint (added Supertrend, market hours check)
# -----------------------------
@app.get("/")
def predict():
    try:
        # Download latest intraday data (5m default for signal)
        data = yf.download("^NSEI", period="1d", interval="5m", progress=False)

        if data.empty or len(data) < 30:
            return {"error": "Market closed or insufficient data", "signal": "CLOSED"}

        # Flatten multi-index if present
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # Full market hours check (NSE: 9:15–15:30 IST = 3:45–10:00 UTC)
        last_time = data.index[-1]  # UTC
        now_utc = datetime.utcnow()
        market_open_utc = now_utc.replace(hour=3, minute=45)
        market_close_utc = now_utc.replace(hour=10, minute=0)
        if now_utc < market_open_utc or now_utc > market_close_utc:
            return {"signal": "CLOSED", "message": "Market is closed (NSE: 9:15 AM - 3:30 PM IST)"}

        # Time awareness for early session noise
        market_open_utc = last_time.replace(hour=3, minute=45)
        if last_time < market_open_utc + pd.Timedelta(minutes=25):
            return {
                "signal": "WAIT",
                "message": "Market too young — avoid first 25 minutes (high noise)",
                "price": round(float(data["Close"].iloc[-1]), 2),
                "time": str(last_time)
            }

        close = data["Close"]
        high = data["High"]
        low = data["Low"]

        # EMA
        ema_fast = close.ewm(span=9, adjust=False).mean()
        ema_slow = close.ewm(span=21, adjust=False).mean()

        price = float(close.iloc[-1])
        fast = float(ema_fast.iloc[-1])
        slow = float(ema_slow.iloc[-1])

        # RSI(14)
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        rsi_last = float(rsi.iloc[-1])

        # ATR(14)
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=14).mean()
        atr_last = float(atr.iloc[-1])

        # Supertrend (10,3) - common for Nifty intraday
        st_period = 10
        st_multiplier = 3.0
        hl2 = (high + low) / 2
        atr_st = tr.rolling(window=st_period).mean()
        upper_band = hl2 + (st_multiplier * atr_st)
        lower_band = hl2 - (st_multiplier * atr_st)

        # Initialize Supertrend
        supertrend = pd.Series(index=data.index, dtype=float)
        direction = pd.Series(index=data.index, dtype=int)  # 1 up, -1 down
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

        st_last = float(supertrend.iloc[-1])
        st_dir = direction.iloc[-1]  # 1 bullish, -1 bearish

        # Enhanced signal: EMA + RSI + Supertrend confirmation
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

        # Confidence: add Supertrend alignment
        ema_diff = abs(fast - slow)
        ema_strength = min(ema_diff / atr_last * 20, 40)  # adjusted for more factors
        rsi_strength = 0
        if signal == "BUY":
            rsi_strength = max(min((rsi_last - 50) * 1.5, 30), 0)
        elif signal == "SELL":
            rsi_strength = max(min((50 - rsi_last) * 1.5, 30), 0)
        st_strength = 30 if (signal == "BUY" and st_bullish) or (signal == "SELL" and st_bearish) else 0
        confidence = round(ema_strength + rsi_strength + st_strength, 1)

        # ATR-based target & stop
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
            "time": str(last_time)
        }

    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# Candle Data Endpoint (added EMA and Supertrend series data)
# -----------------------------
@app.get("/chart")
def chart(interval: str = Query("5m")):
    try:
        valid_intervals = ["1m", "5m", "15m"]
        if interval not in valid_intervals:
            interval = "5m"

        data = yf.download("^NSEI", period="1d", interval=interval, progress=False)
        if data.empty or len(data) < 5:
            return {"error": "No chart data available"}

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        candles = []
        ema_fast_data = []
        ema_slow_data = []
        supertrend_data = []

        close = data["Close"]
        high = data["High"]
        low = data["Low"]

        # EMA
        ema_fast = close.ewm(span=9, adjust=False).mean()
        ema_slow = close.ewm(span=21, adjust=False).mean()

        # Supertrend (same as predict, but for chart interval)
        st_period = 10
        st_multiplier = 3.0
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_st = tr.rolling(window=st_period).mean()
        hl2 = (high + low) / 2
        upper_band = hl2 + (st_multiplier * atr_st)
        lower_band = hl2 - (st_multiplier * atr_st)

        supertrend = pd.Series(index=data.index, dtype=float)
        direction = pd.Series(index=data.index, dtype=int)
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

        for index, row in data.iterrows():
            time_unix = int(index.timestamp())
            candles.append({
                "time": time_unix,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"])
            })
            ema_fast_data.append({"time": time_unix, "value": float(ema_fast.loc[index]) if pd.notna(ema_fast.loc[index]) else None})
            ema_slow_data.append({"time": time_unix, "value": float(ema_slow.loc[index]) if pd.notna(ema_slow.loc[index]) else None})
            st_val = float(supertrend.loc[index]) if pd.notna(supertrend.loc[index]) else None
            supertrend_data.append({"time": time_unix, "value": st_val})

        # Filter out None values for lines
        ema_fast_data = [d for d in ema_fast_data if d["value"] is not None]
        ema_slow_data = [d for d in ema_slow_data if d["value"] is not None]
        supertrend_data = [d for d in supertrend_data if d["value"] is not None]

        return {
            "candles": candles,
            "ema_fast": ema_fast_data,
            "ema_slow": ema_slow_data,
            "supertrend": supertrend_data
        }

    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# Dashboard UI — added confidence bar, EMA/Supertrend on chart, alert sound, closed handling
# -----------------------------
@app.get("/app", response_class=HTMLResponse)
def app_ui():
    return """
<html>
<head>
<title>NIFTY Intraday Predictor</title>
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.min.js"></script>
<style>
body { background-color:#0b0c10; color:white; font-family:'Segoe UI', sans-serif; margin:0; padding:0; text-align:center;}
header { padding:15px; background-color:#1f2833; display:flex; flex-direction:column; align-items:center; }
header h2 { margin:8px; font-size:26px; }
header #signal { font-size:48px; margin:10px; font-weight:bold; }
header p { margin:6px; font-size:18px; }
#interval { margin:15px 0; padding:8px; font-size:18px; }
#chart { width:96%; max-width:1100px; height:480px; margin:20px auto; background-color:#0b0c10; }
#error-msg { color: #ff4444; font-size: 18px; margin: 10px; font-weight:bold; }
#confidence-bar { background: #333; border-radius: 10px; height: 20px; width: 200px; margin: 10px auto; position: relative; }
#confidence-fill { background: linear-gradient(to right, red, yellow, lime); height: 100%; border-radius: 10px; transition: width 0.5s; }
#confidence-text { position: absolute; top: 0; left: 50%; transform: translateX(-50%); color: white; font-weight: bold; }
.closed { color: orange !important; }
</style>
</head>

<body>
<header>
<h2>NIFTY Intraday Predictor (EMA + RSI + Supertrend)</h2>
<h1 id="signal">Loading...</h1>
<p id="price"></p>
<p id="indicators"></p>
<div id="confidence-bar">
    <div id="confidence-fill" style="width: 0%;"></div>
    <span id="confidence-text">0%</span>
</div>
<p id="target"></p>
<p id="stop_loss"></p>

<label for="interval">Chart Timeframe: </label>
<select id="interval" onchange="loadData()">
    <option value="1m">1 Minute</option>
    <option value="5m" selected>5 Minutes</option>
    <option value="15m">15 Minutes</option>
</select>
</header>

<div id="chart"></div>
<div id="error-msg"></div>

<audio id="alert-sound" src="https://www.soundjay.com/buttons/beep-07.mp3" preload="auto"></audio>

<script>
let chart;
let candleSeries;
let emaFastSeries;
let emaSlowSeries;
let supertrendSeries;
let prevSignal = null;

async function loadData() {
    const interval = document.getElementById("interval").value;
    const errorEl = document.getElementById("error-msg");
    errorEl.innerText = '';

    try {
        const predRes = await fetch("/");
        if (!predRes.ok) throw new Error(`Prediction failed: ${predRes.status}`);
        const pred = await predRes.json();

        const signalEl = document.getElementById("signal");
        signalEl.innerText = pred.signal || "ERROR";
        
        if (pred.signal === "BUY") {
            signalEl.style.color = "lime";
        } else if (pred.signal === "SELL") {
            signalEl.style.color = "red";
        } else if (pred.signal === "CLOSED" || pred.signal === "WAIT") {
            signalEl.style.color = "orange";
        } else {
            signalEl.style.color = "#aaa";
        }

        document.getElementById("price").innerText = `Current Price: ${pred.price || '—'}`;
        document.getElementById("indicators").innerText = 
            `EMA 9 / 21: ${pred.ema_fast || '—'} / ${pred.ema_slow || '—'}   |   RSI: ${pred.rsi || '—'}   |   ATR: ${pred.atr || '—'}   |   Supertrend: \( {pred.supertrend || '—'} ( \){pred.st_dir || '—'})`;
        
        const conf = pred.confidence || 0;
        document.getElementById("confidence-fill").style.width = `${conf}%`;
        document.getElementById("confidence-text").innerText = `${conf}%`;

        document.getElementById("target").innerText = `Target: ${pred.target || '—'}`;
        document.getElementById("stop_loss").innerText = `Stop Loss: ${pred.stop_loss || '—'}`;

        if (pred.message) {
            document.getElementById("indicators").innerText += ` (${pred.message})`;
        }

        // Alert on signal change to BUY/SELL
        if (prevSignal !== null && prevSignal !== pred.signal && (pred.signal === "BUY" || pred.signal === "SELL")) {
            document.getElementById("alert-sound").play();
        }
        prevSignal = pred.signal;

        const chartRes = await fetch(`/chart?interval=${interval}`);
        if (!chartRes.ok) throw new Error(`Chart API failed: ${chartRes.status}`);
        const data = await chartRes.json();

        if (data.error) throw new Error(data.error);

        const chartDiv = document.getElementById("chart");
        if (!chart) {
            chart = LightweightCharts.createChart(chartDiv, {
                width: chartDiv.clientWidth,
                height: 480,
                layout: { backgroundColor: '#0b0c10', textColor: 'white' },
                grid: { vertLines: { color: '#333' }, horzLines: { color: '#333' } },
                crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
                rightPriceScale: { borderColor: '#555' },
                timeScale: { borderColor: '#555', timeVisible: true, secondsVisible: false }
            });
            candleSeries = chart.addCandlestickSeries({
                upColor: '#26a69a',
                downColor: '#ef5350',
                borderVisible: false,
                wickUpColor: '#26a69a',
                wickDownColor: '#ef5350'
            });
            emaFastSeries = chart.addLineSeries({ color: 'yellow', lineWidth: 2 });
            emaSlowSeries = chart.addLineSeries({ color: 'orange', lineWidth: 2 });
            supertrendSeries = chart.addLineSeries({ color: 'purple', lineWidth: 2 });
        }

        candleSeries.setData(data.candles);
        emaFastSeries.setData(data.ema_fast);
        emaSlowSeries.setData(data.ema_slow);
        supertrendSeries.setData(data.supertrend);
        chart.timeScale().fitContent();

    } catch (e) {
        errorEl.innerText = "Error: " + e.message;
        console.error(e);
    }
}

loadData();
setInterval(loadData, 60000);

window.addEventListener('resize', () => {
    if (chart) chart.applyOptions({ width: document.getElementById("chart").clientWidth });
});
</script>
</body>
</html>
    """
