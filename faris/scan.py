"""Market scan: candidate list -> Yahoo daily data -> Faris criteria per stock."""
from __future__ import annotations

import pandas as pd

from . import indicators as ind

# Finviz filter codes for the two lists in section 3 of the guide.
# They are editable in the app; open the generated URL in a browser to confirm.
PRESETS = {
    "momentum": {
        "label": "فلتر الزخم (Finviz)",
        "filters": "exch_nasd,cap_microunder,sh_price_u5,sh_float_u20,sh_avgvol_o100,"
                   "sh_relvol_o2,sh_curvol_o200,ta_change_u",
        "note": "NASDAQ · Market Cap تحت 300M · السعر تحت 5$ · Float تحت 20M · "
                "Avg Volume فوق 100K · Rel Volume فوق 2 · Current Volume فوق 200K · Change Up",
    },
    "anchor": {
        "label": "فلتر الارتكاز (Finviz)",
        "filters": "exch_nasd,cap_microunder,sh_price_u5,sh_float_u20,sh_avgvol_o100,ta_perf_4wdown",
        "note": "NASDAQ · Market Cap تحت 300M · السعر تحت 5$ · Float تحت 20M · "
                "Avg Volume فوق 100K · Performance Month Down",
    },
}


def scan_row(ticker: str, d: pd.DataFrame, info: dict, short: dict | None, runner_mult: float) -> dict:
    close = d["Close"]
    price = float(close.iloc[-1])
    chg = (price / float(close.iloc[-2]) - 1) * 100 if len(d) > 1 else None
    r = ind.rsi(close).iloc[-1]
    m = ind.macd(close).dropna()
    macd_up = None
    if len(m) >= 6:
        h = m["hist"]
        cross = any(m["macd"].iloc[i] > m["signal"].iloc[i] and m["macd"].iloc[i - 1] <= m["signal"].iloc[i - 1]
                    for i in range(len(m) - 5, len(m)))
        macd_up = bool(cross or (h.iloc[-1] > h.iloc[-2] > h.iloc[-3]))
    s20, s50 = ind.sma(close, 20).iloc[-1], ind.sma(close, 50).iloc[-1]
    fr = ind.former_runner(d, mult=runner_mult) if len(d) > 30 else None
    low20 = float(d["Low"].tail(20).min())
    rs_date = None
    if "Stock Splits" in d.columns:
        rs = d["Stock Splits"][(d["Stock Splits"] > 0) & (d["Stock Splits"] < 1)]
        if not rs.empty:
            rs_date = rs.index[-1].date()
    flt = info.get("floatShares")
    return {
        "الرمز": ticker,
        "السعر": round(price, 4),
        "التغير %": None if chg is None else round(chg, 2),
        "RVOL": None if ind.rvol(d) is None else round(ind.rvol(d), 2),
        "الفلووت": flt,
        "القيمة السوقية": info.get("marketCap"),
        "RSI": None if pd.isna(r) else round(float(r), 1),
        "RSI 23-27": bool(not pd.isna(r) and 23 <= r <= 27),
        "تحت MA20/50": bool(price < s20 and price < s50) if not (pd.isna(s20) or pd.isna(s50)) else None,
        "MACD يتحسن": macd_up,
        "Former Runner": None if fr is None else fr["is_runner"],
        "صعود من قاع 20 يوم %": round((price / low20 - 1) * 100, 1) if low20 else None,
        "تقسيم عكسي (سنة)": rs_date,
        "شورت متاح IBKR": None if not short else short.get("available"),
        "CTB %": None if not short else short.get("fee_rate"),
    }


def score(row: dict, mode: str) -> int:
    """Count of guide criteria met. Not a buy signal; only for sorting the list."""
    s = 0
    flt = row.get("الفلووت")
    if flt and flt < 20e6:
        s += 1
    if row.get("Former Runner"):
        s += 1
    if row.get("تقسيم عكسي (سنة)"):
        s += 1
    if mode == "momentum":
        s += int((row.get("RVOL") or 0) >= 2) + int((row.get("التغير %") or 0) > 0)
    else:
        s += int(bool(row.get("RSI 23-27"))) + int(bool(row.get("تحت MA20/50"))) + int(bool(row.get("MACD يتحسن")))
        s -= int((row.get("صعود من قاع 20 يوم %") or 0) >= 50)  # already ran: do not chase
    return s
