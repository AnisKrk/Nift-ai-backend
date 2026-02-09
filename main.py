from fastapi import FastAPI
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
# Candle Data Endpoint
# -----------------------------
@app.get("/chart")
def chart():
    try:
        data = yf.download("^NSEI", period="1d", interval="5m", progress=False)

        if data.empty:
            return {"error": "No chart data available"}

        # Handle multi-index columns
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
# Dashboard UI
# -----------------------------
@app.get("/app", response_class=HTMLResponse)
def app_ui():
    return """
<html>
<head>
<title>NIFTY AI Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>

<body style="background:black;color:white;text-align:center;font-family:sans-serif">
<h2>NIFTY Intraday AI</h2>

<h1 id="signal">Loading...</h1>
<p id="price"></p>
<p id="confidence"></p>

<canvas id="chart" style="width:100%;max-width:600px;"></canvas>

<script>
async function loadData() {

  // Fetch prediction
  const predRes = await fetch("/");
  const pred = await predRes.json();

  // Update signal + color
  const signalEl = document.getElementById("signal");
  signalEl.innerText = pred.signal;
  signalEl.style.color = pred.signal === "BUY" ? "green" : "red";

  document.getElementById("price").innerText = "Price: " + pred.price;
  document.getElementById("confidence").innerText = "Confidence: " + pred.confidence;

  // Fetch chart data
  const res = await fetch("/chart");
  const data = await res.json();

  const labels = data.candles.map(c => c.time);
  const prices = data.candles.map(c => c.close);

  new Chart(document.getElementById("chart"), {
      type: "line",
      data: {
          labels: labels,
          datasets: [{
              label: "NIFTY",
              data: prices,
              borderColor: 'white',
              borderWidth: 2,
              fill: false
          }]
      },
      options: {
          responsive: true,
          plugins: { legend: { labels: { color: "white" } } },
          scales: {
              x: { ticks: { color: "white" } },
              y: { ticks: { color: "white" } }
          }
      }
  });
}

// Initial load + auto-refresh every 60s
loadData();
setInterval(loadData, 60000);

</script>
</body>
</html>
"""
