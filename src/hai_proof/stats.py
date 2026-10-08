"""Paired efficiency statistics and verdict rules (DESIGN §6, §7). Pure Python."""

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


@dataclass
class Verdict:
    code: str
    label: str
    indicative: bool
    reasons: list[str] = field(default_factory=list)


_LABELS = {
    "comparative": {
        "HARMFUL": "HARMFUL",
        "COSTLIER": "COSTS MORE THAN IT'S WORTH",
        "CHEAPER": "PAYS FOR ITSELF",
        "NO_DIFFERENCE": "NO MEANINGFUL DIFFERENCE",
        "INCONCLUSIVE": "INCONCLUSIVE",
    },
    "ab": {
        "HARMFUL": "B HARMFUL VS A",
        "COSTLIER": "B COSTS MORE THAN A",
        "CHEAPER": "B CHEAPER THAN A",
        "NO_DIFFERENCE": "NO MEANINGFUL DIFFERENCE",
        "INCONCLUSIVE": "INCONCLUSIVE",
    },
    "lightning": {
        "HARMFUL": "LIKELY HARMFUL",
        "COSTLIER": "LIKELY COSTLIER",
        "CHEAPER": "LIKELY CHEAPER",
        "NO_DIFFERENCE": "NO OBVIOUS DIFFERENCE",
        "INCONCLUSIVE": "INCONCLUSIVE",
    },
}


def _success_rate(trials: Sequence[TrialResult], arm: str) -> float:
    s = [t for t in trials if t.scored and t.arm == arm]
    return sum(1 for t in s if t.success) / len(s) if s else 0.0


def _task_disagreements(ref_pk: dict, cand_pk: dict) -> tuple[list[str], list[str]]:
    worse, better = [], []
    for task in sorted(set(ref_pk) & set(cand_pk)):
        r, c = ref_pk[task]["all_pass"], cand_pk[task]["all_pass"]
        if r and not c:
            worse.append(task)
        elif c and not r:
            better.append(task)
    return worse, better


def _task_ratios(trials: Sequence[TrialResult], metric: str) -> list[float]:
    per = paired_log_ratios(trials, metric)
    return [sum(v) / len(v) for v in per.values() if v]


def verdict(
    trials: Sequence[TrialResult], *, shape: str, reps: int, margin: float = 0.15,
    n_boot: int = 5000, seed: int = 0,
) -> Verdict | None:
    if shape == "single":
        return None
    lightning = reps < 2
    labels = _LABELS["lightning" if lightning else ("ab" if shape == "ab" else "comparative")]

    def mk(code: str, reasons: list[str]) -> Verdict:
        return Verdict(code, labels[code], lightning, reasons)

    ref_pk, cand_pk = pass_k(trials, "A"), pass_k(trials, "B")
    worse, better = _task_disagreements(ref_pk, cand_pk)

    if lightning:
        if worse:
            return mk("HARMFUL", [f"A passes and B fails on: {', '.join(worse)}"])
        reasons: list[str] = []
        stats_by_metric = {}
        for metric in ("cost_usd", "wall_s"):
            logs = _task_ratios(trials, metric)
            n = len(logs)
            if n == 0:
                continue
            gm = math.exp(sum(logs) / n)
            up = sum(1 for r in logs if r > 0)
            down = sum(1 for r in logs if r < 0)
            stats_by_metric[metric] = (n, gm, up, down)
            reasons.append(f"{metric}: gm ratio {gm:.2f}, {up}/{n} tasks higher, {down}/{n} lower")
        for metric, (n, gm, up, _down) in stats_by_metric.items():
            if up >= (5 * n + 5) // 6 and gm > 1.5:
                return mk("COSTLIER", reasons)
        for metric, (n, gm, _up, down) in stats_by_metric.items():
            if down >= (5 * n + 5) // 6 and gm < 1 / 1.5:
                return mk("CHEAPER", reasons)
        return mk("NO_DIFFERENCE", reasons)

    ref_rate, cand_rate = _success_rate(trials, "A"), _success_rate(trials, "B")
    if worse:
        return mk("HARMFUL", [f"A passes all runs but B does not on: {', '.join(worse)}"])
    if cand_rate <= ref_rate - 0.10 + 1e-9:
        return mk("HARMFUL", [f"B success rate {cand_rate:.0%} vs A {ref_rate:.0%}"])

    cost = ratio_ci(trials, "cost_usd", n_boot=n_boot, seed=seed)
    wall = ratio_ci(trials, "wall_s", n_boot=n_boot, seed=seed)
    reasons = []
    for name, ci in (("cost", cost), ("wall", wall)):
        if ci is not None:
            reasons.append(
                f"{name} ratio {ci.gm_ratio:.2f} (95% CI {ci.ci_low:.2f}-{ci.ci_high:.2f}, "
                f"{ci.n_tasks} tasks, {ci.n_pairs} pairs)"
            )
    lo_m, hi_m = 1 - margin, 1 + margin
    if cost is None or wall is None:
        return mk("INCONCLUSIVE", reasons + ["no paired scored trials for cost or wall"])
    if cost.ci_low > hi_m or wall.ci_low > hi_m:
        return mk("COSTLIER", reasons)
    if (cost.ci_high < lo_m and wall.ci_high < lo_m) or better:
        if better:
            reasons.append(f"B strictly better success on: {', '.join(better)}")
        return mk("CHEAPER", reasons)
    if all(ci.ci_low >= lo_m and ci.ci_high <= hi_m for ci in (cost, wall)):
        return mk("NO_DIFFERENCE", reasons)
    return mk("INCONCLUSIVE", reasons)
