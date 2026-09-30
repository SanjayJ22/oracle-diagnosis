"""One-command reproduction of the CJSJ numbers: runs the cjsj_* analysis scripts in dependency order and rewrites the matching sections of reports/cjsj_numbers.md.

    python src/reproduce_cjsj.py                # all offline scripts (needs data/processed/features.parquet; see README)
    python src/reproduce_cjsj.py --only 35,47   # selected items
    python src/reproduce_cjsj.py --network      # also the scripts that read Ethereum mainnet (needs ALCHEMY_KEY in .env or data/raw/rpc_cache)
    python src/reproduce_cjsj.py --keep-going   # do not stop at the first failing script

Scripts that need a wallet-free, read-only Alchemy archive endpoint (06 atomicity, 26 dollar losses, 33 Chainlink feed history) are skipped unless --network; their
committed outputs (reports/cjsj_06_atomicity.csv, cjsj_26_losses.csv, cjsj_33*.csv) are read by later scripts."""
import argparse, glob, subprocess, sys, time
from pathlib import Path

SRC = Path(__file__).resolve().parent
OFFLINE = [1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 25, 27, 28, 29, 30, 32, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 15, 31, 34]
NETWORK = [6, 26, 33]          # 33 = cjsj_33b_config, cjsj_33_chainlink, cjsj_33_finalize (in that order)


def scripts(n):
    if n == 33: return [SRC / f"cjsj_{x}.py" for x in ("33b_config", "33_chainlink", "33_finalize")]
    return sorted(SRC.glob(f"cjsj_{n:02d}_*.py"))


def sort_sections():
    """write_section replaces a section by appending it; restore numeric order of the '## N.' sections."""
    import re
    p = SRC.parent / "reports" / "cjsj_numbers.md"; t = p.read_text(); parts = re.split(r"(?m)^(?=## \d+\. )", t)
    p.write_text(parts[0] + "".join(sorted(parts[1:], key=lambda x: int(re.match(r"## (\d+)\.", x).group(1)))))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--only", default=""); ap.add_argument("--network", action="store_true"); ap.add_argument("--keep-going", action="store_true")
    a = ap.parse_args()
    items = [int(x) for x in a.only.split(",") if x] if a.only else OFFLINE + (NETWORK if a.network else [])
    if a.network and not a.only: items = [6] + OFFLINE[:8] + [26, 33] + OFFLINE[8:]
    failed = []
    for n in items:
        if n == 34 and not (SRC.parent / 'reports/cjsj_submission/JillellamudiSanjay_paper.docx').exists():
            print('skip cjsj_34_paper_check.py (paper .docx is not distributed with the repository)'); continue
        for s in scripts(n):
            t0 = time.time(); r = subprocess.run([sys.executable, str(s)], cwd=SRC, capture_output=True, text=True)
            print(f"{'ok  ' if r.returncode == 0 else 'FAIL'} {s.name:40s} {time.time() - t0:6.0f}s", flush=True)
            if r.returncode:
                print(r.stderr[-1500:]); failed.append(s.name)
                if not a.keep_going: sys.exit(1)
    sort_sections()
    print("failed:", failed or "none")


if __name__ == "__main__":
    main()
