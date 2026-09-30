"""Readers, QA harness and features for the matched-negative pilot (A0/A1, G1 block-close).

Readers return a price series for a source S; QA checks run on EVERY pull (A8-lite):
 - decimals check against token.decimals(), finite/positive, range sanity per S_type
 - inverted-pair check (p vs reverse quote), reverse consistency for AMM spot quotes
 - block verification (requested block == returned block; block timestamps monotonic)
 - tx verification for attack anchors (receipt status + block)
Nothing here touches models.py or features.parquet.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import keccak

import pilot_rpc as R

ETH_PSEUDO = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"


def sel(sig: str) -> str:
    return "0x" + keccak(text=sig)[:4].hex()


def enc(sig: str, types, vals) -> str:
    return sel(sig) + (abi_encode(types, vals).hex() if types else "")


def dec_uint(h):
    return None if h in (None, "0x") else int(h[:66], 16)   # first word only


def dec_addr(h):
    return None if h in (None, "0x") or len(h) < 66 else "0x" + h[26:66]   # first 32-byte word (proxies can over-return)


# ------------------------------------------------------------------ QA ledger
@dataclass
class QA:
    """Collects QA outcomes for a pull; `ok` is False if any hard check fails."""
    name: str
    checks: list = field(default_factory=list)

    def add(self, check, passed, detail=""):
        self.checks.append((check, bool(passed), detail))
        return passed

    @property
    def ok(self):
        return all(p for _, p, _ in self.checks)

    def failures(self):
        return [(c, d) for c, p, d in self.checks if not p]


QA_LOG: list = []  # every QA object created in a run (written to reports)


def new_qa(name):
    q = QA(name)
    QA_LOG.append(q)
    return q


# ------------------------------------------------------------------ token/decimals
def token_decimals(addr):
    if addr is None or addr.lower() == ETH_PSEUDO:
        return 18
    h = R.eth_call_many([(addr, sel("decimals()"))], 20_000_000)[0]  # latest-ish block is fine for decimals
    v = dec_uint(h)
    if v is None:  # older tokens: try at a very recent block via latest (block param 'latest' unsupported in cache key)
        raise ValueError(f"decimals() failed for {addr}")
    return v


# ------------------------------------------------------------------ Curve spot reader
class CurvePool:
    """Marginal price of coin i in coin j via get_dy(1 unit of i). Handles int128/uint256 variants."""

    def __init__(self, addr, i, j, name, ref_block, unit=1.0):
        self.addr, self.i, self.j, self.name, self.unit = addr, i, j, name, unit
        self.coins, self.dec = [], []
        for k in range(8):
            c = None
            for sig, t in (("coins(uint256)", ["uint256"]), ("coins(int128)", ["int128"])):
                c = dec_addr(R.eth_call_many([(addr, enc(sig, t, [k]))], ref_block)[0])
                if c and int(c, 16) != 0:
                    break
                c = None
            if not c:
                break
            self.coins.append(c)
        if len(self.coins) < 2:
            raise ValueError(f"{name}: could not read coins at block {ref_block}")
        self.dec = [self._dec(c, ref_block) for c in self.coins]
        self.sig = None
        for sig, t in (("get_dy(int128,int128,uint256)", ["int128", "int128", "uint256"]),
                       ("get_dy(uint256,uint256,uint256)", ["uint256", "uint256", "uint256"])):
            dx = int(unit * 10 ** self.dec[i])
            h = R.eth_call_many([(addr, enc(sig, t, [i, j, dx]))], ref_block)[0]
            if dec_uint(h):
                self.sig, self.types = sig, t
                break
        if self.sig is None:
            raise ValueError(f"{name}: get_dy not callable at block {ref_block}")

    @staticmethod
    def _dec(c, blk):
        if c.lower() == ETH_PSEUDO:
            return 18
        h = R.eth_call_many([(c, sel("decimals()"))], blk)[0]
        v = dec_uint(h)
        if v is None:
            raise ValueError(f"decimals failed {c}")
        return v

    def _data(self, i, j):
        dx = int(self.unit * 10 ** self.dec[i])
        return enc(self.sig, self.types, [i, j, dx])

    def series(self, blocks, qa: QA, rev_stride=5):
        """Forward quote at every block; reverse quote (QA identity p_ij*p_ji ~ 1-fees) on every `rev_stride`-th block
        (pilot deviation from full reverse coverage, to stay inside the free-tier CU budget)."""
        di, dj = self.dec[self.i], self.dec[self.j]
        fwd = R.eth_call_blocks(self.addr, self._data(self.i, self.j), blocks)
        ridx = list(range(0, len(blocks), rev_stride))
        revs = R.eth_call_blocks(self.addr, self._data(self.j, self.i), [blocks[k] for k in ridx])
        p = []
        for f in fwd:
            fv = dec_uint(f)
            p.append(np.nan if not fv else (fv / 10 ** dj) / self.unit)
        prev = np.full(len(blocks), np.nan)
        for k, r in zip(ridx, revs):
            rv = dec_uint(r)
            prev[k] = np.nan if not rv else (rv / 10 ** di) / self.unit
        p = np.array(p)
        qa.add("decimals_read", di in range(0, 37) and dj in range(0, 37), f"dec_i={di} dec_j={dj}")
        qa.add("no_nan", np.isfinite(p).all(), f"{int((~np.isfinite(p)).sum())} NaN of {len(p)}")
        # reverse consistency: p_ij * p_ji = (1-fee)^2 ~ within 3% for any sane AMM state near balanced
        with np.errstate(invalid="ignore"):
            prod = p * prev
        okmask = np.isfinite(prod)
        qa.add("reverse_consistency", (~okmask).all() or bool((prod[okmask] > 0.90).all() and (prod[okmask] <= 1.001).all()),
               f"p*p_rev range [{np.nanmin(prod) if okmask.any() else 'na'}, {np.nanmax(prod) if okmask.any() else 'na'}]")
        return p


# ------------------------------------------------------------------ Vault rate reader
class VaultRate:
    """Share price of a vault: convertToAssets(1 share) (ERC4626), else pricePerShare()/getPricePerFullShare()."""
    SIGS = [("convertToAssets(uint256)", ["uint256"], "shares"),
            ("pricePerShare()", [], None),
            ("getPricePerFullShare()", [], None)]

    def __init__(self, addr, name, ref_block, decimals=None, asset_decimals=None):
        self.addr, self.name = addr, name
        self.dec = decimals if decimals is not None else dec_uint(R.eth_call_many([(addr, sel("decimals()"))], ref_block)[0])
        self.adec = asset_decimals if asset_decimals is not None else self.dec
        self.sig = None
        for sig, t, kind in self.SIGS:
            data = enc(sig, t, [10 ** self.dec] if t else [])
            v = dec_uint(R.eth_call_many([(addr, data)], ref_block)[0])
            if v is not None:
                self.sig, self.types, self.kind = sig, t, kind
                break
        if self.sig is None:
            raise ValueError(f"{name}: no supported share-price function at block {ref_block}")

    def _data(self):
        return enc(self.sig, self.types, [10 ** self.dec] if self.types else [])

    def series(self, blocks, qa: QA):
        out = R.eth_call_blocks(self.addr, self._data(), blocks)
        v = np.array([np.nan if dec_uint(o) is None else dec_uint(o) for o in out], dtype=float)
        scale = 10 ** self.adec if self.kind == "shares" else 10 ** self.dec  # pricePerShare is in token decimals
        p = v / scale
        qa.add("no_nan", np.isfinite(p).all(), f"{int((~np.isfinite(p)).sum())} NaN of {len(p)}")
        qa.add("positive", bool((p[np.isfinite(p)] > 0).all()), "")
        return p


# ------------------------------------------------------------------ Chainlink reader
class ChainlinkFeed:
    def __init__(self, addr, name):
        self.addr, self.name = addr, name
        self.dec = dec_uint(R.eth_call_many([(addr, sel("decimals()"))], 20_000_000)[0])

    def series(self, blocks, qa: QA, max_stale=None):
        out = R.eth_call_blocks(self.addr, sel("latestRoundData()"), blocks)
        px, upd = [], []
        for o in out:
            if o in (None, "0x") or len(o) < 2 + 64 * 5:
                px.append(np.nan); upd.append(np.nan); continue
            rid, ans, st, ua, air = abi_decode(["uint80", "int256", "uint256", "uint256", "uint80"], bytes.fromhex(o[2:]))
            px.append(ans / 10 ** self.dec); upd.append(ua)
        px, upd = np.array(px), np.array(upd, dtype=float)
        qa.add("no_nan", np.isfinite(px).all(), f"{int((~np.isfinite(px)).sum())} NaN of {len(px)}")
        qa.add("positive", bool((px[np.isfinite(px)] > 0).all()), "")
        return px, upd


# ------------------------------------------------------------------ block/tx verification
def block_times(blocks, qa: QA):
    bs = R.get_blocks(list(blocks))
    ts = np.array([int(b["timestamp"], 16) if b else np.nan for b in bs], dtype=float)
    nums = [int(b["number"], 16) if b else None for b in bs]
    qa.add("block_numbers_match", all(n == b for n, b in zip(nums, blocks)), "")
    qa.add("timestamps_monotonic", bool(np.all(np.diff(ts) >= 0)), "")
    return ts, bs


def verify_tx(txhash, expect_block, qa: QA):
    rc = R.get_receipt(txhash)
    if not rc:
        qa.add("tx_found", False, txhash)
        return None
    blk = int(rc["blockNumber"], 16)
    qa.add("tx_status_ok", rc["status"] == "0x1", txhash)
    qa.add("tx_block_matches", expect_block is None or blk == expect_block, f"receipt block {blk} vs expected {expect_block}")
    return blk


# ------------------------------------------------------------------ trigger (A0, G1)
def trigger_fires(prices: np.ndarray, Y_steps: int, X: float):
    """Indices where max over k in [1, Y_steps] of |p[b]-p[b-k]|/p[b-k] >= X (block-close, source price only)."""
    n = len(prices)
    fire = np.zeros(n, dtype=bool)
    mag = np.zeros(n)
    for k in range(1, Y_steps + 1):
        if k >= n:
            break
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.abs(prices[k:] - prices[:-k]) / prices[:-k]
        r = np.nan_to_num(r, nan=0.0, posinf=0.0)
        mag[k:] = np.maximum(mag[k:], r)
    fire = mag >= X
    return fire, mag


# ------------------------------------------------------------------ features (A1)
def f_P1(pS_a, R_a):
    return abs(pS_a - R_a) / R_a


def f_P2(pS_a, pS_aW):
    return math.log(pS_a / pS_aW)


def f_P3(pS_window):
    r = np.diff(np.log(pS_window))
    return float(np.std(r, ddof=1)) if len(r) > 1 else float("nan")


def f_D1(pS_T, pS_a):
    return abs(pS_T - pS_a) / pS_a


def f_D2(pS_T, R_T):
    return abs(pS_T - R_T) / R_T


def f_D3(R_T, R_a):
    return abs(R_T - R_a) / R_a


def f_D5(p_after: np.ndarray, p_a: float, band=0.005, cap=None):
    """Blocks (in units of the sampling grid: caller multiplies by stride) until |p-p_a|/p_a <= band; cap if never."""
    dev = np.abs(p_after - p_a) / p_a
    ok = np.where(dev <= band)[0]
    return int(ok[0]) if len(ok) else (cap if cap is not None else len(p_after))


# ------------------------------------------------------------------ Curve tricrypto2 LP / yvCurve-3Crypto price (Inverse S)
TRICRYPTO2 = "0xD51a44d3FaE010294C616388b506AcdA1bfAAE46"
CRV3CRYPTO = "0xc4AD29ba4B3c580e6D59105FFf484999997675Ff"
YV3CRYPTO = "0xE537B5cc158EB71037D4125BDD7538421981E6AA"
CL_FEEDS = {"BTC": "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c", "ETH": "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419",
            "USDT": "0x3E7d1eAB13ad0104d2750B8863b489D65364e32D"}


class TricryptoLP:
    """S = value the Inverse feed read: yearn ppfs * (sum_i bal_i * chainlink_i) / LP supply (balance-weighted, manipulable).
    R (fair value) = ppfs * 3 * virtual_price * cbrt(P_usdt*P_btc*P_eth)  (Curve's manipulation-resistant LP formula)."""

    def __init__(self):
        self.F = {k: ChainlinkFeed(a, k) for k, a in CL_FEEDS.items()}

    def series(self, blocks, qa: QA):
        px = {k: self.F[k].series(blocks, qa)[0] for k in self.F}
        bal = [np.array([np.nan if dec_uint(o) is None else dec_uint(o) for o in
                         R.eth_call_blocks(TRICRYPTO2, enc("balances(uint256)", ["uint256"], [k]), blocks)], dtype=float) for k in range(3)]
        sup = np.array([np.nan if dec_uint(o) is None else dec_uint(o) for o in R.eth_call_blocks(CRV3CRYPTO, sel("totalSupply()"), blocks)], dtype=float) / 1e18
        ppfs = np.array([np.nan if dec_uint(o) is None else dec_uint(o) for o in R.eth_call_blocks(YV3CRYPTO, sel("pricePerShare()"), blocks)], dtype=float) / 1e18
        vp = np.array([np.nan if dec_uint(o) is None else dec_uint(o) for o in R.eth_call_blocks(TRICRYPTO2, sel("get_virtual_price()"), blocks)], dtype=float) / 1e18
        S = ppfs * (bal[0] / 1e6 * px["USDT"] + bal[1] / 1e8 * px["BTC"] + bal[2] / 1e18 * px["ETH"]) / sup
        Rfair = ppfs * 3 * vp * np.cbrt(px["USDT"] * px["BTC"] * px["ETH"])
        qa.add("no_nan", np.isfinite(S).all() and np.isfinite(Rfair).all(), f"{int((~np.isfinite(S)).sum())} NaN S")
        qa.add("S_vs_Rfair_same_scale", bool(np.nanmax(np.abs(np.log(S / Rfair))) < 0.5), f"max |log(S/R)|={np.nanmax(np.abs(np.log(S/Rfair))):.3f}")
        return S, Rfair
