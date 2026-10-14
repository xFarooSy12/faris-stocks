"""Run with:  python -m pytest -q tests"""
import numpy as np
import pandas as pd
import pytest

from faris import data, indicators as ind

# StockCharts' RSI textbook example. Their table shows 70.53 for the first value
# because the spreadsheet rounds the averages; the exact value is 70.464.
CLOSES = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
          45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64]


def test_rsi_first_value_exact():
    diffs = np.diff(CLOSES[:15])
    g, l = diffs[diffs > 0].sum() / 14, -diffs[diffs < 0].sum() / 14
    assert ind.rsi(pd.Series(CLOSES)).iloc[14] == pytest.approx(100 - 100 / (1 + g / l))
    assert ind.rsi(pd.Series(CLOSES)).iloc[14] == pytest.approx(70.464, abs=1e-3)


def test_rsi_matches_stockcharts_within_rounding():
    got = ind.rsi(pd.Series(CLOSES)).iloc[14:].round(2).tolist()
    published = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97]
    assert all(abs(a - b) < 0.1 for a, b in zip(got, published))


def test_macd_matches_loop():
    s = pd.Series(np.random.default_rng(1).normal(0, 1, 200).cumsum() + 50)

    def ema_loop(x, n):
        a, out = 2 / (n + 1), [x[0]]
        for v in x[1:]:
            out.append(a * v + (1 - a) * out[-1])
        return np.array(out)

    line = ema_loop(s.values, 12) - ema_loop(s.values, 26)
    sig = ema_loop(line, 9)
    m = ind.macd(s)
    assert np.allclose(m["macd"], line) and np.allclose(m["signal"], sig)


def _bars(closes):
    c = pd.Series(closes, dtype=float, index=pd.bdate_range("2025-01-01", periods=len(closes)))
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 100_000.0})


def test_former_runner_detects_double():
    d = _bars([1.0] * 40 + [2.5] + [1.2] * 40)
    fr = ind.former_runner(d)
    assert fr["is_runner"] and fr["ratio"] > 2


def test_unfilled_gap_down():
    d = _bars([5.0] * 10 + [3.0] * 10)  # gap from ~4.95 down to ~3.03, never filled
    gaps = ind.unfilled_gaps_above(d, 3.0)
    assert len(gaps) == 1 and gaps[0]["from"] == pytest.approx(3.03) and gaps[0]["to"] == pytest.approx(4.95)


def test_reverse_split_ratio():
    s = pd.Series([0.1, 2.0, 0.05], index=pd.to_datetime(["2023-01-05", "2024-02-01", "2025-03-10"]))
    rs = data.reverse_splits(s)
    assert rs["ratio"].tolist() == ["1:20", "1:10"]


def test_ibkr_available_parse():
    assert data.parse_available(">10000000") == 10_000_000
    assert data.parse_available("0") == 0


def test_support_falls_back_to_recent_low_at_new_lows():
    from faris import rules
    d = _bars(list(np.linspace(6.0, 1.95, 300)))  # steady decline: no swing low below price
    res = rules.evaluate({}, d, "day", d, None, data.reverse_splits(pd.Series(dtype=float)),
                         {"short_low": 50_000, "runner_mult": 2.0, "near_support_pct": 8.0})
    sup = res["plan"]["support"]
    assert sup["fallback"] and sup["level"] == pytest.approx(d["Low"].tail(20).min())
    assert any(c.label == "الدعم (يومي، تقريبي)" for c in res["checks"])
    assert f"{sup['level']:.2f}" in res["kind"]
