from fastapi import FastAPI
import yfinance as yf

app = FastAPI()

@app.get("/")
def home():
    data = yf.download("^NSEI", period="1d", interval="5m")
    close = float(data["Close"].iloc[-1])

    return {
        "price": close,
        "signal": "BUY" if close > float(data["Close"].iloc[-2]) else "SELL",
        "confidence": 0.6
    }
