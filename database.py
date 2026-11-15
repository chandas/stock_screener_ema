"""SQLite database management for the stock screener."""
import sqlite3

DB_NAME = "stocks.db"

# Nasdaq-100 constituents as of November 13, 2026 (101 securities; Alphabet has two share classes).
NASDAQ_100_TICKERS = (
    "AAPL",
    "ABNB",
    "ADBE",
    "ADI",
    "ADP",
    "ADSK",
    "AEP",
    "ALAB",
    "ALNY",
    "AMAT",
    "AMD",
    "AMGN",
    "AMZN",
    "APP",
    "ARM",
    "ASML",
    "AVGO",
    "AXON",
    "BKNG",
    "BKR",
    "CCEP",
    "CDNS",
    "CEG",
    "CMCSA",
    "COST",
    "CPRT",
    "CRWD",
    "CRWV",
    "CSCO",
    "CSX",
    "CTAS",
    "DASH",
    "DDOG",
    "DXCM",
    "EXC",
    "FANG",
    "FAST",
    "FER",
    "FTNT",
    "GEHC",
    "GILD",
    "GOOG",
    "GOOGL",
    "HON",
    "HONA",
    "IDXX",
    "INTC",
    "INTU",
    "ISRG",
    "KDP",
    "KLAC",
    "LIN",
    "LITE",
    "LRCX",
    "MAR",
    "MCHP",
    "MDLZ",
    "MELI",
    "META",
    "MNST",
    "MPWR",
    "MRNA",
    "MRVL",
    "MSFT",
    "MSTR",
    "MU",
    "NBIS",
    "NFLX",
    "NVDA",
    "NXPI",
    "ODFL",
    "ORLY",
    "PANW",
    "PAYX",
    "PCAR",
    "PDD",
    "PEP",
    "PLTR",
    "PYPL",
    "QCOM",
    "REGN",
    "RKLB",
    "ROP",
    "ROST",
    "SBUX",
    "SHOP",
    "SNDK",
    "SNPS",
    "SPCX",
    "STX",
    "TER",
    "TMUS",
    "TRI",
    "TSLA",
    "TTWO",
    "TXN",
    "VRTX",
    "WDAY",
    "WDC",
    "WMT",
    "XEL",
)

NIFTY_50_TICKERS = (
    "ADANIENT.NS",
    "ADANIPORTS.NS",
    "APOLLOHOSP.NS",
    "ASIANPAINT.NS",
    "AXISBANK.NS",
    "BAJAJ-AUTO.NS",
    "BAJFINANCE.NS",
    "BAJAJFINSV.NS",
    "BEL.NS",
    "BHARTIARTL.NS",
    "BSE.NS",
    "CIPLA.NS",
    "COALINDIA.NS",
    "DRREDDY.NS",
    "EICHERMOT.NS",
    "ETERNAL.NS",
    "GRASIM.NS",
    "HCLTECH.NS",
    "HDFCBANK.NS",
    "HDFCLIFE.NS",
    "HINDALCO.NS",
    "HINDUNILVR.NS",
    "ICICIBANK.NS",
    "INDIGO.NS",
    "INFY.NS",
    "ITC.NS",
    "JIOFIN.NS",
    "JSWSTEEL.NS",
    "KOTAKBANK.NS",
    "LT.NS",
    "M&M.NS",
    "MARUTI.NS",
    "MAXHEALTH.NS",
    "NESTLEIND.NS",
    "NTPC.NS",
    "ONGC.NS",
    "POWERGRID.NS",
    "RELIANCE.NS",
    "SBILIFE.NS",
    "SHRIRAMFIN.NS",
    "SBIN.NS",
    "SUNPHARMA.NS",
    "TCS.NS",
    "TATACONSUM.NS",
    "TMPV.NS",
    "TATASTEEL.NS",
    "TECHM.NS",
    "TITAN.NS",
    "TRENT.NS",
    "ULTRACEMCO.NS",
)

DEFAULT_WATCHLISTS = {
    "NASDAQ": NASDAQ_100_TICKERS,
    "NIFTY": NIFTY_50_TICKERS,
}
MODES = ("Investor", "Trader")


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            market TEXT,
            ticker TEXT,
            score INTEGER,
            recommendation TEXT,
            stop_loss REAL,
            mode TEXT NOT NULL DEFAULT 'Legacy'
        )
    ''')
    recommendation_columns = {
        row[1] for row in cursor.execute('PRAGMA table_info(recommendations)')
    }
    if "mode" not in recommendation_columns:
        cursor.execute(
            "ALTER TABLE recommendations "
            "ADD COLUMN mode TEXT NOT NULL DEFAULT 'Legacy'"
        )
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_watchlist (
            market TEXT NOT NULL,
            ticker TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            scan_status TEXT NOT NULL DEFAULT 'Awaiting scan',
            PRIMARY KEY (market, ticker)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_mode_status (
            market TEXT NOT NULL,
            ticker TEXT NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Awaiting scan',
            PRIMARY KEY (market, ticker, mode)
        )
    ''')
    watchlist_columns = {
        row[1] for row in cursor.execute('PRAGMA table_info(stock_watchlist)')
    }
    if "scan_status" not in watchlist_columns:
        cursor.execute(
            "ALTER TABLE stock_watchlist "
            "ADD COLUMN scan_status TEXT NOT NULL DEFAULT 'Awaiting scan'"
        )
        cursor.execute('''
            UPDATE stock_watchlist
            SET scan_status = 'Scanned'
            WHERE EXISTS (
                SELECT 1
                FROM recommendations
                WHERE recommendations.market = stock_watchlist.market
                  AND recommendations.ticker = stock_watchlist.ticker
            )
        ''')
    cursor.executemany(
        'INSERT OR IGNORE INTO stock_watchlist (market, ticker) VALUES (?, ?)',
        [
            (market, ticker)
            for market, tickers in DEFAULT_WATCHLISTS.items()
            for ticker in tickers
        ],
    )
    cursor.execute(
        'SELECT market, ticker FROM stock_watchlist WHERE active = 1'
    )
    active_stocks = cursor.fetchall()
    cursor.executemany(
        'INSERT OR IGNORE INTO stock_mode_status (market, ticker, mode) VALUES (?, ?, ?)',
        [
            (market, ticker, mode)
            for market, ticker in active_stocks
            for mode in MODES
        ],
    )
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_recommendations_mode_latest
        ON recommendations (market, ticker, mode, timestamp DESC, id DESC)
    ''')
    conn.commit()
    conn.close()


def get_watchlist(market):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT ticker FROM stock_watchlist WHERE market = ? AND active = 1 ORDER BY ticker',
        (market,),
    )
    tickers = [row[0] for row in cursor.fetchall()]
    conn.close()
    if market == "NASDAQ":
        tickers = sorted(set(tickers).union(NASDAQ_100_TICKERS))
    elif market == "NIFTY":
        tickers = sorted(set(tickers).union(NIFTY_50_TICKERS))
    return tickers


def get_watchlist_scan_status(market, ticker, mode):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT status FROM stock_mode_status '
        'WHERE market = ? AND ticker = ? AND mode = ?',
        (market, ticker, mode),
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def add_watchlist_stock(market, ticker):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT active FROM stock_watchlist WHERE market = ? AND ticker = ?',
        (market, ticker),
    )
    existing = cursor.fetchone()
    if existing and existing[0]:
        conn.close()
        return False
    if existing:
        cursor.execute(
            "UPDATE stock_watchlist SET active = 1, scan_status = 'Awaiting scan' "
            'WHERE market = ? AND ticker = ?',
            (market, ticker),
        )
    else:
        cursor.execute(
            'INSERT INTO stock_watchlist (market, ticker) VALUES (?, ?)',
            (market, ticker),
        )
    conn.commit()
    cursor.executemany(
        'INSERT OR IGNORE INTO stock_mode_status (market, ticker, mode) VALUES (?, ?, ?)',
        [(market, ticker, mode) for mode in MODES],
    )
    if existing:
        cursor.execute(
            'UPDATE stock_mode_status SET status = ? WHERE market = ? AND ticker = ?',
            ("Awaiting scan", market, ticker),
        )
    conn.commit()
    conn.close()
    return True


def remove_watchlist_stock(market, ticker):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE stock_watchlist SET active = 0 WHERE market = ? AND ticker = ? AND active = 1',
        (market, ticker),
    )
    removed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return removed


def mark_watchlist_stock_pending(market, ticker):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE stock_watchlist SET scan_status = 'Awaiting scan' "
        'WHERE market = ? AND ticker = ? AND active = 1',
        (market, ticker),
    )
    cursor.execute(
        "UPDATE stock_mode_status SET status = 'Awaiting scan' "
        'WHERE market = ? AND ticker = ?',
        (market, ticker),
    )
    conn.commit()
    conn.close()


def mark_watchlist_stock_scanned(market, ticker, mode):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE stock_mode_status SET status = 'Scanned' "
        'WHERE market = ? AND ticker = ? AND mode = ?',
        (market, ticker, mode),
    )
    cursor.execute(
        "UPDATE stock_watchlist SET scan_status = 'Scanned' "
        'WHERE market = ? AND ticker = ? AND active = 1',
        (market, ticker),
    )
    conn.commit()
    conn.close()


def save_recommendation(
    timestamp, market, ticker, score, recommendation, stop_loss, mode="Legacy"
):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO recommendations
            (timestamp, market, ticker, score, recommendation, stop_loss, mode)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (timestamp, market, ticker, score, recommendation, stop_loss, mode))
    conn.commit()
    conn.close()

def get_latest_recommendations(market, mode):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    query = '''
        SELECT watchlist.market, watchlist.ticker, mode_status.status AS scan_status,
               latest.timestamp, latest.score,
               latest.recommendation, latest.stop_loss
        FROM stock_watchlist AS watchlist
        JOIN stock_mode_status AS mode_status
          ON mode_status.market = watchlist.market
         AND mode_status.ticker = watchlist.ticker
         AND mode_status.mode = ?
        LEFT JOIN recommendations AS latest
          ON mode_status.status = 'Scanned'
         AND latest.id = (
              SELECT recommendation.id
              FROM recommendations AS recommendation
              WHERE recommendation.market = watchlist.market
                AND recommendation.ticker = watchlist.ticker
                AND recommendation.mode = mode_status.mode
              ORDER BY recommendation.timestamp DESC, recommendation.id DESC
              LIMIT 1
          )
        WHERE watchlist.market = ? AND watchlist.active = 1
    '''
    if market == "NASDAQ":
        query += '''
            AND latest.score IS NOT NULL
            AND latest.recommendation IN (
                'STRONG BUY',
                'WEAK BUY / HOLD',
                'STRONG SELL / SHORT',
                'WEAK SELL / WATCH'
            )
        '''
    elif market == "NIFTY":
        query += " AND latest.score IS NOT NULL"
    query += '''
        ORDER BY
            CASE WHEN latest.score IS NULL THEN 1 ELSE 0 END,
            latest.score DESC,
            latest.timestamp DESC,
            latest.id DESC,
            watchlist.ticker
    '''
    if market in {"NASDAQ", "NIFTY"}:
        query += " LIMIT 10"
    cursor.execute(query, (mode, market))
    rows = cursor.fetchall()
    conn.close()
    return rows