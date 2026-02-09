herefrom fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
import pandas as pd
import traceback
from indicators import calculate_ema, calculate_rsi, calculate_supertrend, clean_val
from market_data import get_market_data

app = FastAPI()

# Global Error Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_msg = "".join(traceback.format_exception(None, exc, exc.__traceback__))
    return JSONResponse(status_code=500, content={"signal": "CRITICAL ERROR", "message": str(exc), "trace": error_msg})

@app.get("/")
async def get_dashboard_data(interval: str = "5m"):
    # VALIDATE INTERVAL
    if interval not in ["1m", "5m", "15m", "30m", "1h"]:
        interval = "5m"
        
    result, error = await get_market_data(interval)
    if error:
        return {"signal": "DATA ERROR", "message": error}
    
    data = result["data"]
    status = result["status"]
    
    # --- CALCULATIONS ---
    close = data["Close"]
    
    ema_fast = calculate_ema(close, 9)
    ema_slow = calculate_ema(close, 21)
    rsi = calculate_rsi(close)
    supertrend, direction, atr = calculate_supertrend(data)
    
    # Get last values
    price = float(close.iloc[-1])
    fast = float(ema_fast.iloc[-1])
    slow = float(ema_slow.iloc[-1])
    rsi_last = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50.0
    st_last = float(supertrend.iloc[-1])
    st_dir_val = direction.iloc[-1]
    atr_last = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else 0.0
    
    # Generate Signal
    ema_bullish = fast > slow
    ema_bearish = fast < slow
    st_bullish = st_dir_val == 1
    st_bearish = st_dir_val == -1
    
    if ema_bullish and rsi_last > 53 and st_bullish:
        signal = "BUY"
    elif ema_bearish and rsi_last < 47 and st_bearish:
        signal = "SELL"
    else:
        signal = "NEUTRAL"
        
    # --- TARGET / STOP LOSS LOGIC (Restored) ---
    risk_atr = atr_last * 1.5   # Risk 1.5x ATR
    reward_atr = atr_last * 3.0 # Reward 3.0x ATR (1:2 Ratio)
    
    target = 0
    stop_loss = 0
    
    if signal == "BUY":
        target = price + reward_atr
        stop_loss = price - risk_atr
    elif signal == "SELL":
        target = price - reward_atr
        stop_loss = price + risk_atr
    else:
        # If neutral, show levels based on current price just for reference
        target = price + reward_atr
        stop_loss = price - risk_atr

    # --- CHART DATA PACKAGING ---
    chart_data = data.tail(300)
    candles = []
    volume_data = []
    ema_fast_data = []
    ema_slow_data = []
    supertrend_data = []
    
    for index, row in chart_data.iterrows():
        time_unix = int(index.timestamp())
        
        # Candle
        o, h, l, c = clean_val(float(row["Open"])), clean_val(float(row["High"])), clean_val(float(row["Low"])), clean_val(float(row["Close"]))
        if None not in [o, h, l, c]:
            candles.append({"time": time_unix, "open": o, "high": h, "low": l, "close": c})
            
            # Volume
            vol_color = "rgba(0, 150, 136, 0.5)" if c >= o else "rgba(255, 82, 82, 0.5)"
            v = clean_val(float(row["Volume"]))
            if v:
                volume_data.append({"time": time_unix, "value": v, "color": vol_color})

        # Indicators
        ef = clean_val(float(ema_fast.loc[index]))
        es = clean_val(float(ema_slow.loc[index]))
        st = clean_val(float(supertrend.loc[index]))
        
        if ef: ema_fast_data.append({"time": time_unix, "value": ef})
        if es: ema_slow_data.append({"time": time_unix, "value": es})
        if st: supertrend_data.append({"time": time_unix, "value": st})

    return {
        "signal": signal,
        "price": clean_val(round(price, 2)),
        "rsi": clean_val(round(rsi_last, 1)),
        "supertrend": clean_val(round(st_last, 2)),
        "st_dir": "BULLISH" if st_dir_val == 1 else "BEARISH",
        "market_status": status,
        "last_updated": result["last_updated"],
        "target": clean_val(round(target, 2)),
        "stop_loss": clean_val(round(stop_loss, 2)),
        "candles": candles,
        "volume": volume_data,
        "ema_fast": ema_fast_data,
        "ema_slow": ema_slow_data,
        "supertrend_line": supertrend_data
    }

@app.get("/app", response_class=HTMLResponse)
def app_ui():
    return """
<!DOCTYPE html>
<html>
<head>
<title>ProTrader NIFTY</title>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.min.js"></script>
<style>
/* PROFESSIONAL DARK THEME */
:root { --bg: #0b0c10; --panel: #1f2833; --text: #c5c6c7; --accent: #66fcf1; --green: #4caf50; --red: #ff5252; }
body { background: var(--bg); color: var(--text); font-family: 'Inter', system-ui, sans-serif; margin: 0; padding: 0; overflow-x: hidden; }

/* HEADER */
header { background: var(--panel); padding: 12px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #333; }
.logo { font-size: 18px; font-weight: 700; color: white; display: flex; align-items: center; gap: 10px; }
.status-dot { height: 10px; width: 10px; background-color: #555; border-radius: 50%; display: inline-block; }
.status-open { background-color: var(--green); box-shadow: 0 0 8px var(--green); animation: pulse 2s infinite; }
.status-closed { background-color: var(--red); }

@keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }

/* MAIN DASHBOARD */
.dashboard { padding: 15px; max-width: 1200px; margin: 0 auto; }

/* SIGNAL CARD */
.signal-card { background: var(--panel); padding: 20px; border-radius: 12px; text-align: center; margin-bottom: 15px; border: 1px solid #333; position: relative; }
#signal-text { font-size: 36px; font-weight: 900; margin: 5px 0; letter-spacing: 1px; }
.price-display { font-size: 20px; color: white; font-weight: 600; }
.refresh-btn { position: absolute; top: 15px; right: 15px; background: #333; border: none; color: white; padding: 8px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; }
.refresh-btn:hover { background: #444; }

/* METRICS GRID */
.metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 20px; }
.metric-box { background: #151920; padding: 12px; border-radius: 8px; text-align: center; border: 1px solid #2a2a2a; }
.metric-label { font-size: 11px; color: #888; text-transform: uppercase; }
.metric-value { font-size: 15px; font-weight: bold; color: var(--accent); margin-top: 4px; }

/* RISK REWARD BOX */
.rr-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 20px; }
.rr-box { background: #151920; padding: 10px; border-radius: 6px; text-align: center; border: 1px solid #333; }
.rr-label { color: #aaa; font-size: 12px; }
.rr-val { font-size: 18px; font-weight: bold; color: white; }

/* CHART CONTAINER */
#chart-container { position: relative; height: 500px; width: 100%; border-radius: 12px; overflow: hidden; border: 1px solid #333; }
#floating-tooltip {
    position: absolute; display: none; padding: 8px; box-sizing: border-box; font-size: 12px; text-align: left; z-index: 1000; top: 12px; left: 12px;
    pointer-events: none; border: 1px solid #444; border-radius: 4px; background: rgba(31, 40, 51, 0.9); color: white; box-shadow: 0 2px 5px rgba(0,0,0,0.5);
}

/* FOOTER */
.timer-bar { display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: #666; margin-top: 5px; padding: 0 10px; }
select { background: #333; color: white; border: none; padding: 5px; border-radius: 4px; }
</style>
</head>
<body>

<header>
    <div class="logo">
        <span id="market-status" class="status-dot"></span>
        NIFTY AI PRO
    </div>
    <div style="font-size: 12px; color: #aaa;" id="last-updated">Updating...</div>
</header>

<div class="dashboard">
    <div class="signal-card">
        <button class="refresh-btn" onclick="loadData(true)">↻ Refresh</button>
        <div id="signal-text">LOADING</div>
        <div class="price-display" id="price-text">---</div>
    </div>

    <div class="rr-grid">
        <div class="rr-box" style="border-color: #26a69a;">
            <div class="rr-label">TARGET</div>
            <div class="rr-val" id="target-val" style="color: #26a69a;">--</div>
        </div>
        <div class="rr-box" style="border-color: #ef5350;">
            <div class="rr-label">STOP LOSS</div>
            <div class="rr-val" id="sl-val" style="color: #ef5350;">--</div>
        </div>
    </div>

    <div class="metrics">
        <div class="metric-box">
            <div class="metric-label">RSI (14)</div>
            <div class="metric-value" id="rsi-val">--</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Supertrend</div>
            <div class="metric-value" id="st-val">--</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Trend</div>
            <div class="metric-value" id="trend-val">--</div>
        </div>
    </div>

    <div id="chart-container">
        <div id="floating-tooltip"></div>
    </div>
    
    <div class="timer-bar">
        <div>
            Interval: 
            <select id="interval-select" onchange="changeInterval()">
                <option value="1m">1 Min</option>
                <option value="5m" selected>5 Min</option>
                <option value="15m">15 Min</option>
                <option value="30m">30 Min</option>
                <option value="1h">1 Hour</option>
            </select>
        </div>
        <span id="next-candle-timer">Next Candle: --:--</span>
    </div>
</div>

<script>
// --- CHART SETUP ---
const chartContainer = document.getElementById('chart-container');
const chart = LightweightCharts.createChart(chartContainer, {
    layout: { background: { color: '#0b0c10' }, textColor: '#d1d4dc' },
    grid: { vertLines: { color: '#1f2833' }, horzLines: { color: '#1f2833' } },
    rightPriceScale: { borderColor: 'rgba(197, 198, 199, 0.2)', autoScale: true },
    timeScale: { borderColor: 'rgba(197, 198, 199, 0.2)', timeVisible: true, minBarSpacing: 5, rightOffset: 5 },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
});

const candleSeries = chart.addCandlestickSeries({ upColor: '#26a69a', downColor: '#ef5350', borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350' });
const volumeSeries = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: '', scaleMargins: { top: 0.8, bottom: 0 } });
const supertrendSeries = chart.addLineSeries({ color: '#ae22e0', lineWidth: 2, title: 'Supertrend' });
const emaFastSeries = chart.addLineSeries({ color: '#fdd835', lineWidth: 1, title: 'EMA 9' });
const emaSlowSeries = chart.addLineSeries({ color: '#ff9800', lineWidth: 1, title: 'EMA 21' });

let isFirstLoad = true;

// FIX: Handle Interval Change
function changeInterval() {
    isFirstLoad = true; // Reset zoom on interval change
    loadData(true);
}

async function loadData(manual = false) {
    if(manual) document.querySelector('.refresh-btn').innerText = "Loading...";
    
    // FIX: Get value from dropdown
    const interval = document.getElementById("interval-select").value;
    
    try {
        const res = await fetch(`/?interval=${interval}`);
        const d = await res.json();
        
        if(d.signal === "DATA ERROR") { alert(d.message); return; }

        // 1. UPDATE METRICS
        const statusEl = document.getElementById("market-status");
        statusEl.className = d.market_status === "OPEN" ? "status-dot status-open" : "status-dot status-closed";
        document.getElementById("last-updated").innerText = "Updated: " + d.last_updated;

        const sigEl = document.getElementById("signal-text");
        sigEl.innerText = d.signal;
        sigEl.style.color = d.signal === "BUY" ? "#26a69a" : (d.signal === "SELL" ? "#ef5350" : "#ffffff");
        
        document.getElementById("price-text").innerText = "₹" + d.price;
        document.getElementById("rsi-val").innerText = d.rsi;
        document.getElementById("st-val").innerText = d.supertrend;
        document.getElementById("trend-val").innerText = d.st_dir;
        document.getElementById("trend-val").style.color = d.st_dir === "BULLISH" ? "#26a69a" : "#ef5350";

        // RESTORED TARGETS
        document.getElementById("target-val").innerText = d.target || "--";
        document.getElementById("sl-val").innerText = d.stop_loss || "--";

        // 2. UPDATE CHART
        if(d.candles.length > 0) {
            candleSeries.setData(d.candles);
            volumeSeries.setData(d.volume);
            emaFastSeries.setData(d.ema_fast);
            emaSlowSeries.setData(d.ema_slow);
            supertrendSeries.setData(d.supertrend_line);
            
            if(isFirstLoad) {
                chart.timeScale().fitContent();
                isFirstLoad = false;
            }
        }
        
    } catch(e) {
        console.error(e);
    } finally {
        if(manual) document.querySelector('.refresh-btn').innerText = "↻ Refresh";
    }
}

// --- TOOLTIP LOGIC ---
const toolTip = document.getElementById('floating-tooltip');
chart.subscribeCrosshairMove(param => {
    if (param.time === undefined || param.point === undefined) {
        toolTip.style.display = 'none';
        return;
    }
    const candle = param.seriesData.get(candleSeries);
    const st = param.seriesData.get(supertrendSeries);
    const vol = param.seriesData.get(volumeSeries);
    if(candle) {
        toolTip.style.display = 'block';
        toolTip.innerHTML = `
            <div style="font-weight:bold; margin-bottom:4px; color: ${candle.close >= candle.open ? '#26a69a' : '#ef5350'}">
                O:${candle.open.toFixed(2)} H:${candle.high.toFixed(2)} L:${candle.low.toFixed(2)} C:${candle.close.toFixed(2)}
            </div>
            <div>Vol: ${(vol ? (vol.value/1000).toFixed(1) + 'k' : 'N/A')}</div>
            <div>ST: ${st ? st.toFixed(2) : '-'}</div>
        `;
    }
});

// RESIZE HANDLER
window.addEventListener('resize', () => {
    chart.applyOptions({ width: chartContainer.clientWidth });
});

loadData();
setInterval(loadData, 60000);
</script>
</body>
</html>
"""
