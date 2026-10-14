"""Faris-method checklist.

Every rule below comes from the guide "دليل طريقة فارس" (section numbers in
comments). Thresholds marked "(app choice)" are not in the guide and can be
changed in the sidebar.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from . import indicators as ind

PASS, WARN, FAIL, INFO = "pass", "warn", "fail", "info"


@dataclass
class Check:
    group: str
    label: str
    status: str
    detail: str


def _num(x):
    try:
        x = float(x)
        return None if math.isnan(x) else x
    except (TypeError, ValueError):
        return None


def fmt_int(x):
    return "غير متاح" if x is None else f"{x:,.0f}"


def float_check(flt):
    # section 4: <20M acceptable, <5M strong and risky, ~1M very risky
    if flt is None:
        return Check("البيانات", "الفلووت", INFO, "غير متاح من Yahoo")
    if flt < 1.5e6:
        return Check("البيانات", "الفلووت", WARN, f"{fmt_int(flt)} - قريب من 1M: شديد الخطورة")
    if flt < 5e6:
        return Check("البيانات", "الفلووت", PASS, f"{fmt_int(flt)} - أقل من 5M: قوي وخطر")
    if flt < 20e6:
        return Check("البيانات", "الفلووت", PASS, f"{fmt_int(flt)} - أقل من 20M: مقبول للمضاربة")
    if flt < 50e6:
        return Check("البيانات", "الفلووت", WARN, f"{fmt_int(flt)} - بين 20M و50M")
    return Check("البيانات", "الفلووت", FAIL, f"{fmt_int(flt)} - فوق 50M")


def rsi_check(r, tf):
    # sections 22-23: RSI 23-27 = pressure alert, not a buy order; ~40 not preferred
    lab = f"RSI 14 ({tf})"
    if r is None:
        return Check("فني", lab, INFO, "بيانات غير كافية")
    if 23 <= r <= 27:
        return Check("فني", lab, PASS, f"{r:.1f} - داخل منطقة 23-27: إنذار ضغط، وليس أمر شراء")
    if r < 23:
        return Check("فني", lab, WARN, f"{r:.1f} - تحت 23: ضغط شديد، انتظر فشل الهبوط")
    if r <= 35:
        return Check("فني", lab, INFO, f"{r:.1f} - قريب من منطقة الضغط وليس داخلها")
    if r >= 38:
        return Check("فني", lab, WARN, f"{r:.1f} - حول 40 أو أعلى: جزء من الارتداد حصل")
    return Check("فني", lab, INFO, f"{r:.1f}")


def ma_check(close, s20, s30, s50, tf):
    # section 21: under MAs = pressure; reclaiming = improvement; failing at MA = weakness
    lab = f"المتوسطات 20/30/50 ({tf})"
    vals = [v for v in (s20, s30, s50) if v is not None]
    if len(vals) < 3:
        return Check("فني", lab, INFO, "بيانات غير كافية")
    above = sum(close > v for v in (s20, s30, s50))
    txt = f"MA20 {s20:.2f} · MA30 {s30:.2f} · MA50 {s50:.2f}"
    if above == 0:
        return Check("فني", lab, INFO, f"السعر تحت كل المتوسطات = ضغط. {txt}")
    if above == 3:
        return Check("فني", lab, PASS, f"السعر فوق كل المتوسطات. {txt}")
    return Check("فني", lab, PASS, f"السعر يستعيد بعض المتوسطات = بداية تحسن. {txt}")


def macd_check(m: pd.DataFrame, tf):
    # sections 22-23: MACD starts easing or gives a positive crossover
    lab = f"MACD ({tf})"
    m = m.dropna()
    if len(m) < 6:
        return Check("فني", lab, INFO, "بيانات غير كافية")
    h = m["hist"]
    cross = any((m["macd"].iloc[i] > m["signal"].iloc[i]) and (m["macd"].iloc[i - 1] <= m["signal"].iloc[i - 1])
                for i in range(len(m) - 5, len(m)))
    rising = h.iloc[-1] > h.iloc[-2] > h.iloc[-3]
    v = f"MACD {m['macd'].iloc[-1]:.3f} · Signal {m['signal'].iloc[-1]:.3f}"
    if cross:
        return Check("فني", lab, PASS, f"تقاطع إيجابي خلال آخر 5 شموع. {v}")
    if rising:
        return Check("فني", lab, PASS, f"الهيستوجرام يتحسن آخر شمعتين. {v}")
    return Check("فني", lab, WARN, f"لا يوجد تحسن واضح بعد. {v}")


def candle_check(df: pd.DataFrame, tf):
    # section 23: hammer / lower wick / engulfing at support
    lab = f"شمعة إيجابية ({tf})"
    if len(df) < 2:
        return Check("فني", lab, INFO, "بيانات غير كافية")
    o, h, l, c = (df[k].iloc[-1] for k in ("Open", "High", "Low", "Close"))
    po, pc = df["Open"].iloc[-2], df["Close"].iloc[-2]
    body = abs(c - o)
    rng = h - l
    lower = min(o, c) - l
    if rng > 0 and lower >= 2 * max(body, rng * 0.05) and c >= l + rng * 0.5:
        return Check("فني", lab, PASS, "آخر شمعة لها ذيل سفلي طويل (Hammer): امتصاص بيع محتمل")
    if pc < po and c > o and c >= po and o <= pc:
        return Check("فني", lab, PASS, "آخر شمعة ابتلاعية صاعدة (Engulfing)")
    return Check("فني", lab, INFO, "لا توجد شمعة ارتداد واضحة في آخر شمعة")


def evaluate(info: dict, tf_df: pd.DataFrame, tf: str, daily: pd.DataFrame,
             short: dict | None, rsplits: pd.DataFrame, params: dict) -> dict:
    checks: list[Check] = []
    price = _num(tf_df["Close"].iloc[-1]) if not tf_df.empty else None
    price = price or _num(info.get("currentPrice")) or _num(info.get("_fast_last"))
    mcap = _num(info.get("marketCap")) or _num(info.get("_fast_mcap"))
    flt = _num(info.get("floatShares"))

    # ---- section 3: Finviz-style filters
    if price is not None:
        checks.append(Check("البيانات", "السعر تحت 5$", PASS if price < 5 else FAIL, f"${price:,.2f}"))
    if mcap is not None:
        checks.append(Check("البيانات", "القيمة السوقية تحت 300M", PASS if mcap < 300e6 else FAIL,
                            f"${mcap / 1e6:,.1f}M"))
    checks.append(float_check(flt))

    avg_vol = _num(info.get("averageVolume"))
    if avg_vol is None and len(daily) > 20:
        avg_vol = float(daily["Volume"].tail(63).mean())
    if avg_vol is not None:
        checks.append(Check("البيانات", "متوسط الفوليوم فوق 100K", PASS if avg_vol > 100_000 else FAIL,
                            fmt_int(avg_vol)))

    rv = ind.rvol(daily) if len(daily) > 5 else None
    if rv is not None:
        checks.append(Check("البيانات", "الفوليوم النسبي RVOL (يومي)", PASS if rv >= 2 else INFO,
                            f"{rv:.2f}x - " + ("غير طبيعي ويستحق مراقبة، وليس دخولاً" if rv >= 2 else "عادي")))

    # ---- section 4: short available (helper factor, not a buy signal)
    if short and short.get("available") is not None:
        low = short["available"] <= params["short_low"]
        checks.append(Check("البيانات", "الشورت المتاح (IBKR)", PASS if low else INFO,
                            f"{short['available_raw']} سهم - " + ("قليل: عامل مساعد وليس إشارة شراء" if low else "ليس قليلاً")))
    else:
        checks.append(Check("البيانات", "الشورت المتاح (IBKR)", INFO, "غير متاح"))

    # ---- reverse split = speculation catalyst, high risk
    if not rsplits.empty:
        last = rsplits.iloc[0]
        days = (pd.Timestamp.now().normalize() - pd.Timestamp(last["date"]).normalize()).days
        checks.append(Check("البيانات", "آخر تقسيم عكسي", WARN if days <= 365 else INFO,
                            f"{pd.Timestamp(last['date']).date()} بنسبة {last['ratio']} (قبل {days} يوم) - محفز مضاربة عالي الخطورة"))
    else:
        checks.append(Check("البيانات", "آخر تقسيم عكسي", INFO, "لا يوجد تقسيم عكسي في بيانات Yahoo"))

    # ---- section 16 / 5: Former Runner
    fr = ind.former_runner(daily, mult=params["runner_mult"]) if len(daily) > 30 else None
    if fr:
        pct = (fr["ratio"] - 1) * 100
        checks.append(Check("السلوك", "Former Runner (آخر سنة)", PASS if fr["is_runner"] else INFO,
                            f"أكبر صعود {pct:,.0f}% بتاريخ {pd.Timestamp(fr['date']).date()}"))

    # ---- technical (selected timeframe) sections 21-23
    close = tf_df["Close"]
    r = ind.rsi(close)
    m = ind.macd(close)
    s20, s30, s50 = (_num(ind.sma(close, n).iloc[-1]) for n in (20, 30, 50))
    r_last = _num(r.iloc[-1])
    checks.append(rsi_check(r_last, tf))
    checks.append(ma_check(close.iloc[-1], s20, s30, s50, tf))
    checks.append(macd_check(m, tf))
    checks.append(candle_check(tf_df, tf))

    if tf in ("1h", "30m", "15m", "5m", "1m") and len(tf_df) > 1:
        vw = ind.session_vwap(tf_df).iloc[-1]
        above = close.iloc[-1] > vw
        checks.append(Check("فني", f"VWAP ({tf})", PASS if above else WARN,
                            f"{vw:.2f} - " + ("السعر فوق الفواب" if above else "السعر تحت الفواب")))

    # ---- entry discipline: sections 24, 29 (do not chase after +50%)
    plan = {}
    if len(daily) > 25 and price:
        low20 = float(daily["Low"].tail(20).min())
        run = (price / low20 - 1) * 100
        st = FAIL if run >= 50 else WARN if run >= 20 else PASS
        txt = {FAIL: "لا تطارد: انتظر Retest أو سحب سيولة",
               WARN: "صعود 20-50%: احذر المطاردة",
               PASS: "لم يبتعد كثيراً عن القاع"}[st]
        checks.append(Check("الدخول", "الصعود من قاع 20 يوم", st, f"{run:,.0f}% من {low20:.2f} - {txt}"))

        # search all loaded daily history (about 2 years), not only the last year
        sup, res = ind.support_resistance(daily, price)
        if sup is None:
            # price is at or near its lowest level: no confirmed swing low below it.
            # Fall back to the recent 20-day low and mark it unconfirmed (app choice).
            sup = {"level": low20, "touches": 1, "fallback": True}
        plan["support"], plan["resistance"] = sup, res
        dist = (price - sup["level"]) / price * 100
        if sup.get("fallback"):
            checks.append(Check("الدخول", "الدعم (يومي، تقريبي)", WARN,
                                f"لا يوجد دعم مؤكد تحت السعر في آخر سنتين؛ السهم عند أدنى مستوياته. "
                                f"أقرب مرجع = قاع 20 يوم {low20:.2f} (على بعد {dist:.1f}%) وهو غير مؤكد: "
                                f"انتظر أن يثبت فوقه أو يسحب السيولة تحته ثم يسترده"))
        else:
            near = dist <= params["near_support_pct"]
            checks.append(Check("الدخول", "الدعم (يومي، تقريبي)", PASS if near else WARN,
                                f"دعم {sup['level']:.2f} ({sup['touches']} لمسة) على بعد {dist:.1f}%"))
        if res:
            dist_r = (res["level"] - price) / price * 100
            checks.append(Check("الدخول", "المقاومة الأولى (يومي، تقريبي)", WARN if dist_r < 3 else INFO,
                                f"{res['level']:.2f} على بعد {dist_r:.1f}%" + (" - الدخول تحت مقاومة مباشرة دخول غلط" if dist_r < 3 else "")))
        gaps = ind.unfilled_gaps_above(daily.tail(500), price)
        plan["gaps"] = gaps
        if gaps:
            g = " · ".join(f"{x['from']:.2f}-{x['to']:.2f}" for x in gaps)
            checks.append(Check("الدخول", "فجوات غير مغطاة فوق السعر", INFO, f"{g} - هدف محتمل وليس وعداً"))

    # ---- suggested type (section 2)
    day_chg = None
    if len(daily) > 1:
        day_chg = (daily["Close"].iloc[-1] / daily["Close"].iloc[-2] - 1) * 100
    d_rsi = _num(ind.rsi(daily["Close"]).iloc[-1]) if len(daily) > 20 else None
    d_s50 = _num(ind.sma(daily["Close"], 50).iloc[-1]) if len(daily) > 50 else None
    if rv is not None and rv >= 2 and day_chg is not None and day_chg > 0:
        kind = "زخم: يتحرك اليوم بفوليوم غير طبيعي. إذا لم تدخل أول موجة 5 دقائق، اصرف النظر."
    elif d_rsi is not None and d_rsi <= 35 and d_s50 is not None and price < d_s50:
        sp = plan.get("support")
        where = ""
        if sp:
            where = (f" الدعم: {sp['level']:.2f}" + (" (قاع حديث غير مؤكد)" if sp.get("fallback") else "") + ".")
        kind = "مرشح ارتكاز: مضغوط وتحت المتوسطات. ليس دخولاً الآن، تابعه حتى يصل الدعم ويثبت." + where
    else:
        kind = "غير محدد: لا يطابق وصف الزخم ولا الارتكاز بوضوح الآن."

    return {"checks": checks, "plan": plan, "kind": kind, "rsi": r, "macd": m,
            "price": price, "day_change": day_chg}
