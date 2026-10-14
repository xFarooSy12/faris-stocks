"""Free data sources.

* Yahoo Finance (through the yfinance library): prices, company info, float,
  official short interest, and the split history.
* Interactive Brokers public short-stock file (ftp3.interactivebrokers.com,
  user "shortstock", no password): shares available to short at IBKR and the
  borrow fee rate. This is what Faris means by "short available" - it is a
  single broker's inventory, not the official short interest.
"""
from __future__ import annotations

import io
import re
from ftplib import FTP

import pandas as pd
import requests
import yfinance as yf

# timeframe label -> (yfinance interval, history period)
# Yahoo limits: 1m bars go back 7 days, 5m-30m bars 60 days, 1h bars 730 days.
TIMEFRAMES = {
    "day": ("1d", "2y"),
    "week": ("1wk", "10y"),
    "1h": ("1h", "730d"),
    "30m": ("30m", "60d"),
    "15m": ("15m", "60d"),
    "5m": ("5m", "60d"),
    "1m": ("1m", "7d"),
}

TV_INTERVAL = {"day": "D", "week": "W", "1h": "60", "30m": "30", "15m": "15", "5m": "5", "1m": "1"}
TV_EXCHANGE = {"NMS": "NASDAQ", "NCM": "NASDAQ", "NGM": "NASDAQ", "NAS": "NASDAQ",
               "NYQ": "NYSE", "ASE": "AMEX", "PCX": "AMEX", "BTS": "AMEX"}


def history(ticker: str, timeframe: str) -> pd.DataFrame:
    interval, period = TIMEFRAMES[timeframe]
    df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False,
                                   prepost=False, actions=False)
    if df.empty:
        return df
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None and interval in ("1d", "1wk"):
        df.index = df.index.tz_localize(None)
    return df


def info(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    try:
        data = dict(t.info or {})
    except Exception:
        data = {}
    try:  # fast_info is a lighter endpoint, used as a fallback for price / market cap
        fi = t.fast_info
        data.setdefault("_fast_last", fi.get("lastPrice"))
        data.setdefault("_fast_mcap", fi.get("marketCap"))
        data.setdefault("_fast_shares", fi.get("shares"))
    except Exception:
        pass
    return data


def splits(ticker: str) -> pd.Series:
    s = yf.Ticker(ticker).splits
    if s is None or s.empty:
        return pd.Series(dtype=float)
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    return s


def reverse_splits(split_series: pd.Series) -> pd.DataFrame:
    """Yahoo stores a 1-for-10 reverse split as 0.1."""
    r = split_series[split_series < 1]
    if r.empty:
        return pd.DataFrame(columns=["date", "ratio"])
    return pd.DataFrame({"date": r.index, "ratio": [f"1:{round(1 / v):g}" for v in r.values]}) \
        .sort_values("date", ascending=False).reset_index(drop=True)


# --------------------------------------------------------- IBKR short file

def ibkr_short_table() -> pd.DataFrame:
    """Download and parse IBKR's public US short-stock availability file."""
    buf = io.BytesIO()
    with FTP("ftp3.interactivebrokers.com", timeout=30) as ftp:
        ftp.login("shortstock", "")
        ftp.retrbinary("RETR usa.txt", buf.write)
    text = buf.getvalue().decode("utf-8", errors="replace")
    header, rows = None, []
    for line in text.splitlines():
        if line.startswith("#SYM"):
            header = [h.strip("#").strip() for h in line.split("|")]
        elif line.startswith("#") or not line.strip():
            continue
        elif header:
            rows.append(line.split("|"))
    if not header:
        raise ValueError("IBKR file format not recognised")
    width = len(header)
    df = pd.DataFrame([r[:width] + [""] * (width - len(r)) for r in rows], columns=header)
    df = df.loc[:, [c for c in df.columns if c]]
    df["SYM"] = df["SYM"].str.strip().str.upper()
    return df.drop_duplicates("SYM").set_index("SYM")


def parse_available(v: str) -> float | None:
    """AVAILABLE can look like '12000' or '>10000000'."""
    if v is None:
        return None
    m = re.search(r"[\d.]+", str(v))
    return float(m.group()) if m else None


def ibkr_short_for(table: pd.DataFrame, ticker: str) -> dict | None:
    key = ticker.upper().replace("-", " ")
    for k in (ticker.upper(), key, ticker.upper().replace("-", ".")):
        if k in table.index:
            row = table.loc[k]
            fee = pd.to_numeric(row.get("FEERATE"), errors="coerce")
            return {"available_raw": str(row.get("AVAILABLE", "")).strip(),
                    "available": parse_available(row.get("AVAILABLE")),
                    "fee_rate": None if pd.isna(fee) else float(fee)}
    return None


# ------------------------------------------------------------- Finviz scan

FINVIZ_URL = "https://finviz.com/screener.ashx"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def finviz_url(filters: str) -> str:
    return f"{FINVIZ_URL}?v=111&f={filters}"


def finviz_tickers(filters: str, max_pages: int = 10) -> list[str]:
    """Read tickers from Finviz's free screener pages (20 per page).

    Finviz has no free API; this reads the public HTML page and may break if
    Finviz changes its layout or blocks the request.
    """
    found: list[str] = []
    for page in range(max_pages):
        r = requests.get(FINVIZ_URL, params={"v": "111", "f": filters, "r": 1 + 20 * page},
                         headers=_UA, timeout=20)
        r.raise_for_status()
        new = [t for t in dict.fromkeys(re.findall(r"quote\.ashx\?t=([A-Z][A-Z0-9.\-]{0,9})", r.text))
               if t not in found]
        if not new:
            break
        found.extend(new)
        if len(new) < 20:
            break
    return found


def daily_batch(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Daily bars plus split events for many tickers in one request."""
    raw = yf.download(tickers, period=period, interval="1d", auto_adjust=False, actions=True,
                      group_by="ticker", threads=True, progress=False)
    out = {}
    for t in tickers:
        try:
            df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
        except KeyError:
            continue
        df = df.dropna(subset=["Close"])
        if not df.empty:
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            out[t] = df
    return out
