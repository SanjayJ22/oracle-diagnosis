"""Shared helpers for the cjsj_* scripts: cached Alchemy RPC, report-section writer, label constants.

Run every cjsj_* script from src/ with the project .venv:
    DYLD_FALLBACK_LIBRARY_PATH=../.venv/lib/python3.13/site-packages/sklearn/.dylibs ../.venv/bin/python cjsj_XX_*.py
(the env var is only needed for xgboost on macOS; it points at the libomp bundled with sklearn).
"""
import hashlib, json, os, re, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
CACHE = ROOT / "data" / "raw" / "rpc_cache"
NUMBERS_MD = REPORTS / "cjsj_numbers.md"

TAG_CONFOUNDED = "within-benchmark (confounded data, see research_audit.md)"
TAG_VERIFIED = "verified-label rerun (positives restricted to 2-source-verified M; negatives unchanged and still subject to audit C1-C3)"


def ensure_omp():
    """macOS: xgboost needs libomp; the venv's sklearn bundles one. Re-exec once with DYLD_FALLBACK_LIBRARY_PATH set
    (dyld reads it at process start, so setting os.environ in-process is too late). Call before importing xgboost."""
    import glob, sys
    libs = glob.glob(str(ROOT / ".venv/lib/python3*/site-packages/sklearn/.dylibs")) or glob.glob(os.path.join(sys.prefix, "lib/python3*/site-packages/sklearn/.dylibs"))
    if libs and libs[0] not in os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", ""):
        os.execve(sys.executable, [sys.executable] + sys.argv, dict(os.environ, DYLD_FALLBACK_LIBRARY_PATH=libs[0]))


def _env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def rpc(method, params, retries=4):
    """Cached JSON-RPC against Alchemy mainnet. Cache key = method+params (results are immutable for old blocks)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(json.dumps([method, params], sort_keys=True).encode()).hexdigest()
    f = CACHE / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text())
    url = f"https://eth-mainnet.g.alchemy.com/v2/{_env()['ALCHEMY_KEY']}"
    for i in range(retries):
        r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=60)
        if r.status_code == 200 and "error" not in r.json():
            res = r.json()["result"]
            f.write_text(json.dumps(res))
            return res
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"rpc failed {method} {params}: {r.text[:200]}")


def write_section(script, item_id, title, tag, body):
    """Replace-or-append one '## <item_id>' section in reports/cjsj_numbers.md (idempotent per item)."""
    header = "# CJSJ numbers (append-only log; one section per roadmap item, every number cites its script)\n\n"
    text = NUMBERS_MD.read_text() if NUMBERS_MD.exists() else header
    marker = f"## {item_id}. {title}"
    block = f"{marker}\n\n**Label: {tag}.**  Script: `src/{script}`  (run {time.strftime('%Y-%m-%d %H:%M')})\n\n{body.rstrip()}\n\n"
    pat = re.compile(rf"^## {re.escape(item_id)}\. .*?(?=^## |\Z)", re.S | re.M)
    text = pat.sub("", text) if pat.search(text) else text
    NUMBERS_MD.write_text(text.rstrip() + "\n\n" + block)
    return block
