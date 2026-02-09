from fastapi import FastAPI, Query
import yfinance as yf
from fastapi.responses import HTMLResponse
import pandas as pd
from datetime import datetime

app = FastAPI()

# -----------------------------
# Prediction Endpoint (EMA + RSI + ATR improvements)
# -----------------------------
@app.get("/")
def predict():
    try:
        # Download latest intraday data (5m default for signal)
        data = yf.download("^NSEI", period="1d", interval="5m", progress=False)

        if data.empty or len(data) < 30:
            return {"error": "Insufficient market data"}

        # Flatten multi-index if present
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # Time awareness (NSE opens at 9:15 IST = 3:45 UTC)
        last_time = data.index[-1]  # UTC timezone
        market_open_utc = last_time.replace(hour=3, minute=45)  # UTC equivalent of 9:15 IST
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

        # ATR(14) for realistic target & stop
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=14).mean()
        atr_last = float(atr.iloc[-1])

        # Enhanced signal logic with RSI filter
        ema_bullish = fast > slow
        ema_bearish = fast < slow

        if ema_bullish and rsi_last > 53:          # slight bias above 50 to filter noise
            signal = "BUY"
        elif ema_bearish and rsi_last < 47:
            signal = "SELL"
        else:
            signal = "NEUTRAL"

        # Confidence (0–100): combination of EMA separation + RSI alignment
        ema_diff = abs(fast - slow)
        ema_strength = min(ema_diff / atr_last * 30, 60)   # cap at 60
        rsi_strength = 0
        if signal == "BUY":
            rsi_strength = max(min((rsi_last - 50) * 2, 40), 0)
        elif signal == "SELL":
            rsi_strength = max(min((50 - rsi_last) * 2, 40), 0)
        confidence = round(ema_strength + rsi_strength, 1)

        # ATR-based target & stop (1.2× risk : 2.4× reward ≈ 1:2 RR)
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
            "confidence": confidence,
            "target": round(target, 2),
            "stop_loss": round(stop_loss, 2),
            "time": str(last_time)
        }

    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# Candle Data Endpoint (unchanged, but added length check)
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
        for index, row in data.iterrows():
            candles.append({
                "time": str(index),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"])
            })

        return {"candles": candles}

    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# Dashboard UI — added RSI & ATR display + neutral color + error handling in JS
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
</style>
</head>

<body>
<header>
<h2>NIFTY Intraday Predictor (EMA + RSI)</h2>
<h1 id="signal">Loading...</h1>
<p id="price"></p>
<p id="indicators"></p>
<p id="confidence"></p>
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

<script>
let chart;
let candleSeries;

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
        } else {
            signalEl.style.color = "#aaa";
        }

        document.getElementById("price").innerText = `Current Price: ${pred.price || '—'}`;
        document.getElementById("indicators").innerText = 
            `EMA 9 / 21: ${pred.ema_fast || '—'} / ${pred.ema_slow || '—'}   |   RSI: ${pred.rsi || '—'}   |   ATR: ${pred.atr || '—'}`;
        document.getElementById("confidence").innerText = `Confidence: ${pred.confidence || '—'}%`;
        document.getElementById("target").innerText = `Target: ${pred.target || '—'}`;
        document.getElementById("stop_loss").innerText = `Stop Loss: ${pred.stop_loss || '—'}`;

        if (pred.message) {
            document.getElementById("confidence").innerText += ` (${pred.message})`;
        }

        const chartRes = await fetch(`/chart?interval=${interval}`);
        if (!chartRes.ok) throw new Error(`Chart API failed: ${chartRes.status}`);
        const data = await chartRes.json();

        if (data.error) throw new Error(data.error);

        const candlesticks = data.candles.map(c => ({
            time: new Date(c.time).getTime() / 1000,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close
        }));

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
        }

        candleSeries.setData(candlesticks);
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
