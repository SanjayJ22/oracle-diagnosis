"""Fetch 1-minute candlestick data from a Binance-compatible public REST API.

This endpoint is public (no API key required). The base URL is read from
.env (BINANCE_API_BASE) because api.binance.com 451-blocks some regions
(e.g. the US) — default here is api.binance.us, which shares the same
request/response schema. Override BINANCE_API_BASE in .env to point at
api.binance.com if running from an unrestricted location.
"""

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

BINANCE_KLINES_URL = os.getenv("BINANCE_API_BASE", "https://api.binance.us/api/v3/klines")
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2  # multiplied by attempt number between retries


def _to_ms(dt) -> int:
    """Convert a datetime (or ISO string) to a Binance-style millisecond timestamp."""
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _cache_path(symbol: str, interval: str, start_ms: int, end_ms: int) -> Path:
    """Deterministic cache filename so identical calls hit disk, not the API."""
    return CACHE_DIR / f"cex_{symbol}_{interval}_{start_ms}_{end_ms}.csv"


def fetch_cex_klines(symbol: str, start_time, end_time, interval: str = "1m") -> pd.DataFrame:
    """Fetch candlestick data for `symbol` between `start_time` and `end_time`.

    Args:
        symbol: Binance trading pair, e.g. "ETHUSDT".
        start_time: datetime or ISO string (naive datetimes are assumed UTC).
        end_time: datetime or ISO string (naive datetimes are assumed UTC).
        interval: Kline interval, defaults to 1-minute.

    Returns:
        DataFrame with columns ["timestamp", "close"], timestamp as UTC datetime.
    """
    start_ms = _to_ms(start_time)
    end_ms = _to_ms(end_time)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_path(symbol, interval, start_ms, end_ms)
    if cache_file.exists():
        return pd.read_csv(cache_file, parse_dates=["timestamp"])

    all_rows = []
    fetch_start = start_ms
    while fetch_start < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": fetch_start,
            "endTime": end_ms,
            "limit": 1000,  # Binance's max klines per request
        }

        rows = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = requests.get(BINANCE_KLINES_URL, params=params, timeout=10)
                response.raise_for_status()
                rows = response.json()
                break
            except (requests.RequestException, ValueError) as exc:
                if attempt == MAX_RETRIES:
                    raise RuntimeError(
                        f"Failed to fetch klines for {symbol} after {MAX_RETRIES} attempts"
                    ) from exc
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

        if not rows:
            break

        all_rows.extend(rows)
        last_open_time = rows[-1][0]
        fetch_start = last_open_time + 1  # step past the last candle to avoid duplicates

        if len(rows) < 1000:
            break  # short page means we've reached the end of the range

    df = pd.DataFrame(
        all_rows,
        columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "num_trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ],
    )
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close"] = df["close"].astype(float)
    df = df[["timestamp", "close"]]

    df.to_csv(cache_file, index=False)
    return df


if __name__ == "__main__":
    # Quick smoke test: fetch the last hour of ETHUSDT 1-minute data and print it.
    now = datetime.now(timezone.utc)
    one_hour_ago = now - pd.Timedelta(hours=1)

    result = fetch_cex_klines("ETHUSDT", one_hour_ago, now)
    print(result)
