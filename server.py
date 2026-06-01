from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import asyncio, time, logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

TICKER_MAP = {"GC=F":"GCUSD","SI=F":"SIUSD","GLD":"GLD","SLV":"SLV","DX-Y.NYB":"DX-Y.NYB","TLT":"TLT","IEF":"IEF","TIP":"TIP","LQD":"LQD","HYG":"HYG","^TNX":"TNX","^TYX":"TYX","^FVX":"FVX","^GSPC":"^GSPC","^NDX":"^NDX","SOXX":"SOXX","^VIX":"^VIX","NVDA":"NVDA","TSM":"TSM"}
_cache = {"data":{}, "ts":0, "fetching":False}
CACHE_TTL = 60

async def fetch_market_data():
    loop = asyncio.get_event_loop()
    def _sync():
        tickers = yf.Tickers(" ".join(TICKER_MAP.keys()))
        out = {}
        ts_now = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        for yf_sym, dash_key in TICKER_MAP.items():
            try:
                info = tickers.tickers[yf_sym].fast_info
                price = getattr(info, "last_price", None)
                prev = getattr(info, "previous_close", None)
                if price is None:
                    hist = tickers.tickers[yf_sym].history(period="2d", interval="1d")
                    if not hist.empty:
                        price = float(hist["Close"].iloc[-1])
                        prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
                if price is not None:
                    change = round(price - prev, 4) if prev else 0
                    pct = round((change / prev) * 100, 4) if prev else 0
                    out[dash_key] = {"price":round(price,4),"prev":round(prev,4) if prev else None,"change":change,"pct":pct,"ts":ts_now}
                else:
                    out[dash_key] = None
            except Exception as e:
                logger.warning(f"Failed {yf_sym}: {e}")
                out[dash_key] = None
        if out.get("GCUSD"):
            out["XAUUSD"] = dict(out["GCUSD"])
        return out
    return await loop.run_in_executor(None, _sync)

async def refresh_cache():
    if _cache["fetching"] or time.time() - _cache["ts"] < CACHE_TTL:
        return
    _cache["fetching"] = True
    try:
        _cache["data"] = await fetch_market_data()
        _cache["ts"] = time.time()
    finally:
        _cache["fetching"] = False

@app.on_event("startup")
async def startup():
    await refresh_cache()
    asyncio.create_task(auto_loop())

async def auto_loop():
    while True:
        await asyncio.sleep(CACHE_TTL)
        await refresh_cache()

@app.get("/api/market")
async def get_market():
    await refresh_cache()
    return {"ok":True,"ts":time.strftime("%Y-%m-%d %H:%M:%S UTC",time.gmtime(_cache["ts"])),"cache_age_s":round(time.time()-_cache["ts"],1),"data":_cache["data"]}

@app.get("/api/health")
async def health():
    return {"ok":True,"cache_age_s":round(time.time()-_cache["ts"],1),"symbols":len(_cache["data"])}

@app.get("/")
async def root():
    return {"service":"Macro Dashboard API v2.0"}