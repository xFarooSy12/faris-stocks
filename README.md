# Faris strategy stock analyzer (استراتيجية فارس - فحص و فرز الأسهم)

This is an Arabic, right-to-left Streamlit app modeled on the four screenshots and the guide `منهج فيصل.pdf`. It is for learning only and is not a buy or sell recommendation.

## Run it on your computer (bash)

These commands work in bash on Mac, Linux, WSL, or Git Bash on Windows. You need Python 3.11, 3.12 or 3.13 installed. They assume the zip is in your Downloads folder.

```bash
cd ~/Downloads                      # go to the folder that has the zip
unzip stocksite_app.zip             # extract it; this creates a "stocksite" folder
cd stocksite                        # go into the app folder
python3 -m venv .venv               # create a private Python environment in .venv
source .venv/bin/activate           # turn it on (Git Bash on Windows: source .venv/Scripts/activate)
pip install -r requirements.txt     # install the tested package versions
streamlit run app.py                # start the app; it opens at http://localhost:8501 (Ctrl+C stops it)
```

Next time, you only need to run `cd ~/Downloads/stocksite`, then `source .venv/bin/activate`, then `streamlit run app.py`.

On Git Bash for Windows, if `python3` is not found, use `python` instead.

Optional: `python -m pytest -q tests` runs the calculation checks.

## Run it on your computer (PowerShell)

These are the same steps as the bash ones, for Windows PowerShell:

```powershell
cd ~\Downloads                           # go to the folder that has the zip
Expand-Archive stocksite_app.zip -DestinationPath .   # extract it; this creates a "stocksite" folder
cd stocksite                             # go into the app folder
python -m venv .venv                     # create a private Python environment in .venv
.venv\Scripts\Activate.ps1               # turn it on; you'll see (.venv) at the start of the line
pip install -r requirements.txt          # install the tested package versions
streamlit run app.py                     # start the app; it opens at http://localhost:8501 (Ctrl+C stops it)
```

If PowerShell says running scripts is disabled when you activate, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, answer Y, and then try again. That setting lets scripts on your own computer run, but downloaded scripts still need a signature.

Next time, you only need `cd ~\Downloads\stocksite`, then `.venv\Scripts\Activate.ps1`, then `streamlit run app.py`.

### The same steps one at a time, with explanations

You need Python 3.11, 3.12 or 3.13 (https://www.python.org/downloads/). Open a terminal (PowerShell on Windows, Terminal on Mac) inside the `stocksite` folder, then run:

```powershell
python -m venv .venv
```
This creates a private Python environment in a `.venv` folder, so the packages don't touch the rest of your system.

```powershell
.venv\Scripts\Activate.ps1        # Windows PowerShell
source .venv/bin/activate         # Mac / Linux
```
This turns that environment on for the current terminal. You'll see `(.venv)` at the start of the prompt. If PowerShell blocks the script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, which lets your own local scripts run.

```powershell
pip install -r requirements.txt
```
This installs the exact package versions the app was tested with: streamlit, yfinance, plotly, pandas, requests and pytest.

```powershell
streamlit run app.py
```
This starts the app and opens it in your browser at http://localhost:8501. Press Ctrl+C in the terminal to stop it.

```powershell
python -m pytest -q tests
```
This is optional. It runs the checks on the RSI, MACD, gap, Former Runner and reverse-split calculations.

## Where each number comes from

| Field | Source | Notes |
|---|---|---|
| Price, candles, volume, country, market cap, float, shares outstanding | Yahoo Finance (yfinance) | Free and unofficial. Float can differ from Finviz. |
| Reverse splits | Yahoo split history | A 1-for-20 split is stored as 0.05 and shown as 1:20. |
| RSI 14, MACD 12/26/9, MA20/30/50, VWAP | Calculated in the app | These use the same formulas as TradingView. |
| Short shares available and borrow fee (CTB) | Interactive Brokers' public file `ftp3.interactivebrokers.com` (user `shortstock`) | This is one broker's inventory. It's what Faris calls "شورت متاح". |
| Official short interest | Yahoo / FINRA | It's about two weeks delayed. |
| Market scan list | Finviz's free screener page | There's no official free API, so this can break. You can type tickers in by hand instead. |
| Chart tab 1 | TradingView embedded widget | It loads in your browser from TradingView. |

## The rules the checklist applies (from the guide)
- Filters (section 3): price under $5, market cap under $300M, float under 20M/50M, average volume over 100K, RVOL over 2.
- Float (section 4): under 20M is acceptable, under 5M is strong but risky, and near 1M is very risky.
- Former Runner: the stock rose 100% or more within the last year.
- RSI 23-27 (section 22) is a pressure alert, not a buy order. An RSI around 40 is not preferred.
- Moving averages (section 21): below them means pressure, and reclaiming them means improvement.
- MACD improving, and a positive candle such as a hammer or an engulfing candle (section 23).
- Don't chase (sections 24 and 29): a rise of 50% or more from the 20-day low gets a warning to wait for a retest or a liquidity sweep.
- Support, resistance and unfilled gaps are found automatically from daily swing points. They're approximate, so confirm them on the chart.

The app picked these thresholds itself, and you can change them in the sidebar: what counts as a "low" short-available number (default 50,000), and what counts as "near support" (default 8%).
