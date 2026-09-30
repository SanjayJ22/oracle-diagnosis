"""Block/time helpers and A0 G1 trigger scans (source price path only) for the pilot."""
import datetime as dt
import numpy as np
import pilot_rpc as R
from pilot_lib import *

X_PEGGED = 0.005      # A0 placeholder: pegged / slow sources (Curve stable, LSD, LP, vault)
Y_BLOCKS = 50         # A0
Y_MERGE = 300         # A0
STRIDE = 10           # scan grid; T refined to the exact block afterwards


def ts_of(n):
    return int(R.get_block(n)["timestamp"], 16)


def block_at(ts_target, lo=11_000_000, hi=None):
    hi = hi or R.latest_block()
    while lo < hi:
        mid = (lo + hi) // 2
        if ts_of(mid) < ts_target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def utc(y, m, d, h=0):
    return int(dt.datetime(y, m, d, h, tzinfo=dt.timezone.utc).timestamp())


def episodes_from_series(blocks, prices, X=X_PEGGED, Y=Y_BLOCKS, stride=STRIDE, merge=Y_MERGE):
    fire, mag = trigger_fires(prices, Y // stride, X)
    idx = np.where(fire)[0]
    eps = []
    for i in idx:
        b = blocks[i]
        if eps and b - eps[-1]["last_fire"] <= merge:
            eps[-1]["last_fire"] = b
            eps[-1]["peak_mag"] = max(eps[-1]["peak_mag"], float(mag[i]))
        else:
            eps.append({"first_grid_fire": b, "last_fire": b, "peak_mag": float(mag[i])})
    return eps


def refine_T(series_fn, first_grid_fire, X=X_PEGGED, Y=Y_BLOCKS):
    """Exact first firing block: per-block series over [b*-Y-stride, b*]; trigger evaluated per block."""
    lo = first_grid_fire - Y - STRIDE
    blocks = list(range(lo, first_grid_fire + 1))
    p = series_fn(blocks)
    fire, mag = trigger_fires(p, Y, X)
    idx = np.where(fire)[0]
    idx = idx[idx >= Y]        # need a full window of history inside the refine range
    if len(idx) == 0:
        idx = np.where(fire)[0]
    return blocks[idx[0]] if len(idx) else None
