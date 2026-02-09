from fastapi import FastAPI
import yfinance as yf

app = FastAPI()

def get_signal():
    data = yf.download("^NSEI", period="1d", interval="5m")
    close = data["Close"]

    if len(close) < 2:
        return "NO TRADE", 0.5, float(close.iloc[-1])

    if close.iloc[-1] > close.iloc[-2]:
        return "BUY", 0.6, float(close.iloc[-1])
    else:
        return "SELL", 0.6, float(close.iloc[-1])

@app.get("/")
def home():
    signal, confidence, price = get_signal()
    return {
        "price": price,
        "signal": signal,
        "confidence": confidence
    }
