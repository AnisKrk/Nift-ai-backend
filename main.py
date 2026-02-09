from fastapi import FastAPI, Query
import yfinance as yf
from fastapi.responses import HTMLResponse

app = FastAPI()

# -----------------------------
# Prediction Endpoint (EMA)
# -----------------------------
@app.get("/")
def predict():
    try:
        data = yf.download("^NSEI", period="1d", interval="5m", progress=False)

        if data.empty:
            return {"error": "No market data"}

        if hasattr(data.columns, "levels"):
            data.columns = data.columns.get_level_values(0)

        close = data["Close"]

        ema_fast = close.ewm(span=9).mean()
        ema_slow = close.ewm(span=21).mean()

        price = float(close.iloc[-1])
        fast = float(ema_fast.iloc[-1])
        slow = float(ema_slow.iloc[-1])

        signal = "BUY" if fast > slow else "SELL"

        diff = abs(fast - slow)
        confidence = min(round(diff / price * 100, 2), 100)

        return {
            "price": round(price, 2),
            "signal": signal,
            "ema_fast": round(fast, 2),
            "ema_slow": round(slow, 2),
            "confidence": confidence
        }

    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# Candle Data Endpoint with interval
# -----------------------------
@app.get("/chart")
def chart(interval: str = Query("5m")):
    try:
        data = yf.download("^NSEI", period="1d", interval=interval, progress=False)

        if data.empty:
            return {"error": "No chart data available"}

        if len(data["Close"].shape) > 1:
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
# Dashboard UI with Timeframe Selector
# -----------------------------
@app.get("/app", response_class=HTMLResponse)
def app_ui():
    return """
<html>
<head>
<title>NIFTY AI Dashboard</title>
<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
</head>

<body style="background:black;color:white;text-align:center;font-family:sans-serif">
<h2>NIFTY Intraday AI</h2>
<h1 id="signal">Loading...</h1>
<p id="price"></p>
<p id="confidence"></p>

<label for="interval">Timeframe: </label>
<select id="interval" onchange="loadData()">
    <option value="1m">1 Minute</option>
    <option value="5m" selected>5 Minutes</option>
    <option value="15m">15 Minutes</option>
</select>

<div id="chart" style="width:100%; height:400px; margin:auto;"></div>

<script>
async function loadData() {
    const interval = document.getElementById("interval").value;

    // Fetch prediction
    const predRes = await fetch("/");
    const pred = await predRes.json();

    // Update signal
    const signalEl = document.getElementById("signal");
    signalEl.innerText = pred.signal;
    signalEl.style.color = pred.signal === "BUY" ? "green" : "red";

    document.getElementById("price").innerText = "Price: " + pred.price;
    document.getElementById("confidence").innerText = "Confidence: " + pred.confidence;

    // Fetch chart data with selected interval
    const res = await fetch("/chart?interval=" + interval);
    const data = await res.json();

    const candlesticks = data.candles.map(c => ({
        time: new Date(c.time).getTime() / 1000,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close
    }));

    // Create chart
    const chartDiv = document.getElementById("chart");

    // Remove previous chart if exists
    if(window.chart) {
        window.chart.remove();
    }

    window.chart = LightweightCharts.createChart(chartDiv, {
        width: chartDiv.clientWidth,
        height: 400,
        layout: { backgroundColor: '#000000', textColor: 'white' },
        grid: { vertLines: { color: '#444' }, horzLines: { color: '#444' } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        rightPriceScale: { borderColor: '#555' },
        timeScale: { borderColor: '#555' }
    });

    const candleSeries = window.chart.addCandlestickSeries();
    candleSeries.setData(candlesticks);
}

// Initial load + auto-refresh every 60s
loadData();
setInterval(loadData, 60000);
</script>

</body>
</html>
"""
