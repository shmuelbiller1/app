"""Research-grade validation helpers adapted from established open-source quant ideas.

Includes:
- stationary bootstrap confidence intervals for serially correlated returns;
- probabilistic/deflated Sharpe calculations to penalize multiple testing;
- simple walk-forward signal outcome evaluation;
- a no-look-ahead suffix-pollution test for state functions.

These are deliberately small, dependency-light implementations rather than
copying an entire external framework into the scanner.
"""
from __future__ import annotations

import math
from typing import Callable, Sequence
import numpy as np
from scipy.stats import norm

EULER_GAMMA = 0.5772156649015329


def stationary_bootstrap(returns: Sequence[float], n_resamples: int = 1000, mean_block: float = 7.0, seed: int = 42) -> np.ndarray:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.ndim != 1 or len(r) < 2:
        raise ValueError("need at least two finite returns")
    rng = np.random.default_rng(seed)
    n = len(r)
    out = np.empty((n_resamples, n), dtype=float)
    p = 1.0 / max(float(mean_block), 1.0)
    for k in range(n_resamples):
        idx = []
        while len(idx) < n:
            start = int(rng.integers(0, n))
            length = int(rng.geometric(p))
            idx.extend((start + np.arange(length)) % n)
        out[k] = r[np.asarray(idx[:n])]
    return out


def bootstrap_ci(returns: Sequence[float], statistic: Callable[[np.ndarray], float], level: float = 0.95, n_resamples: int = 1000, mean_block: float = 7.0) -> tuple[float, float]:
    boot = stationary_bootstrap(returns, n_resamples=n_resamples, mean_block=mean_block)
    vals = np.asarray([statistic(x) for x in boot], dtype=float)
    alpha = 1.0 - level
    return float(np.nanpercentile(vals, 100 * alpha / 2)), float(np.nanpercentile(vals, 100 * (1 - alpha / 2)))


def _sr_correction(returns: Sequence[float], sharpe: float) -> float | None:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 3:
        return None
    sd = r.std(ddof=1)
    if sd <= 0:
        return None
    z = (r - r.mean()) / sd
    g3 = float(np.mean(z ** 3))
    g4 = float(np.mean(z ** 4))
    return 1.0 - g3 * sharpe + (g4 - 1.0) * sharpe ** 2 / 4.0


def probabilistic_sharpe_ratio(sharpe: float, returns: Sequence[float], benchmark: float = 0.0) -> float:
    corr = _sr_correction(returns, sharpe)
    n = len(np.asarray(returns))
    if corr is None or corr <= 0 or n < 3:
        return float("nan")
    return float(norm.cdf((sharpe - benchmark) * math.sqrt(n - 1) / math.sqrt(corr)))


def expected_max_sharpe_under_null(trial_sharpes: Sequence[float]) -> float:
    a = np.asarray(trial_sharpes, dtype=float)
    a = a[np.isfinite(a)]
    n = len(a)
    if n < 2:
        return 0.0
    var = float(np.var(a, ddof=1))
    if var <= 0:
        return 0.0
    return float(math.sqrt(var) * ((1-EULER_GAMMA)*norm.ppf(1-1/n) + EULER_GAMMA*norm.ppf(1-1/(n*math.e))))


def deflated_sharpe_ratio(chosen_sharpe: float, trial_sharpes: Sequence[float], returns: Sequence[float]) -> float:
    corr = _sr_correction(returns, chosen_sharpe)
    n = len(np.asarray(returns))
    if corr is None or corr <= 0 or n < 3:
        return float("nan")
    sr0 = expected_max_sharpe_under_null(trial_sharpes)
    return float(norm.cdf((chosen_sharpe - sr0) * math.sqrt(n - 1) / math.sqrt(corr)))


def no_lookahead_suffix_test(signal_fn: Callable[[np.ndarray], np.ndarray], data: Sequence[float], cut: int) -> None:
    x = np.asarray(data, dtype=float)
    clean = np.asarray(signal_fn(x))
    polluted = x.copy()
    polluted[cut:] = np.nan
    dirty = np.asarray(signal_fn(polluted))
    a, b = clean[:cut], dirty[:cut]
    if not np.allclose(a, b, equal_nan=True):
        raise AssertionError(f"signal function leaks future data before cut={cut}")
