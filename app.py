"""Flask application entry point for the stock screener."""
import re
import atexit
import threading
from flask import Flask, abort, redirect, render_template, request, url_for
from apscheduler.schedulers.background import BackgroundScheduler
from scanner import evaluate_stock, run_full_scan, run_market_scan
from database import (
    DEFAULT_WATCHLISTS,
    MODES,
    add_watchlist_stock,
    get_latest_recommendations,
    get_watchlist_scan_status,
    init_db,
    mark_watchlist_stock_pending,
    remove_watchlist_stock,
)

app = Flask(__name__)
TICKER_PATTERN = re.compile(r"[A-Z0-9.^=_&-]{1,20}\Z")

# Initialize DB on start
init_db()

scan_lock = threading.Lock()


def _run_market_scan(market_name, macro_ticker):
    with scan_lock:
        run_market_scan(market_name, macro_ticker)


def _run_startup_scan():
    with scan_lock:
        run_full_scan()


# Schedule market scans on weekdays in India Standard Time.
scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
scheduler.add_job(
    func=_run_market_scan,
    trigger="cron",
    day_of_week="mon-fri",
    hour=10,
    minute=0,
    args=("NIFTY", "^NSEI"),
    id="nifty-morning-scan",
)
scheduler.add_job(
    func=_run_market_scan,
    trigger="cron",
    day_of_week="mon-fri",
    hour=16,
    minute=30,
    args=("NIFTY", "^NSEI"),
    id="nifty-afternoon-scan",
)
scheduler.add_job(
    func=_run_market_scan,
    trigger="cron",
    day_of_week="mon-fri",
    hour=20,
    minute=0,
    args=("NASDAQ", "^IXIC"),
    id="nasdaq-evening-scan",
)
scheduler.add_job(
    func=_run_market_scan,
    trigger="cron",
    day_of_week="tue-sat",
    hour=4,
    minute=0,
    args=("NASDAQ", "^IXIC"),
    id="nasdaq-early-morning-scan",
)
scheduler.start()

# Shut down scheduler when app exits
atexit.register(lambda: scheduler.shutdown())

@app.route("/")
def index():
    nasdaq_mode = request.args.get("nasdaq_mode", "Trader")
    nifty_mode = request.args.get("nifty_mode", "Trader")
    if nasdaq_mode not in MODES:
        nasdaq_mode = "Trader"
    if nifty_mode not in MODES:
        nifty_mode = "Trader"
    nasdaq_recs = get_latest_recommendations("NASDAQ", nasdaq_mode)
    nifty_recs = get_latest_recommendations("NIFTY", nifty_mode)
    notice = request.args.get("notice", "")
    if notice not in {
        "scanned",
        "mode_awaiting",
        "exists",
        "removed",
        "not_found",
        "invalid",
    }:
        notice = ""
    notice_mode = request.args.get("mode", "")
    if notice_mode not in MODES:
        notice_mode = ""
    return render_template(
        "index.html",
        nasdaq_recs=nasdaq_recs,
        nifty_recs=nifty_recs,
        notice=notice,
        notice_ticker=request.args.get("ticker", "").upper(),
        notice_mode=notice_mode,
        nasdaq_mode=nasdaq_mode,
        nifty_mode=nifty_mode,
    )


def _selected_modes():
    selected = {}
    for market in ("nasdaq", "nifty"):
        mode = request.form.get(f"{market}_mode", "Trader")
        selected[f"{market}_mode"] = mode if mode in MODES else "Trader"
    return selected


@app.post("/markets/<market>/stocks")
def add_stock_route(market):
    market = market.upper()
    if market not in DEFAULT_WATCHLISTS:
        abort(404)
    ticker = request.form.get("ticker", "").strip().upper()
    selected_modes = _selected_modes()
    selected_mode = request.form.get("mode", "Trader")
    if selected_mode not in MODES:
        selected_mode = "Trader"
    if not TICKER_PATTERN.fullmatch(ticker):
        return redirect(url_for("index", notice="invalid", **selected_modes))
    added = add_watchlist_stock(market, ticker)
    statuses = [
        get_watchlist_scan_status(market, ticker, mode)
        for mode in MODES
    ]
    if not added and all(status == "Scanned" for status in statuses):
        notice = "exists"
    else:
        mark_watchlist_stock_pending(market, ticker)
        macro_ticker = "^IXIC" if market == "NASDAQ" else "^NSEI"
        scan_results = evaluate_stock(ticker, market, macro_ticker)
        notice = "scanned" if scan_results.get(selected_mode) else "mode_awaiting"
    return redirect(
        url_for(
            "index",
            notice=notice,
            ticker=ticker,
            mode=selected_mode,
            **selected_modes,
        )
    )


@app.post("/markets/<market>/stocks/remove")
def remove_stock_route(market):
    market = market.upper()
    if market not in DEFAULT_WATCHLISTS:
        abort(404)
    ticker = request.form.get("ticker", "").strip().upper()
    selected_modes = _selected_modes()
    if not TICKER_PATTERN.fullmatch(ticker):
        return redirect(url_for("index", notice="invalid", **selected_modes))
    removed = remove_watchlist_stock(market, ticker)
    notice = "removed" if removed else "not_found"
    return redirect(
        url_for("index", notice=notice, ticker=ticker, **selected_modes)
    )


if __name__ == "__main__":
    threading.Thread(
        target=_run_startup_scan,
        name="startup-market-scan",
        daemon=True,
    ).start()
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
