"""A10 power analysis. No data, no models: closed-form / Monte Carlo only.

Outputs the numbers quoted in reports/a10_power_analysis.md. Run from src/ with the project .venv.
"""
import numpy as np
from scipy import stats
from scipy.optimize import brentq

RNG = np.random.default_rng(20260929)
ALPHA = 0.05
POWER = 0.80
N_POS, N_NEG = 24, 138  # current manipulation / volatility counts (audit n=162)


# ---------- helpers ----------
def wilson(k, n, conf=0.95):
    z = stats.norm.ppf(1 - (1 - conf) / 2)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def hanley_mcneil_se(auc, n_pos, n_neg):
    q1 = auc / (2 - auc)
    q2 = 2 * auc * auc / (1 + auc)
    v = (auc * (1 - auc) + (n_pos - 1) * (q1 - auc**2) + (n_neg - 1) * (q2 - auc**2)) / (n_pos * n_neg)
    return np.sqrt(v)


def se_null(n_pos, n_neg):
    return np.sqrt((n_pos + n_neg + 1) / (12 * n_pos * n_neg))


def auc_mde(n_pos, n_neg, alpha=ALPHA, power=POWER):
    """Smallest true AUC rejected against H0: AUC=0.5 (one-sided z test, Hanley-McNeil SE under H1)."""
    za, zb = stats.norm.ppf(1 - alpha), stats.norm.ppf(power)
    f = lambda a: (a - 0.5) - za * se_null(n_pos, n_neg) - zb * hanley_mcneil_se(a, n_pos, n_neg)
    return brentq(f, 0.5001, 0.9999)


def n_pos_for_auc(target_auc, prevalence_ratio, alpha=ALPHA, power=POWER):
    """n_pos needed so that target_auc is detectable vs 0.5, with n_neg = n_pos * prevalence_ratio."""
    for n in range(5, 5000):
        if auc_mde(n, int(n * prevalence_ratio), alpha, power) <= target_auc:
            return n
    return None


def mcnemar_exact_p(b, c):
    n = b + c
    return 1.0 if n == 0 else min(1.0, 2 * stats.binom.cdf(min(b, c), n, 0.5))


def mcnemar_power(n_disc, p_b, alpha=ALPHA, sims=20000):
    """Power of exact McNemar given n_disc discordant pairs and P(discordant pair favours model A)=p_b."""
    b = RNG.binomial(n_disc, p_b, size=sims)
    return np.mean([mcnemar_exact_p(x, n_disc - x) < alpha for x in b])


def n_disc_for_power(p_b, alpha=ALPHA, power=POWER):
    for n in range(4, 400):
        if mcnemar_power(n, p_b, alpha, sims=4000) >= power:
            return n
    return None


def n_for_ci_halfwidth(p, hw, conf=0.95):
    z = stats.norm.ppf(1 - (1 - conf) / 2)
    return int(np.ceil(z * z * p * (1 - p) / hw**2))


# ---------- report ----------
if __name__ == "__main__":
    print("== 1. Precision of recall at current n_pos=24 (Wilson 95%) ==")
    for k in (12, 18, 20, 22):
        lo, hi = wilson(k, N_POS)
        print(f"  recall {k}/{N_POS}={k/N_POS:.3f}  CI [{lo:.3f}, {hi:.3f}]")

    print("\n== 2. AUC vs 0.5: null SE and minimum detectable AUC (alpha=.05 one-sided, power=.80) ==")
    print(f"  current n=({N_POS},{N_NEG}): null SE={se_null(N_POS, N_NEG):.3f}  "
          f"95% two-sided null band on AUC = 0.5 +/- {1.96*se_null(N_POS, N_NEG):.3f}")
    print(f"  MDE AUC (single test)              = {auc_mde(N_POS, N_NEG):.3f}")
    for m in (2, 3, 4, 6, 8):
        print(f"  MDE AUC (Holm/Bonferroni m={m}, alpha={ALPHA/m:.4f}) = {auc_mde(N_POS, N_NEG, ALPHA/m):.3f}")

    print("\n== 3. Negative controls (A5): how big must n be to CERTIFY 'near chance'? ==")
    print("   Rule: upper 95% one-sided bound on AUC must be < 0.60 when the true AUC is 0.50.")
    for ratio in (1, 2, 5.75):
        for n in (24, 40, 60, 100, 150, 250):
            nn = int(n * ratio)
            ub = 0.5 + 1.645 * se_null(n, nn)
            print(f"  n_pos={n:4d} n_neg={nn:4d}: expected upper bound = {ub:.3f}")
        print()

    print("== 4. Paired model comparison (exact McNemar on the manipulation class) ==")
    print(f"  observed BN vs RF: b=4,c=0 -> p={mcnemar_exact_p(4, 0):.3f}")
    for n_disc in (4, 8, 12, 20):
        for p_b in (0.75, 0.9):
            print(f"  n_disc={n_disc:3d}  P(favours A)={p_b}: power={mcnemar_power(n_disc, p_b):.2f}")
    for p_b in (0.7, 0.8, 0.9):
        print(f"  discordant pairs needed for 80% power at P(favours A)={p_b}: {n_disc_for_power(p_b)}")
    print("  (expected discordant pairs = n * discordance rate; at 5% discordance need n = n_disc / 0.05)")

    print("\n== 5. Sample size targets ==")
    print("  n_pos needed to detect a true AUC vs 0.5 (alpha=.05 one-sided, power=.80):")
    for tgt in (0.65, 0.70, 0.75, 0.80):
        row = ", ".join(f"ratio {r}: {n_pos_for_auc(tgt, r)}" for r in (1, 2, 5.75))
        print(f"    AUC {tgt}: {row}")
    print("  n_pos so a recall estimate has 95% CI half-width <= h (worst case p=.5 / p=.85):")
    for hw in (0.20, 0.15, 0.10, 0.05):
        print(f"    h={hw}: p=.5 -> {n_for_ci_halfwidth(.5, hw)}   p=.85 -> {n_for_ci_halfwidth(.85, hw)}")

    print("\n== 6. Total anomalies A0 must yield, by attack prevalence among triggered anomalies ==")
    print("  (need n_pos manipulations of the price-source-level class to be triggered)")
    for prev in (0.30, 0.15, 0.05, 0.02):
        row = ", ".join(f"n_pos={k}: {int(np.ceil(k/prev))}" for k in (30, 50, 80))
        print(f"    prevalence {prev:.2f}: total triggered anomalies -> {row}")

    print("\n== 7. Precision at deployment prevalence for a detector with sens/spec ==")
    for sens, spec in ((0.83, 0.97), (0.83, 0.995)):
        for prev in (0.15, 0.05, 0.01, 0.001):
            tp, fp = sens * prev, (1 - spec) * (1 - prev)
            print(f"    sens={sens} spec={spec} prevalence={prev}: precision={tp/(tp+fp):.3f}")
    print("  spec 95% CI at 0 false alarms in 138: Wilson upper bound on FPR ->", f"{wilson(0,138)[1]:.3f}",
          "(rule of three: 3/138 =", f"{3/138:.3f})")
