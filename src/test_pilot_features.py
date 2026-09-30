"""A8 unit tests for pilot features on synthetic fixtures. Run on every pilot run."""
import math
import numpy as np
from pilot_lib import f_P1, f_P2, f_P3, f_D1, f_D2, f_D3, f_D5, trigger_fires


def test_all():
    assert abs(f_P1(1.02, 1.0) - 0.02) < 1e-12
    assert abs(f_P1(0.98, 1.0) - 0.02) < 1e-12                       # symmetric
    assert abs(f_P2(1.1, 1.0) - math.log(1.1)) < 1e-12
    assert f_P2(1.0, 1.0) == 0
    flat = np.ones(50)
    assert f_P3(flat) == 0
    w = np.array([1.0, 1.01, 1.0, 1.01, 1.0])
    assert f_P3(w) > 0
    assert abs(f_D1(1.05, 1.0) - 0.05) < 1e-12
    assert abs(f_D2(0.9, 1.0) - 0.1) < 1e-12
    assert abs(f_D3(1.0, 1.0)) < 1e-12 and abs(f_D3(1.02, 1.0) - 0.02) < 1e-12
    # D5: revert at index 3 (0.4% off) -> 3 ; never reverts -> cap
    assert f_D5(np.array([1.2, 1.1, 1.05, 1.004, 1.0]), 1.0) == 3
    assert f_D5(np.array([1.2, 1.2, 1.2]), 1.0, cap=99) == 99
    # trigger: 0.6% jump within Y=5 steps fires at X=0.5%, not at 1%
    p = np.ones(20); p[10:] = 1.006
    f, m = trigger_fires(p, 5, 0.005)
    assert f[10] and not f[9]
    f2, _ = trigger_fires(p, 5, 0.01)
    assert not f2.any()
    # trigger ignores any reference price by construction (signature has none)
    # a slow drift below X per window never fires
    drift = 1 + 0.0004 * np.arange(200)
    f3, _ = trigger_fires(drift, 5, 0.005)
    assert not f3.any()
    # NaN safe
    pn = np.ones(10); pn[4] = np.nan
    trigger_fires(pn, 3, 0.01)
    print("feature/trigger unit tests: PASS")


if __name__ == "__main__":
    test_all()
