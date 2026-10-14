"""Technical indicators and price-structure helpers.

Formulas follow the standard definitions used by TradingView so the numbers
can be checked against a TradingView chart:
  * RSI: Wilder's RSI (RMA smoothing, seeded with a simple average).
  * MACD: EMA(12) - EMA(26), signal = EMA(9) of MACD, histogram = MACD - signal.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI. First average = simple mean of the first n changes."""
    close = close.astype(float)
    delta = close.diff()
    gain = delta.clip(lower=0).to_numpy()
    loss = (-delta.clip(upper=0)).to_numpy()
    out = np.full(len(close), np.nan)
    if len(close) <= n:
        return pd.Series(out, index=close.index)
    avg_g = np.nanmean(gain[1 : n + 1])
    avg_l = np.nanmean(loss[1 : n + 1])

    def _val(g, l):
        if l == 0:
            return 100.0 if g > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + g / l)

    out[n] = _val(avg_g, avg_l)
    for i in range(n + 1, len(close)):
        avg_g = (avg_g * (n - 1) + gain[i]) / n
        avg_l = (avg_l * (n - 1) + loss[i]) / n
        out[i] = _val(avg_g, avg_l)
    return pd.Series(out, index=close.index)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP that resets every trading day (for intraday bars)."""
    tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
    day = df.index.normalize() if isinstance(df.index, pd.DatetimeIndex) else df.index
    pv = (tp * df["Volume"]).groupby(day).cumsum()
    vv = df["Volume"].groupby(day).cumsum()
    return pv / vv.replace(0, np.nan)


# ---------------------------------------------------------------- structure

def pivots(df: pd.DataFrame, k: int = 3) -> tuple[pd.Series, pd.Series]:
    """Swing lows / highs: a bar whose low (high) is the extreme of the k bars on each side."""
    lo, hi = df["Low"], df["High"]
    win = 2 * k + 1
    is_low = lo == lo.rolling(win, center=True).min()
    is_high = hi == hi.rolling(win, center=True).max()
    return lo[is_low], hi[is_high]


def _cluster(levels: list[float], tol: float) -> list[tuple[float, int]]:
    """Group price levels that sit within `tol` (fraction) of each other."""
    out: list[list[float]] = []
    for p in sorted(levels):
        if out and abs(p - np.mean(out[-1])) / np.mean(out[-1]) <= tol:
            out[-1].append(p)
        else:
            out.append([p])
    return [(float(np.mean(c)), len(c)) for c in out]


def support_resistance(df: pd.DataFrame, price: float, k: int = 3, tol: float = 0.03):
    """Nearest swing-based support below and resistance above the price.

    Returns dicts {level, touches} or None. These are mechanical estimates and
    must be confirmed on the chart.
    """
    lows, highs = pivots(df, k)
    sup = [c for c in _cluster(lows.tolist(), tol) if c[0] < price]
    res = [c for c in _cluster(highs.tolist(), tol) if c[0] > price]
    support = max(sup, key=lambda c: c[0]) if sup else None
    resist = min(res, key=lambda c: c[0]) if res else None
    fmt = lambda c: None if c is None else {"level": c[0], "touches": c[1]}
    return fmt(support), fmt(resist)


def unfilled_gaps_above(df: pd.DataFrame, price: float, max_n: int = 3) -> list[dict]:
    """Down-gaps (today's high < yesterday's low) above the price that were never fully filled."""
    hi, lo = df["High"].to_numpy(), df["Low"].to_numpy()
    idx = df.index
    gaps = []
    for i in range(1, len(df)):
        if hi[i] < lo[i - 1]:
            top = lo[i - 1]
            later_high = hi[i + 1 :].max() if i + 1 < len(df) else hi[i]
            bottom = max(hi[i], later_high)
            if bottom < top and bottom > price:
                gaps.append({"date": idx[i], "from": float(bottom), "to": float(top)})
    gaps.sort(key=lambda g: g["from"])
    return gaps[:max_n]


def former_runner(daily: pd.DataFrame, lookback: int = 252, base: int = 20, mult: float = 2.0):
    """Largest move inside the lookback: high / lowest low of the previous `base` bars.

    A ratio >= mult (2.0 = +100%) marks the stock as a "Former Runner".
    """
    d = daily.tail(lookback + base)
    if len(d) <= base:
        return None
    prior_low = d["Low"].rolling(base, min_periods=base).min().shift(1)
    ratio = (d["High"] / prior_low).tail(lookback)
    if ratio.dropna().empty:
        return None
    when = ratio.idxmax()
    return {"ratio": float(ratio.max()), "date": when, "is_runner": bool(ratio.max() >= mult)}


def rvol(daily: pd.DataFrame, n: int = 63) -> float | None:
    """Last bar volume / average volume of the n bars before it (about 3 months)."""
    v = daily["Volume"].dropna()
    if len(v) < 5:
        return None
    avg = v.iloc[-(n + 1) : -1].mean()
    return float(v.iloc[-1] / avg) if avg else None
