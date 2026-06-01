
"""
Macro Core Dashboard v2.0 — Market Data Proxy Server
FastAPI + TradingView scanner API backend with 60s cache
Deployed on Render — serves /api/market to public Dashboard HTML
v2.4 — Added UKOIL + DJI
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import time
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Macro Dashboard API", version="2.4")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

TV_SYMBOL_MAP = {
    "OANDA:XAUUSD":  "XAUUSD",
    "TVC:SILVER":    "SIUSD",
    "FX:UKOIL":      "UKOIL",
    "AMEX:GLD":      "GLD",
    "AMEX:SLV":      "SLV",
    "TVC:DXY":       "DX-Y.NYB",
    "NASDAQ:TLT":    "TLT",
    "NASDAQ:IEF":    "IEF",
    "NASDAQ:TIP":    "TIP",
    "NASDAQ:LQD":    "LQD",
    "NASDAQ:HYG":    "HYG",
    "TVC:US10Y":     "TNX",
    "TVC:US30Y":     "TYX",
    "TVC:US05Y":     "FVX",
    "SP:SPX":        "^GSPC",
    "TVC:DJI":       "^DJI",
    "CBOE:VIX":      "^VIX",
    "NASDAQ:SOXX":   "SOXX",
    "NASDAQ:NVDA":   "NVDA",
    "NYSE:TSM":      "TSM",
}

TV_SCAN_URL = "https://scanner.tradingview.com/global/scan"

TV_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/json",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}

_cache = {"data": {}, "ts": 0, "fetching": False}
CACHE_TTL = 60


async def fetch_market_data() -> dict:
    ts_now = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    tv_symbols = list(TV_SYMBOL_MAP.keys())

    payload = {
        "symbols": {"tickers": tv_symbols},
        "columns": ["close", "change", "change_abs"]
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(TV_SCAN_URL, headers=TV_HEADERS, json=payload)
        resp.raise_for_status()
        raw = resp.json()

    data_list = raw.get("data", [])
    out = {}

    for item in data_list:
        tv_sym = item.get("s", "")
        dash_key = TV_SYMBOL_MAP.get(tv_sym)
        if dash_key is None:
            continue
        try:
            d = item.get("d", [])
            price      = d[0] if len(d) > 0 else None
            change_pct = d[1] if len(d) > 1 else None
            change_abs = d[2] if len(d) > 2 else None

            if price is not None:
                if change_pct is not None and change_pct != 0:
                    prev_close = price / (1 + change_pct / 100)
                elif change_abs is not None:
                    prev_close = price - change_abs
                else:
                    prev_close = price

                out[dash_key] = {
                    "price":  round(float(price), 4),
                    "prev":   round(float(prev_close), 4),
                    "change": round(float(change_abs), 4) if change_abs else 0,
                    "pct":    round(float(change_pct), 4) if change_pct else 0,
                    "ts":     ts_now,
                    "src":    "TradingView",
                }
            else:
                out[dash_key] = None
        except Exception as e:
            logger.warning(f"Parse failed {tv_sym}: {e}")
            out[dash_key] = None

    for tv_sym, dash_key in TV_SYMBOL_MAP.items():
        if dash_key not in out:
            out[dash_key] = None

    if out.get("XAUUSD"):
        out["GCUSD"] = dict(out["XAUUSD"])

    ok = sum(1 for v in out.values() if v is not None)
    logger.info(f"TradingView fetch OK: {ok}/{len(out)} symbols")
    return out


async def refresh_cache():
    if _cache["fetching"]:
        return
    if time.time() - _cache["ts"] < CACHE_TTL:
        return
    _cache["fetching"] = True
    try:
        data = await fetch_market_data()
        _cache["data"] = data
        _cache["ts"] = time.time()
    except Exception as e:
        logger.error(f"Cache refresh failed: {e}")
    finally:
        _cache["fetching"] = False


@app.on_event("startup")
async def startup_event():
    await refresh_cache()
    asyncio.create_task(auto_refresh_loop())


async def auto_refresh_loop():
    while True:
        await asyncio.sleep(CACHE_TTL)
        await refresh_cache()


@app.get("/api/market")
async def get_market():
    await refresh_cache()
    return {
        "ok": True,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(_cache["ts"])),
        "cache_age_s": round(time.time() - _cache["ts"], 1),
        "source": "TradingView",
        "data": _cache["data"],
    }

@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "cache_age_s": round(time.time() - _cache["ts"], 1),
        "symbols": len(_cache["data"]),
        "source": "TradingView",
    }

@app.get("/")
async def root():
    return {"service": "Macro Dashboard API v2.4", "source": "TradingView"}

if os.path.exists("index.html"):
    from fastapi.responses import FileResponse
    @app.get("/dashboard")
    async def dashboard():
        return FileResponse("index.html")