"""استراتيجية فارس - فحص و فرز الأسهم

Run:  streamlit run app.py
"""
from __future__ import annotations

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from faris import data, indicators as ind, rules, scan

st.set_page_config(page_title="استراتيجية فارس", page_icon="📈", layout="wide")

MODE_SINGLE, MODE_SCAN = "تحليل سهم معين", "فحص السوق"
ICON = {rules.PASS: "✅", rules.WARN: "⚠️", rules.FAIL: "❌", rules.INFO: "ℹ️"}

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&display=swap');
html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {font-family: 'Cairo', sans-serif;}
[data-testid="stMainBlockContainer"], [data-testid="stSidebarContent"] {direction: rtl; text-align: right;}
[data-testid="stMainBlockContainer"] input {direction: ltr; text-align: left;}
[data-testid="stMetric"] {background: #eefaf1; border-radius: 12px; padding: 14px 18px;}
[data-testid="stMetricLabel"] p {color: #2e7d4f; font-size: 0.9rem;}
[data-testid="stMetricValue"] {font-size: 1.45rem; direction: ltr; text-align: right;}
[data-testid="stMetricValue"] div, [data-testid="stMetricLabel"] div {white-space: normal; overflow: visible; text-overflow: clip;}
.checks {font-family: 'Cairo', sans-serif; line-height: 1.9;}
.ck-group {font-weight: 700; margin-top: 10px; color: #2e7d4f;}
.ck {padding: 2px 0;}
.faris-head {background: #e3f6e8; border-radius: 14px; padding: 22px 24px; margin-bottom: 12px;}
.faris-head h1 {font-size: 1.8rem; margin: 0 0 6px 0; padding: 0;}
.faris-head p {color: #5f7d68; margin: 0; font-size: 0.85rem;}
.src {color: #7a8a80; font-size: 0.78rem;}
</style>
<div class="faris-head">
  <h1>استراتيجية فارس - فحص و فرز الأسهم</h1>
  <p>التقسيم العكسي · المؤشرات الفنية · الاقتراض · متابعة الفحص المباشرة</p>
</div>
""",
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.subheader("إعدادات القواعد")
    params = {
        "short_low": st.number_input("الشورت المتاح يعتبر قليلاً إذا كان أقل من (سهم)", 0, 10_000_000, 50_000, 5_000,
                                     help="اختيار التطبيق، ليس رقماً من الدليل. مثال LFS في الدليل: شورت 10 آلاف."),
        "runner_mult": st.number_input("Former Runner: أقل مضاعفة للسعر خلال سنة", 1.5, 10.0, 2.0, 0.5,
                                       help="2.0 = صعود 100% أو أكثر (من الدليل: سبق انفجر 100% أو أكثر)."),
        "near_support_pct": st.number_input("قريب من الدعم إذا كان البعد أقل من %", 1.0, 30.0, 8.0, 1.0,
                                            help="اختيار التطبيق، ليس رقماً من الدليل."),
    }
    st.divider()
    st.caption("تعليمي فقط وليس توصية شراء أو بيع. الأسهم الصغيرة وقليلة الفلووت عالية الخطورة. "
               "أي دخول يجب أن يكون بوقف واضح وحجم مخاطرة صغير.")


# ------------------------------------------------------------- cached data
@st.cache_data(ttl=300, show_spinner=False)
def get_history(t, tf):
    return data.history(t, tf)


@st.cache_data(ttl=900, show_spinner=False)
def get_info(t):
    return data.info(t)


@st.cache_data(ttl=3600, show_spinner=False)
def get_splits(t):
    return data.splits(t)


@st.cache_data(ttl=900, show_spinner=False)
def get_ibkr():
    try:
        return data.ibkr_short_table(), None
    except Exception as e:  # network / format problems should not stop the app
        return None, str(e)


def money(x, dec=2):
    return "غير متاح" if x is None else f"${x:,.{dec}f}"


def price_fmt(x):
    return "غير متاح" if x is None else (f"${x:,.4f}" if x < 1 else f"${x:,.2f}")


# --------------------------------------------------------------- charts
def tradingview(symbol: str, exchange: str | None, tf: str):
    sym = f"{data.TV_EXCHANGE[exchange]}:{symbol}" if exchange in data.TV_EXCHANGE else symbol
    cfg = {"container_id": "tv", "symbol": sym, "interval": data.TV_INTERVAL[tf], "autosize": True,
           "timezone": "America/New_York", "theme": "light", "style": "1", "locale": "ar_AE",
           "studies": ["RSI@tv-basicstudies", "MACD@tv-basicstudies"], "allow_symbol_change": True}
    st.iframe(
        f"""<div style="height:640px"><div id="tv" style="height:100%"></div></div>
        <script src="https://s3.tradingview.com/tv.js"></script>
        <script>new TradingView.widget({json.dumps(cfg)});</script>""",
        height=660,
    )


def levels_chart(df: pd.DataFrame, tf: str, plan: dict):
    df = df.tail(300 if tf not in ("day", "week") else 250).copy()
    close = df["Close"]
    r = ind.rsi(close)
    m = ind.macd(close)
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.02,
                        row_heights=[0.55, 0.13, 0.16, 0.16])
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=close,
                                 name="السعر", increasing_line_color="#26a69a", decreasing_line_color="#ef5350"),
                  row=1, col=1)
    for n, color in ((20, "#f2a900"), (50, "#7e57c2")):
        fig.add_trace(go.Scatter(x=df.index, y=ind.sma(close, n), name=f"MA{n}", line=dict(width=1.2, color=color)),
                      row=1, col=1)
    if tf not in ("day", "week"):
        fig.add_trace(go.Scatter(x=df.index, y=ind.session_vwap(df), name="VWAP",
                                 line=dict(width=1.2, color="#1e88e5", dash="dot")), row=1, col=1)
    if plan.get("support"):
        fig.add_hline(y=plan["support"]["level"], line=dict(color="#2e7d32", dash="dash"),
                      annotation_text=f"دعم {plan['support']['level']:.2f}", row=1, col=1)
    if plan.get("resistance"):
        fig.add_hline(y=plan["resistance"]["level"], line=dict(color="#c62828", dash="dash"),
                      annotation_text=f"مقاومة {plan['resistance']['level']:.2f}", row=1, col=1)
    vol_colors = ["#26a69a" if c >= o else "#ef5350" for o, c in zip(df["Open"], close)]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Vol", marker_color=vol_colors), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=r, name="RSI 14", line=dict(color="#7e57c2", width=1.3)), row=3, col=1)
    fig.add_hrect(y0=23, y1=27, fillcolor="#ffcdd2", opacity=0.5, line_width=0, row=3, col=1)
    for y in (30, 70):
        fig.add_hline(y=y, line=dict(color="#999", width=1, dash="dot"), row=3, col=1)
    fig.add_trace(go.Bar(x=df.index, y=m["hist"], name="Hist",
                         marker_color=["#26a69a" if v >= 0 else "#ef5350" for v in m["hist"].fillna(0)]),
                  row=4, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=m["macd"], name="MACD", line=dict(color="#2962ff", width=1.2)), row=4, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=m["signal"], name="Signal", line=dict(color="#ff6d00", width=1.2)), row=4, col=1)
    breaks = [dict(bounds=["sat", "mon"])]
    if tf not in ("day", "week"):
        breaks.append(dict(bounds=[16, 9.5], pattern="hour"))
    if tf != "week":
        fig.update_xaxes(rangebreaks=breaks)
    fig.update_layout(height=820, xaxis_rangeslider_visible=False, showlegend=False,
                      margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white")
    fig.update_yaxes(gridcolor="#eee")
    fig.update_yaxes(range=[0, 100], row=3, col=1)
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
    st.caption("المنطقة الحمراء في RSI = منطقة 23-27. خطوط الدعم والمقاومة محسوبة آلياً من القمم والقيعان اليومية "
               "وهي تقريبية؛ تحقق منها بعينك على الشارت.")


# ----------------------------------------------------------- single stock
def analyze(ticker: str, tf: str):
    with st.spinner(f"جاري جلب بيانات {ticker}..."):
        hist = get_history(ticker, tf)
        daily = hist if tf == "day" else get_history(ticker, "day")
        info = get_info(ticker)
        try:
            spl = get_splits(ticker)
        except Exception:
            spl = pd.Series(dtype=float)
        ib_table, ib_err = get_ibkr()
    if hist.empty:
        st.error(f"لم يتم العثور على بيانات للرمز {ticker} في Yahoo Finance. تأكد من الرمز.")
        return

    short = data.ibkr_short_for(ib_table, ticker) if ib_table is not None else None
    rs = data.reverse_splits(spl)
    res = rules.evaluate(info, hist, tf, daily, short, rs, params)
    price = res["price"]

    name = info.get("longName") or info.get("shortName") or ticker
    st.subheader(f"{ticker} · {name}")

    # ---- company & price (screenshot 2)
    st.markdown("### بيانات الشركة والسعر")
    flt = info.get("floatShares")
    mcap = info.get("marketCap") or info.get("_fast_mcap")
    c = st.columns(4)
    c[0].metric("بلد النشاط", info.get("country") or "غير متاح")
    c[1].metric("القيمة السوقية", money(mcap))
    chg = res["day_change"]
    c[2].metric("آخر سعر", price_fmt(price), None if chg is None else f"{chg:+.2f}% (يومي)")
    c[3].metric("الأسهم الحرة (Free Float)", rules.fmt_int(flt))
    c = st.columns(4)
    c[0].metric("الأسهم القائمة", rules.fmt_int(info.get("sharesOutstanding") or info.get("_fast_shares")))
    c[1].metric("متوسط الفوليوم (3 أشهر)", rules.fmt_int(info.get("averageVolume")))
    c[2].metric("فوليوم آخر يوم", rules.fmt_int(float(daily["Volume"].iloc[-1]) if not daily.empty else None))
    rv = ind.rvol(daily) if not daily.empty else None
    c[3].metric("RVOL", "غير متاح" if rv is None else f"{rv:.2f}x")
    st.markdown('<p class="src">المصدر: Yahoo Finance. الفلووت يختلف أحياناً بين المصادر (Yahoo / Finviz / غيرها).</p>',
                unsafe_allow_html=True)

    # ---- reverse splits
    st.markdown("### بيانات التقسيم العكسي")
    c = st.columns(3)
    if rs.empty:
        c[0].metric("آخر تقسيم عكسي", "لا يوجد")
        c[1].metric("النسبة", "-")
    else:
        c[0].metric("آخر تقسيم عكسي", str(pd.Timestamp(rs.iloc[0]["date"]).date()))
        c[1].metric("النسبة", rs.iloc[0]["ratio"])
    c[2].metric("عدد التقسيمات العكسية (كل التاريخ)", len(rs))
    if len(rs) > 1:
        with st.expander("كل التقسيمات العكسية"):
            st.dataframe(rs.assign(date=rs["date"].dt.date).rename(columns={"date": "التاريخ", "ratio": "النسبة"}),
                         hide_index=True)

    # ---- indicators & short (screenshot 3)
    st.markdown("### المؤشرات الفنية وبيانات الشورت")
    r_last, m_last = res["rsi"].iloc[-1], res["macd"]["macd"].iloc[-1]
    c = st.columns(4)
    c[0].metric(f"RSI (14) · {tf}", "غير متاح" if pd.isna(r_last) else f"{r_last:.2f}")
    c[1].metric(f"MACD · {tf}", "غير متاح" if pd.isna(m_last) else f"{m_last:.2f}")
    c[2].metric("عدد أسهم الشورت (IBKR)", short["available_raw"] if short else "غير متاح")
    fee = short.get("fee_rate") if short else None
    c[3].metric("نسبة الاقتراض (CTB)", "غير متاح" if fee is None else f"{fee:.2f}%")
    c = st.columns(4)
    si = info.get("sharesShort")
    si_date = info.get("dateShortInterest")
    si_date = datetime.fromtimestamp(si_date).date() if isinstance(si_date, (int, float)) else None
    c[0].metric("Short Interest الرسمي", rules.fmt_int(si))
    c[1].metric("تاريخ بيانات Short Interest", str(si_date) if si_date else "غير متاح")
    spf = info.get("shortPercentOfFloat")
    c[2].metric("الشورت من الفلووت", "غير متاح" if spf is None else f"{spf * 100:.2f}%")
    note = ("الشورت المتاح ونسبة الاقتراض من ملف Interactive Brokers العام (مخزون وسيط واحد، يتحدث كل ربع ساعة تقريباً)."
            if ib_table is not None else f"تعذر تحميل ملف IBKR: {ib_err}")
    st.markdown(f'<p class="src">{note} Short Interest الرسمي من Yahoo/FINRA ويتأخر حوالي أسبوعين. '
                f'الدليل يفرق بينهما: عندما يقول فارس "شورت 10 آلاف" يقصد المتاح للشورت.</p>', unsafe_allow_html=True)

    # ---- charts (screenshot 4)
    st.markdown("### الشارت")
    t1, t2 = st.tabs(["TradingView", "شارت مع مستويات فارس"])
    with t1:
        tradingview(ticker, info.get("exchange"), tf)
    with t2:
        levels_chart(hist, tf, res["plan"])

    # ---- Faris checklist
    st.markdown("### قائمة فحص فارس")
    st.info(f"**النوع المقترح:** {res['kind']}")
    parts = []
    for group in ("البيانات", "السلوك", "فني", "الدخول"):
        rows = [ck for ck in res["checks"] if ck.group == group]
        if rows:
            parts.append(f'<div class="ck-group">{group}</div>')
            parts += [f'<div class="ck">{ICON[ck.status]} <b><bdi>{html.escape(ck.label)}</bdi></b>: '
                      f'<bdi>{html.escape(ck.detail)}</bdi></div>' for ck in rows]
    st.html('<div dir="rtl" class="checks">' + "".join(parts) + "</div>")
    st.caption("✅ يطابق الدليل · ⚠️ انتبه · ❌ لا يطابق · ℹ️ معلومة")

    plan = res["plan"]
    if plan.get("support") and price:
        st.markdown("### خطة مبدئية (تحقق منها قبل أي قرار)")
        sup = plan["support"]["level"]
        c = st.columns(3)
        c[0].metric("أقرب قاع حديث (غير مؤكد) / الوقف تحته" if plan["support"].get("fallback") else "الدعم / الوقف تحته", price_fmt(sup), f"-{(price - sup) / price * 100:.1f}% من السعر",
                    delta_color="off")
        if plan.get("resistance"):
            resl = plan["resistance"]["level"]
            c[1].metric("الهدف الأول (أول مقاومة)", price_fmt(resl), f"+{(resl - price) / price * 100:.1f}%")
            risk, reward = price - sup, resl - price
            c[2].metric("العائد / المخاطرة", f"{reward / risk:.2f}" if risk > 0 else "-")
        st.caption("قاعدة فارس: ادخل فقط إذا عرفت أين ستخرج قبل أن تضغط شراء. ضع أوامر Limit داخل منطقة الطلب ولا تشتري من العرض. "
                   "في الزخم لا يتجاوز الخطأ 1% إلى 2%.")


# ------------------------------------------------------------ market scan
def _go_analyze(sym: str):
    st.session_state.mode = MODE_SINGLE
    st.session_state.ticker_in = sym
    st.session_state.active = sym


@st.cache_data(ttl=240, show_spinner=False)
def run_scan(tickers: tuple[str, ...], mode: str, runner_mult: float):
    bars = data.daily_batch(list(tickers))
    with ThreadPoolExecutor(max_workers=8) as ex:
        infos = dict(zip(bars, ex.map(lambda t: _safe_info(t), bars)))
    ib_table, _ = get_ibkr()
    rows = []
    for t, d in bars.items():
        if len(d) < 30:
            continue
        sh = data.ibkr_short_for(ib_table, t) if ib_table is not None else None
        row = scan.scan_row(t, d, infos.get(t, {}), sh, runner_mult)
        row["النقاط"] = scan.score(row, mode)
        rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["النقاط", "RVOL"], ascending=False).reset_index(drop=True)
    return df, datetime.now().strftime("%H:%M:%S")


def _safe_info(t):
    try:
        return data.info(t)
    except Exception:
        return {}


def show_scan(df: pd.DataFrame, when: str, mode: str):
    if df.empty:
        st.warning("لا توجد نتائج.")
        return
    st.caption(f"آخر تحديث: {when} · {len(df)} سهم · النقاط = عدد شروط الدليل المتحققة (للترتيب فقط، ليست إشارة شراء).")
    cfg = {
        "السعر": st.column_config.NumberColumn(format="$%.2f"),
        "التغير %": st.column_config.NumberColumn(format="%.2f%%"),
        "الفلووت": st.column_config.NumberColumn(format="compact"),
        "القيمة السوقية": st.column_config.NumberColumn(format="compact"),
        "شورت متاح IBKR": st.column_config.NumberColumn(format="compact"),
        "CTB %": st.column_config.NumberColumn(format="%.2f%%"),
        "صعود من قاع 20 يوم %": st.column_config.NumberColumn(format="%.1f%%"),
    }
    first = ["النقاط", "الرمز", "السعر", "التغير %", "RVOL", "الفلووت"]
    st.dataframe(df, hide_index=True, column_config=cfg, column_order=first + [c for c in df.columns if c not in first])
    c1, c2 = st.columns([3, 1])
    sym = c1.selectbox("حلل سهماً من النتائج", df["الرمز"].tolist(), key=f"pick_{mode}")
    c2.button("تحليل", on_click=_go_analyze, args=(sym,), type="primary", width="stretch", key=f"go_{mode}")


def market_scan():
    st.header("فحص السوق")
    mode = st.radio("نوع الفلتر", ["momentum", "anchor"], horizontal=True,
                    format_func=lambda k: scan.PRESETS[k]["label"])
    preset = scan.PRESETS[mode]
    src = st.radio("مصدر الأسهم", ["Finviz", "قائمة رموز يدوية"], horizontal=True)
    if src == "Finviz":
        st.caption(preset["note"])
        filters = st.text_input("رموز فلاتر Finviz (قابلة للتعديل)", preset["filters"], key=f"f_{mode}")
        st.markdown(f"[افتح نفس الفلتر في Finviz للتأكد]({data.finviz_url(filters)})")
        limit = st.slider("أقصى عدد أسهم", 10, 100, 40, 10)
    else:
        manual = st.text_area("الرموز (مفصولة بفواصل أو أسطر)", placeholder="LFS, GDHG, BJDX")
    auto = st.checkbox("تحديث تلقائي (متابعة مباشرة)")
    mins = st.number_input("كل كم دقيقة", 5, 60, 5, 1, disabled=not auto)

    def get_tickers():
        if src == "Finviz":
            return tuple(data.finviz_tickers(filters)[:limit])
        raw = (t.strip().upper() for t in manual.replace("\n", ",").split(","))
        return tuple(dict.fromkeys(t for t in raw if re.fullmatch(r"[A-Z0-9.\-]{1,10}", t)))

    def do_scan():
        try:
            tickers = get_tickers()
        except Exception as e:
            st.error(f"تعذر قراءة Finviz: {e}. جرب القائمة اليدوية.")
            return
        if not tickers:
            st.warning("لا توجد رموز. الفلتر لم يُرجع نتائج أو القائمة فارغة.")
            return
        with st.spinner(f"جاري فحص {len(tickers)} سهم..."):
            st.session_state[f"scan_{mode}"] = run_scan(tickers, mode, params["runner_mult"])

    if auto:
        @st.fragment(run_every=int(mins) * 60)
        def live():
            do_scan()
            if f"scan_{mode}" in st.session_state:
                show_scan(*st.session_state[f"scan_{mode}"], mode)
        live()
        return

    if st.button("ابدأ الفحص", type="primary", width="stretch"):
        do_scan()
    if f"scan_{mode}" in st.session_state:
        show_scan(*st.session_state[f"scan_{mode}"], mode)


# ------------------------------------------------------------------- main
mode = st.radio("الوضع", [MODE_SINGLE, MODE_SCAN], horizontal=True, key="mode", label_visibility="collapsed")

if mode == MODE_SINGLE:
    st.header("تحليل سهم معين")
    st.text_input("رمز السهم الأمريكي", placeholder="e.g. JZ, UCAR, AAPL", key="ticker_in")
    tf = st.selectbox("الإطار الزمني", list(data.TIMEFRAMES), key="tf")
    if st.button("تحليل", type="primary", width="stretch"):
        sym = st.session_state.ticker_in.strip().upper()
        if re.fullmatch(r"[A-Z0-9.\-]{1,10}", sym):
            st.session_state.active = sym
        else:
            st.session_state.active = None
            st.error("اكتب رمز سهم صحيح، مثل AAPL")
    if st.session_state.get("active"):
        try:
            analyze(st.session_state.active, tf)
        except Exception as e:
            st.error(f"حدث خطأ أثناء التحليل: {e}")
else:
    market_scan()
