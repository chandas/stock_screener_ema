# Stock Screener

A local Flask dashboard for tracking NASDAQ and NIFTY stocks and viewing stock recommendations.

## Features

- Separate Investor and Trader analysis modes for NASDAQ and NIFTY watchlists.
- Recommendations use EMA13, EMA62, EMA200, RSI, volume, ATR, and market-index confirmation.
- Investor analysis uses weekly signals. Trader analysis combines 4-hour signals with a daily trend filter.
- Click a ticker to open its TradingView chart in a dismissible pop-up.
- Stores watchlists and recommendations in a local SQLite database.
- Sends Telegram alerts for strong signals when Telegram credentials are configured.

## Requirements

- Python 3
- Internet access for downloading market data

## Setup on Windows

From the project directory, create and activate a virtual environment and install the dependencies:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install Flask APScheduler pandas requests yfinance
```

## Run

Start the app from the project directory:

```powershell
python app.py
```

Then open <http://127.0.0.1:5000/>.

The app runs a full scan in the background when it starts, while the dashboard becomes available. The SQLite database is initialized automatically.

## Scheduled scans

Scheduled scan times use the `Asia/Kolkata` time zone:

| Market | Days | Time |
| --- | --- | --- |
| NIFTY | Monday–Friday | 10:00 and 16:30 |
| NASDAQ | Monday–Friday | 20:00 |
| NASDAQ | Tuesday–Saturday | 04:00 |

The laptop must be awake and connected to the internet for scheduled scans to run.

## Telegram alerts

Set these as Windows user environment variables to enable Telegram alerts:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Do not put credential values in source files or commit them. If either variable is missing, the scanner logs that the alert was skipped.

## Network access

By default, the dashboard listens only on `127.0.0.1` and Flask debug mode is disabled. It is intended for use on the host computer; LAN or public access is not configured.

## Local files

`stocks.db` contains local watchlist and recommendation data. Do not commit it. The virtual environment and Python cache files are also local development artifacts.
