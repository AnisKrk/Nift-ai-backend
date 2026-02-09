from fastapi import FastAPI
import yfinance as yf

app = FastAPI()

@app.get("/")
def home():
    try:
        data = yf.download("^NSEI", period="1d", interval="5m", progress=False)

        if data.empty:
            return {"error": "No market data available"}

        # Always extract scalar safely
        close_series = data["Close"]

        # If multi-column → take first column
        if hasattr(close_series, "iloc") and len(close_series.shape) > 1:
            close_series = close_series.iloc[:, 0]

        close = float(close_series.iloc[-1])
        prev = float(close_series.iloc[-2])

        signal = "BUY" if close > prev else "SELL"

        return {
            "price": round(close, 2),
            "signal": signal,
            "confidence": 0.6
        }

    except Exception as e:
        return {"error": str(e)}

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
