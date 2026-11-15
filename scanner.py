"""Stock data fetching, calculations, and scoring."""
import os
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime
from database import (
    MODES,
    get_watchlist,
    init_db,
    mark_watchlist_stock_pending,
    mark_watchlist_stock_scanned,
    save_recommendation,
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram alert not sent: configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"Telegram alert failed: {exc}")

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def _download_frame(symbol, period, interval):
    try:
        frame = yf.download(symbol, period=period, interval=interval, progress=False)
    except Exception as exc:
        print(f"Error downloading {interval} data for {symbol}: {exc}")
        return pd.DataFrame()
    if frame.empty:
        print(f"No {interval} data available for {symbol}.")
        return frame
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    return frame


def _add_indicators(frame):
    data = frame.copy()
    required_columns = {"Open", "High", "Low", "Close", "Volume"}
    missing_columns = required_columns.difference(data.columns)
    if missing_columns:
        raise ValueError(f"Missing price columns: {', '.join(sorted(missing_columns))}")

    data["EMA13"] = data["Close"].ewm(span=13, adjust=False).mean()
    data["EMA62"] = data["Close"].ewm(span=62, adjust=False).mean()
    data["EMA200"] = data["Close"].ewm(span=200, adjust=False).mean()
    data["RSI"] = compute_rsi(data["Close"], 14)
    data["VolMA"] = data["Volume"].rolling(window=20).mean()
    data["TR"] = pd.concat(
        [
            data["High"] - data["Low"],
            (data["High"] - data["Close"].shift(1)).abs(),
            (data["Low"] - data["Close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    data["ATR"] = data["TR"].rolling(window=14).mean()
    return data


def _add_macro_indicator(frame):
    data = frame.copy()
    if "Close" not in data:
        raise ValueError("Macro data is missing Close prices")
    data["EMA200"] = data["Close"].ewm(span=200, adjust=False).mean()
    return data


def _aggregate_four_hour(hourly_frame, market_name):
    offset = "9h30min" if market_name == "NASDAQ" else "9h15min"
    return (
        hourly_frame.resample("4h", origin="start_day", offset=offset)
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        .dropna(subset=["Open", "High", "Low", "Close"])
    )


def _score_recommendation(latest, previous, latest_macro, daily_bias=None):
    is_golden_cross = latest["EMA13"] > latest["EMA200"] and previous["EMA13"] <= previous["EMA200"]
    is_bullish_stack = (
        latest["EMA13"] > latest["EMA62"]
        and latest["EMA62"] > latest["EMA200"]
        and not is_golden_cross
    )
    is_buy_confirmation = (
        latest["EMA13"] > latest["EMA62"] and previous["EMA13"] <= previous["EMA62"]
    ) or (latest["Low"] <= latest["EMA62"] and latest["Close"] >= latest["EMA62"])
    buy_p1 = (2 if is_golden_cross else (1 if is_bullish_stack else 0)) + int(is_buy_confirmation)
    buy_p2 = (
        int(latest["Volume"] > latest["VolMA"])
        + int(40 <= latest["RSI"] <= 65)
        + int(latest_macro["Close"] > latest_macro["EMA200"])
    )
    buy_rsi_penalty = -2 if latest["RSI"] > 70 else 0
    total_buy_score = buy_p1 + buy_p2 + buy_rsi_penalty

    is_death_cross = latest["EMA13"] < latest["EMA200"] and previous["EMA13"] >= previous["EMA200"]
    is_bearish_stack = (
        latest["EMA13"] < latest["EMA62"]
        and latest["EMA62"] < latest["EMA200"]
        and not is_death_cross
    )
    is_sell_confirmation = latest["EMA13"] < latest["EMA62"] and previous["EMA13"] >= previous["EMA62"]
    sell_p1 = (2 if is_death_cross else (1 if is_bearish_stack else 0)) + int(is_sell_confirmation)
    sell_p2 = (
        int(latest["Volume"] > latest["VolMA"])
        + int(30 <= latest["RSI"] <= 45)
        + int(latest_macro["Close"] < latest_macro["EMA200"])
    )
    sell_rsi_penalty = -2 if latest["RSI"] < 30 else 0
    total_sell_score = sell_p1 + sell_p2 + sell_rsi_penalty

    buy_allowed = daily_bias is None or daily_bias == "bullish"
    sell_allowed = daily_bias is None or daily_bias == "bearish"
    if buy_allowed and total_buy_score >= 6:
        recommendation = "STRONG BUY"
        final_score = total_buy_score
    elif buy_allowed and total_buy_score >= 4:
        recommendation = "WEAK BUY / HOLD"
        final_score = total_buy_score
    elif sell_allowed and total_sell_score >= 5:
        recommendation = "STRONG SELL / SHORT"
        final_score = -total_sell_score
    elif sell_allowed and total_sell_score >= 3:
        recommendation = "WEAK SELL / WATCH"
        final_score = -total_sell_score
    else:
        recommendation = "NEUTRAL / CASH"
        final_score = total_buy_score - total_sell_score
    return recommendation, final_score


def _daily_trend(daily_data):
    latest = daily_data.iloc[-1]
    if latest["Close"] > latest["EMA200"] and latest["EMA13"] > latest["EMA62"]:
        return "bullish"
    if latest["Close"] < latest["EMA200"] and latest["EMA13"] < latest["EMA62"]:
        return "bearish"
    return "neutral"


def _evaluate_mode(
    ticker,
    market_name,
    mode,
    signal_frame,
    macro_frame,
    atr_multiple,
    daily_frame=None,
):
    try:
        if signal_frame.empty or macro_frame.empty:
            print(f"Insufficient {mode} data for {ticker}; leaving it awaiting scan.")
            return False
        signal_data = _add_indicators(signal_frame)
        macro_data = _add_macro_indicator(macro_frame)
        if len(signal_data) < 200 or len(macro_data) < 200:
            print(f"Not enough history for {mode} analysis of {ticker}.")
            return False

        daily_bias = None
        if daily_frame is not None:
            if daily_frame.empty or len(daily_frame) < 200:
                print(f"Not enough daily trend data for Trader analysis of {ticker}.")
                return False
            daily_bias = _daily_trend(_add_indicators(daily_frame))

        latest = signal_data.iloc[-1]
        previous = signal_data.iloc[-2]
        recommendation, final_score = _score_recommendation(
            latest,
            previous,
            macro_data.iloc[-1],
            daily_bias,
        )
        is_sell = recommendation in {"STRONG SELL / SHORT", "WEAK SELL / WATCH"}
        if recommendation == "NEUTRAL / CASH":
            is_sell = final_score < 0
        direction = 1 if is_sell else -1
        stop_loss = round(
            float(latest["Close"]) + direction * atr_multiple * float(latest["ATR"]),
            2,
        )
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        save_recommendation(
            timestamp,
            market_name,
            ticker,
            final_score,
            recommendation,
            stop_loss,
            mode=mode,
        )
        mark_watchlist_stock_scanned(market_name, ticker, mode)

        if recommendation in {"STRONG BUY", "STRONG SELL / SHORT"}:
            message = (
                f"🚨 *{recommendation} SIGNAL ({mode})* 🚨\n"
                f"Market: `{market_name}`\nTicker: `{ticker}`\n"
                f"Score: `{final_score}`\nStop Loss: `{stop_loss}`"
            )
            send_telegram_alert(message)
        return True
    except Exception as exc:
        print(f"Error analyzing {ticker} for {mode}: {exc}")
        return False


def evaluate_stock(ticker, market_name, macro_ticker, macro_data=None) -> dict:
    init_db()
    results = {mode: False for mode in MODES}
    daily = _download_frame(ticker, "1y", "1d")
    weekly = _download_frame(ticker, "5y", "1wk")
    hourly = _download_frame(ticker, "2y", "1h")

    if macro_data is None:
        macro_data = {
            "daily": _download_frame(macro_ticker, "1y", "1d"),
            "weekly": _download_frame(macro_ticker, "5y", "1wk"),
        }

    results["Investor"] = _evaluate_mode(
        ticker,
        market_name,
        "Investor",
        weekly,
        macro_data["weekly"],
        atr_multiple=2.0,
    )
    if not hourly.empty:
        try:
            four_hour = _aggregate_four_hour(hourly, market_name)
            results["Trader"] = _evaluate_mode(
                ticker,
                market_name,
                "Trader",
                four_hour,
                macro_data["daily"],
                atr_multiple=1.5,
                daily_frame=daily,
            )
        except Exception as exc:
            print(f"Error preparing 4-hour data for {ticker}: {exc}")
    else:
        print(f"No 4-hour source data available for {ticker}; Trader scan is pending.")
    return results

def run_market_scan(market_name, macro_ticker):
    init_db()
    print(f"--- Starting {market_name} Market Scan ---")
    macro_data = {
        "daily": _download_frame(macro_ticker, "1y", "1d"),
        "weekly": _download_frame(macro_ticker, "5y", "1wk"),
    }
    for ticker in get_watchlist(market_name):
        evaluate_stock(ticker, market_name, macro_ticker, macro_data)
    print(f"--- {market_name} Scan Complete ---")


def run_full_scan():
    print("--- Starting Full Market Scan ---")
    for market_name, macro_ticker in (("NASDAQ", "^IXIC"), ("NIFTY", "^NSEI")):
        run_market_scan(market_name, macro_ticker)
    print("--- Full Market Scan Complete ---")