from fastapi import FastAPI
import yfinance as yf

app = FastAPI()

@app.get("/")
def home():
    try:
        data = yf.download("^NSEI", period="1d", interval="5m")

        if data.empty:
            return {"error": "No market data available"}

        close = float(data["Close"].iloc[-1])
        prev = float(data["Close"].iloc[-2])

        signal = "BUY" if close > prev else "SELL"

        return {
            "price": close,
            "signal": signal,
            "confidence": 0.6
        }

    except Exception as e:
        return {"error": str(e)}
