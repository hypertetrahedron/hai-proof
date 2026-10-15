import math

import pytest

from hai_proof.models import AgentMetrics, TrialResult
from hai_proof.stats import (
    cluster_bootstrap,
    paired_log_ratios,
    pass_at,
    pass_at_relative,
    pass_k,
    ratio_ci,
    wilcoxon_signed_rank,
)


def mk(arm, task, rep, cost, wall, ok, *, status="ok", pair=None):
    return TrialResult(
        run_id="r", arm=arm, treatment="x", task_id=task, rep=rep,
        pair_id=pair or f"{task}-{rep}", status=status,
        metrics=AgentMetrics(cost_usd=cost, wall_s=wall, tokens_input=int(cost * 1000)),
        acceptance_pass=ok, regression_pass=ok,
    )


def build(rows):
    """rows: (task, rep, cost_ref, cost_cand, wall_ref, wall_cand, pass_ref, pass_cand)"""
    out = []
    for task, rep, cr, cc, wr, wc, pr, pc in rows:
        out.append(mk("A", task, rep, cr, wr, pr))
        out.append(mk("B", task, rep, cc, wc, pc))
    return out


def table(n_tasks, reps, cost_f=1.0, wall_f=1.0, pass_ref=True, pass_cand=True, jitter=0.0):
    rows = []
    for ti in range(n_tasks):
        for r in range(reps):
            j = 1 + jitter * (((ti * 7 + r * 3) % 5) - 2) / 2
            rows.append((f"t{ti}", r, 1.0 * (1 + 0.1 * ti), 1.0 * (1 + 0.1 * ti) * cost_f * j,
                         60.0, 60.0 * wall_f * j, pass_ref, pass_cand))
    return build(rows)


# ------------------------------------------------------------------ wilcoxon

def test_wilcoxon_exact_known_values():
    assert wilcoxon_signed_rank([1, 2, 3, 4, 5, 6]) == pytest.approx(2 / 64)
    assert wilcoxon_signed_rank(list(range(1, 11))) == pytest.approx(2 / 1024)
    assert wilcoxon_signed_rank([-1, -2, -3, -4, -5, -6]) == pytest.approx(2 / 64)
    assert wilcoxon_signed_rank([]) is None
    assert wilcoxon_signed_rank([0, 0.0]) is None


def test_wilcoxon_symmetric_and_zeros():
    assert wilcoxon_signed_rank([1, -1]) == pytest.approx(1.0)
    # n=3 all positive: p = 2/8
    assert wilcoxon_signed_rank([0, 0.5, 1, 2]) == pytest.approx(0.25)
    # mixed: ranks 1..5, W+ = 1+2+4+5 = 12, P(W>=12) = count/32
    p = wilcoxon_signed_rank([1, 2, -3, 4, 5])
    # brute-force reference
    import itertools

    ranks = [1, 2, 3, 4, 5]
    sums = [sum(c) for r in range(6) for c in itertools.combinations(ranks, r)]
    w = 12
    expect = min(1.0, 2 * min(sum(s <= w for s in sums), sum(s >= w for s in sums)) / 32)
    assert p == pytest.approx(expect)


def test_wilcoxon_ties_use_average_ranks():
    # |values| = 1,1,2 -> ranks 1.5,1.5,3; all positive => only 1 of 8 subsets reaches the max
    assert wilcoxon_signed_rank([1, 1, 2]) == pytest.approx(2 / 8)
    # tie in abs with mixed signs: ranks 1.5,1.5,3 ; W+ = 1.5+3 = 4.5 ; sums<=4.5: {},1.5,1.5,3,3(=1.5+1.5),4.5,4.5 => 7/8 ; >=4.5: 4.5,4.5,6 => 3/8
    assert wilcoxon_signed_rank([1, -1, 2]) == pytest.approx(min(1.0, 2 * 3 / 8))


def test_wilcoxon_normal_approx_large_n():
    p = wilcoxon_signed_rank([i + 1 for i in range(40)])
    assert p is not None and p < 1e-6
    balanced = [(i + 1) * (1 if i % 2 else -1) for i in range(40)]
    assert wilcoxon_signed_rank(balanced) > 0.8
    assert 0 <= wilcoxon_signed_rank([1.0] * 20 + [-1.0] * 20) <= 1


# ------------------------------------------------------------------ ratios / bootstrap

def test_paired_log_ratios_filters():
    trials = build([("t1", 0, 1.0, 2.0, 10, 10, True, True), ("t1", 1, 1.0, 0.5, 10, 20, True, True)])
    r = paired_log_ratios(trials, "cost_usd")
    assert r["t1"] == pytest.approx([math.log(2), math.log(0.5)])
    assert paired_log_ratios(trials, "wall_s")["t1"] == pytest.approx([0.0, math.log(2)])
    assert paired_log_ratios(trials, "tokens_total")["t1"] == pytest.approx([math.log(2), math.log(0.5)])
    # excluded / warmup / probe / missing pair / zero value
    extra = [
        mk("A", "t2", 0, 1, 1, True, status="error"), mk("B", "t2", 0, 1, 1, True),
        mk("A", "t3", -1, 1, 1, True), mk("B", "t3", -1, 1, 1, True),
        mk("A", "t4", 0, 0.0, 1, True), mk("B", "t4", 0, 1, 1, True),
        mk("A", "t5", 0, 1, 1, True),
    ]
    r2 = paired_log_ratios(trials + extra, "cost_usd")
    assert set(r2) == {"t1"}
    noneM = mk("B", "t1", 5, 1, 1, True)
    noneM.metrics = None
    assert set(paired_log_ratios(trials + [noneM, mk("A", "t1", 5, 1, 1, True)], "cost_usd")) == {"t1"}


def test_paired_log_ratios_custom_arms():
    trials = build([("t1", 0, 1.0, 2.0, 10, 10, True, True)])
    r = paired_log_ratios(trials, "cost_usd", ref="B", cand="A")
    assert r["t1"] == pytest.approx([math.log(0.5)])


def test_bootstrap_deterministic_and_brackets():
    data = {"a": [0.1, 0.3, 0.2], "b": [0.5, 0.4, 0.6], "c": [-0.1, 0.0, 0.1], "d": [0.2, 0.2, 0.3]}
    r1 = cluster_bootstrap(data, n_boot=1000, seed=42)
    r2 = cluster_bootstrap(data, n_boot=1000, seed=42)
    assert r1 == r2
    gm, lo, hi = r1
    assert lo <= gm <= hi
    expect = math.exp(sum(sum(v) / len(v) for v in data.values()) / 4)
    assert gm == pytest.approx(expect)
    assert cluster_bootstrap(data, n_boot=1000, seed=43) != r1


def test_bootstrap_edge_cases():
    with pytest.raises(ValueError):
        cluster_bootstrap({})
    with pytest.raises(ValueError):
        cluster_bootstrap({"a": []})
    gm, lo, hi = cluster_bootstrap({"a": [0.0], "b": []}, n_boot=100)
    assert gm == lo == hi == 1.0
    gm, lo, hi = cluster_bootstrap({"a": [math.log(2)], "b": [math.log(2)], "c": [math.log(8)]}, n_boot=500)
    assert lo <= gm <= hi and lo >= 2 - 1e-9 and hi <= 8 + 1e-9


def test_ratio_ci():
    trials = table(5, 3, cost_f=2.0, wall_f=1.0, jitter=0.1)
    ci = ratio_ci(trials, "cost_usd", n_boot=500)
    assert ci.n_tasks == 5 and ci.n_pairs == 15
    assert ci.ci_low <= ci.gm_ratio <= ci.ci_high
    assert 1.8 < ci.gm_ratio < 2.2
    assert set(ci.per_task) == {f"t{i}" for i in range(5)}
    assert ci.wilcoxon_p == pytest.approx(2 / 32)
    assert ratio_ci([], "cost_usd") is None
    assert ratio_ci(table(2, 1), "bogus_metric") is None


# ------------------------------------------------------------------ pass_k

def test_pass_k():
    trials = build([
        ("t1", 0, 1, 1, 1, 1, True, True), ("t1", 1, 1, 1, 1, 1, True, False),
        ("t2", 0, 1, 1, 1, 1, False, True),
    ])
    trials.append(mk("A", "t9", 0, 1, 1, True, status="discarded"))
    a, b = pass_k(trials, "A"), pass_k(trials, "B")
    assert a == {"t1": {"passes": 2, "runs": 2, "all_pass": True}, "t2": {"passes": 0, "runs": 1, "all_pass": False}}
    assert b["t1"] == {"passes": 1, "runs": 2, "all_pass": False}
    assert b["t2"]["all_pass"] is True
    assert "t9" not in a


def test_pass_at():
    # t1: 3/3, t2: 1/3, t3: 0/3
    rows = [(t, r, 1, 1, 1, 1, ok, ok) for t, oks in (("t1", [1, 1, 1]), ("t2", [1, 0, 0]), ("t3", [0, 0, 0]))
            for r, ok in enumerate(map(bool, oks))]
    trials = build(rows)
    r = pass_at(trials, "A", 3)
    assert (r["k"], r["tasks"], r["runs"], r["passes"]) == (3, 3, 9, 4)
    assert r["pass@1"] == pytest.approx((1 + 1 / 3 + 0) / 3)
    assert r["pass@k"] == pytest.approx(2 / 3)
    # k=2 on t2: 1 - C(2,2)/C(3,2) = 2/3
    assert pass_at(trials, "A", 2)["pass@k"] == pytest.approx((1 + 2 / 3 + 0) / 3)
    # k=1 equals pass@1
    r1 = pass_at(trials, "A", 1)
    assert r1["pass@k"] == pytest.approx(r1["pass@1"])
    # fewer runs than k (an excluded trial) falls back to "passed at least once"
    short = [t for t in trials if not (t.task_id == "t2" and t.rep == 0)]
    assert pass_at(short, "A", 3)["pass@k"] == pytest.approx(1 / 3)
    assert pass_at([], "A", 3)["pass@1"] is None


def test_pass_at_relative():
    # A: t1 3/3, t2 3/3, t3 0/3; B: t1 3/3, t2 1/3, t3 3/3
    oks = {"t1": ([1, 1, 1], [1, 1, 1]), "t2": ([1, 1, 1], [1, 0, 0]), "t3": ([0, 0, 0], [1, 1, 1])}
    rows = [(t, r, 1, 1, 1, 1, bool(a[r]), bool(b[r])) for t, (a, b) in oks.items() for r in range(3)]
    rel = pass_at_relative(build(rows), 3, n_boot=500)
    p1 = rel["pass@1"]
    assert p1["a"] == pytest.approx(2 / 3) and p1["b"] == pytest.approx(7 / 9)
    assert p1["diff"] == pytest.approx(1 / 9) and p1["ratio"] == pytest.approx(7 / 6)
    assert p1["ci_low"] <= p1["diff"] <= p1["ci_high"]
    assert (p1["tasks_b_higher"], p1["tasks_b_lower"], p1["n_tasks"]) == (1, 1, 3)
    pk = rel["pass@k"]
    assert pk["a"] == pytest.approx(2 / 3) and pk["b"] == pytest.approx(1.0)
    assert (pk["tasks_b_higher"], pk["tasks_b_lower"]) == (1, 0)
    # A never passes: no ratio
    zero = build([("t1", 0, 1, 1, 1, 1, False, True)])
    assert pass_at_relative(zero, 1, n_boot=50)["pass@1"]["ratio"] is None
    assert pass_at_relative([], 3) is None
