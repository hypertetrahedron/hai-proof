"""Pass rates and paired efficiency statistics (DESIGN §6). Pure Python."""

from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .models import TrialResult

METRICS = ("cost_usd", "tokens_total", "wall_s")


def _value(t: TrialResult, metric: str) -> float | None:
    if t.metrics is None:
        return None
    v = getattr(t.metrics, metric, None)
    return float(v) if isinstance(v, (int, float)) else None


def paired_log_ratios(
    trials: Sequence[TrialResult], metric: str, *, ref: str = "A", cand: str = "B"
) -> dict[str, list[float]]:
    refs: dict[tuple[str, str], TrialResult] = {}
    cands: dict[tuple[str, str], TrialResult] = {}
    for t in trials:
        if not t.scored:
            continue
        if t.arm == ref:
            refs[(t.pair_id, t.task_id)] = t
        elif t.arm == cand:
            cands[(t.pair_id, t.task_id)] = t
    out: dict[str, list[float]] = defaultdict(list)
    for key in refs:
        if key not in cands:
            continue
        a, b = _value(refs[key], metric), _value(cands[key], metric)
        if a is None or b is None or a <= 0 or b <= 0:
            continue
        out[key[1]].append(math.log(b / a))
    return dict(out)


def cluster_bootstrap(
    per_task: Mapping[str, Sequence[float]], *, n_boot: int = 5000, seed: int = 0, alpha: float = 0.05
) -> tuple[float, float, float]:
    data = [list(v) for _, v in sorted(per_task.items()) if len(v) > 0]
    if not data:
        raise ValueError("no values to bootstrap")
    point = sum(sum(v) / len(v) for v in data) / len(data)
    rng = random.Random(seed)
    k = len(data)
    means: list[float] = []
    for _ in range(n_boot):
        tot = 0.0
        for _ in range(k):
            vals = data[rng.randrange(k)]
            n = len(vals)
            tot += sum(vals[rng.randrange(n)] for _ in range(n)) / n
        means.append(tot / k)
    means.sort()
    lo_i = max(0, min(n_boot - 1, int(math.floor(alpha / 2 * n_boot))))
    hi_i = max(0, min(n_boot - 1, int(math.ceil((1 - alpha / 2) * n_boot)) - 1))
    return math.exp(point), math.exp(means[lo_i]), math.exp(means[hi_i])


def _ranks(abs_vals: list[float]) -> list[float]:
    idx = sorted(range(len(abs_vals)), key=lambda i: abs_vals[i])
    ranks = [0.0] * len(abs_vals)
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and abs_vals[idx[j + 1]] == abs_vals[idx[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[idx[k]] = avg
        i = j + 1
    return ranks


def wilcoxon_signed_rank(values: Sequence[float]) -> float | None:
    vals = [float(v) for v in values if v != 0]
    n = len(vals)
    if n == 0:
        return None
    absv = [round(abs(v), 12) for v in vals]
    ranks = _ranks(absv)
    w_plus = sum(r for r, v in zip(ranks, vals) if v > 0)
    if n <= 30:
        dr = [int(round(2 * r)) for r in ranks]
        total = sum(dr)
        counts = [0] * (total + 1)
        counts[0] = 1
        for r in dr:
            for s in range(total, r - 1, -1):
                counts[s] += counts[s - r]
        w2 = int(round(2 * w_plus))
        p_le = sum(counts[: w2 + 1]) / 2**n
        p_ge = sum(counts[w2:]) / 2**n
        return min(1.0, 2 * min(p_le, p_ge))
    mean = n * (n + 1) / 4
    var = n * (n + 1) * (2 * n + 1) / 24
    ties: dict[float, int] = defaultdict(int)
    for a in absv:
        ties[a] += 1
    var -= sum(c**3 - c for c in ties.values()) / 48
    if var <= 0:
        return 1.0
    z = max(0.0, abs(w_plus - mean) - 0.5) / math.sqrt(var)
    return min(1.0, math.erfc(z / math.sqrt(2)))


@dataclass
class RatioCI:
    metric: str
    gm_ratio: float
    ci_low: float
    ci_high: float
    n_tasks: int
    n_pairs: int
    wilcoxon_p: float | None
    per_task: dict[str, float] = field(default_factory=dict)


def ratio_ci(
    trials: Sequence[TrialResult], metric: str, *, ref: str = "A", cand: str = "B",
    n_boot: int = 5000, seed: int = 0,
) -> RatioCI | None:
    per = paired_log_ratios(trials, metric, ref=ref, cand=cand)
    per = {k: v for k, v in per.items() if v}
    if not per:
        return None
    gm, lo, hi = cluster_bootstrap(per, n_boot=n_boot, seed=seed)
    medians = [statistics.median(v) for v in per.values()]
    return RatioCI(
        metric=metric, gm_ratio=gm, ci_low=lo, ci_high=hi, n_tasks=len(per),
        n_pairs=sum(len(v) for v in per.values()),
        wilcoxon_p=wilcoxon_signed_rank(medians),
        per_task={k: math.exp(sum(v) / len(v)) for k, v in per.items()},
    )


def pass_k(trials: Sequence[TrialResult], arm: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for t in trials:
        if not t.scored or t.arm != arm:
            continue
        d = out.setdefault(t.task_id, {"passes": 0, "runs": 0, "all_pass": False})
        d["runs"] += 1
        d["passes"] += 1 if t.success else 0
    for d in out.values():
        d["all_pass"] = d["runs"] > 0 and d["passes"] == d["runs"]
    return out


def _task_pass_rates(trials: Sequence[TrialResult], arm: str, k: int) -> dict[str, tuple[float, float]]:
    """Per task: (pass@1, pass@k). pass@k is the unbiased 1 - C(n-c, k)/C(n, k); k = n when n < k."""
    out = {}
    for task, d in pass_k(trials, arm).items():
        n, c = d["runs"], d["passes"]
        kk = min(k, n)
        out[task] = (c / n, 1.0 - math.comb(n - c, kk) / math.comb(n, kk))
    return out


def pass_at(trials: Sequence[TrialResult], arm: str, k: int) -> dict:
    """pass@1 and pass@k for one arm, averaged over tasks (each task weighs the same).

    Per task with n scored runs and c passes: pass@1 = c/n, and pass@k is the unbiased estimate
    1 - C(n-c, k)/C(n, k), the chance that at least one of k runs passes. A task with fewer than k
    scored runs (excluded trials) uses k = n, i.e. "passed at least once".
    """
    per = pass_k(trials, arm)
    if not per:
        return {"k": k, "tasks": 0, "runs": 0, "passes": 0, "pass@1": None, "pass@k": None}
    rates = list(_task_pass_rates(trials, arm, k).values())
    return {
        "k": k, "tasks": len(per), "runs": sum(d["runs"] for d in per.values()),
        "passes": sum(d["passes"] for d in per.values()),
        "pass@1": sum(r[0] for r in rates) / len(rates), "pass@k": sum(r[1] for r in rates) / len(rates),
    }


def pass_at_relative(
    trials: Sequence[TrialResult], k: int, *, ref: str = "A", cand: str = "B",
    n_boot: int = 5000, seed: int = 0, alpha: float = 0.05,
) -> dict[str, dict] | None:
    """B vs A on pass@1 and pass@k over the tasks both arms ran.

    diff is B - A (fraction; ×100 for percentage points) with a 95% bootstrap CI that resamples
    tasks, keeping each task's A and B values together. ratio is B ÷ A of the task means (None when
    A is 0).
    """
    ra, rb = _task_pass_rates(trials, ref, k), _task_pass_rates(trials, cand, k)
    tasks = sorted(set(ra) & set(rb))
    if not tasks:
        return None
    rng = random.Random(seed)
    n = len(tasks)
    out: dict[str, dict] = {}
    for idx, name in ((0, "pass@1"), (1, "pass@k")):
        a = [ra[t][idx] for t in tasks]
        b = [rb[t][idx] for t in tasks]
        d = [y - x for x, y in zip(a, b)]
        boots = sorted(sum(d[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
        lo_i = max(0, min(n_boot - 1, int(math.floor(alpha / 2 * n_boot))))
        hi_i = max(0, min(n_boot - 1, int(math.ceil((1 - alpha / 2) * n_boot)) - 1))
        ma, mb = sum(a) / n, sum(b) / n
        out[name] = {
            "a": ma, "b": mb, "diff": mb - ma, "ci_low": boots[lo_i], "ci_high": boots[hi_i],
            "ratio": mb / ma if ma > 0 else None, "n_tasks": n,
            "tasks_b_higher": sum(1 for x in d if x > 0), "tasks_b_lower": sum(1 for x in d if x < 0),
        }
    return out
