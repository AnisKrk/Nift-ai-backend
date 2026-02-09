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

        # Simple target and stop loss logic
        multiplier = 2  # risk-reward ratio
        if signal == "BUY":
            target = price + diff * multiplier
            stop_loss = price - diff
        else:
            target = price - diff * multiplier
            stop_loss = price + diff

        return {
            "price": round(price, 2),
            "signal": signal,
            "ema_fast": round(fast, 2),
            "ema_slow": round(slow, 2),
            "confidence": confidence,
            "target": round(target, 2),
            "stop_loss": round(stop_loss, 2)
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
# Dashboard UI — Modern Layout + Target/Stop Loss
# -----------------------------
@app.get("/app", response_class=HTMLResponse)
def app_ui():
    return """
<html>
<head>
<title>NIFTY AI Dashboard</title>
<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
<style>
body { background-color:#0b0c10; color:white; font-family:'Segoe UI', sans-serif; margin:0; padding:0; text-align:center;}
header { padding:10px; background-color:#1f2833; display:flex; flex-direction:column; align-items:center; }
header h2 { margin:5px; font-size:24px; }
header #signal { font-size:36px; margin:5px; }
header p { margin:2px; }
#interval { margin:10px 0; padding:5px; font-size:16px; }
#chart { width:95%; max-width:900px; height:400px; margin:auto; }
</style>
</head>

<body>
<header>
<h2>NIFTY Intraday AI</h2>
<h1 id="signal">Loading...</h1>
<p id="price"></p>
<p id="confidence"></p>
<p id="target"></p>
<p id="stop_loss"></p>

<label for="interval">Timeframe: </label>
<select id="interval" onchange="loadData()">
    <option value="1m">1 Minute</option>
    <option value="5m" selected>5 Minutes</option>
    <option value="15m">15 Minutes</option>
</select>
</header>

<div id="chart"></div>

<script>
let chart;
let candleSeries;

async function loadData() {
    const interval = document.getElementById("interval").value;

    // Fetch prediction
    const predRes = await fetch("/");
    const pred = await predRes.json();

    const signalEl = document.getElementById("signal");
    signalEl.innerText = pred.signal;
    signalEl.style.color = pred.signal === "BUY" ? "lime" : "red";

    document.getElementById("price").innerText = "Current Price: " + pred.price;
    document.getElementById("confidence").innerText = "Confidence: " + pred.confidence;
    document.getElementById("target").innerText = "Target Price: " + pred.target;
    document.getElementById("stop_loss").innerText = "Stop Loss: " + pred.stop_loss;

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

    const chartDiv = document.getElementById("chart");
    if(!chart) {
        chart = LightweightCharts.createChart(chartDiv, {
            width: chartDiv.clientWidth,
            height: 400,
            layout: { backgroundColor: '#0b0c10', textColor: 'white' },
            grid: { vertLines: { color: '#444' }, horzLines: { color: '#444' } },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
            rightPriceScale: { borderColor: '#555' },
            timeScale: { borderColor: '#555' }
        });
        candleSeries = chart.addCandlestickSeries({
            upColor: 'lime',
            downColor: 'red',
            borderVisible: true,
            wickUpColor: 'lime',
            wickDownColor: 'red'
        });
    }

    candleSeries.setData(candlesticks);
}

loadData();
setInterval(loadData, 60000);

window.addEventListener('resize', () => {
    if(chart) chart.applyOptions({ width: document.getElementById("chart").clientWidth });
});
</script>

</body>
</html>
"""
