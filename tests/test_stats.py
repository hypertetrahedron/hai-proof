import math

import pytest

from hai_proof.models import AgentMetrics, TrialResult
from hai_proof.stats import (
    cluster_bootstrap,
    paired_log_ratios,
    pass_k,
    ratio_ci,
    verdict,
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


# ------------------------------------------------------------------ verdicts

def test_verdict_single_is_none():
    assert verdict(table(3, 3), shape="single", reps=3) is None


def test_stat_harmful_task_regression():
    rows = []
    for ti in range(4):
        for r in range(3):
            rows.append((f"t{ti}", r, 1, 1, 1, 1, True, not (ti == 0 and r == 2)))
    v = verdict(build(rows), shape="comparative", reps=3, n_boot=200)
    assert v.code == "HARMFUL" and v.label == "HARMFUL" and not v.indicative
    assert "t0" in v.reasons[0]


def test_stat_harmful_success_rate_drop():
    rows = []
    for ti in range(5):
        for r in range(4):
            pr = ti % 2 == 0 or r < 3  # ref fails on some cells
            rows.append((f"t{ti}", r, 1, 1, 1, 1, pr, pr and not (ti == 1 and r == 0) and not (ti == 3 and r == 1)))
    trials = build(rows)
    v = verdict(trials, shape="ab", reps=4, n_boot=200)
    # no task where ref all_pass & cand not? ti=0,2,4 ref all pass and cand too; ti=1,3 ref fails a run
    assert v.code == "HARMFUL" and v.label == "B HARMFUL VS A"
    assert "success rate" in v.reasons[0]


def test_stat_costlier():
    v = verdict(table(6, 3, cost_f=1.6, wall_f=1.0, jitter=0.05), shape="comparative", reps=3, n_boot=500)
    assert v.code == "COSTLIER" and v.label == "COSTS MORE THAN IT'S WORTH"
    v = verdict(table(6, 3, cost_f=1.0, wall_f=1.6, jitter=0.05), shape="ab", reps=3, n_boot=500)
    assert v.code == "COSTLIER" and v.label == "B COSTS MORE THAN A"
    assert any("cost ratio" in r for r in v.reasons)


def test_stat_cheaper_on_costs():
    v = verdict(table(6, 3, cost_f=0.5, wall_f=0.5, jitter=0.05), shape="comparative", reps=3, n_boot=500)
    assert v.code == "CHEAPER" and v.label == "PAYS FOR ITSELF"
    v = verdict(table(6, 3, cost_f=0.5, wall_f=0.5, jitter=0.05), shape="ab", reps=3, n_boot=500)
    assert v.label == "B CHEAPER THAN A"


def test_stat_cheaper_when_only_cost_cheaper_is_not_enough():
    v = verdict(table(6, 3, cost_f=0.5, wall_f=1.0, jitter=0.05), shape="comparative", reps=3, n_boot=500)
    assert v.code == "INCONCLUSIVE"


def test_stat_cheaper_via_strictly_better_success():
    rows = []
    for ti in range(4):
        for r in range(3):
            rows.append((f"t{ti}", r, 1, 1.0, 1, 1.0, not (ti == 0), True))
    v = verdict(build(rows), shape="comparative", reps=3, n_boot=200)
    assert v.code == "CHEAPER"
    assert any("strictly better" in r for r in v.reasons)


def test_stat_no_difference():
    v = verdict(table(6, 3, jitter=0.1), shape="comparative", reps=3, n_boot=500)
    assert v.code == "NO_DIFFERENCE" and v.label == "NO MEANINGFUL DIFFERENCE" and not v.indicative


def test_stat_inconclusive_wide_ci():
    rows = []
    factors = [0.4, 2.5, 0.5, 2.0, 1.0, 1.1]
    for ti, f in enumerate(factors):
        for r in range(2):
            rows.append((f"t{ti}", r, 1, f, 1, f, True, True))
    v = verdict(build(rows), shape="comparative", reps=2, n_boot=500)
    assert v.code == "INCONCLUSIVE" and v.label == "INCONCLUSIVE"


def test_stat_no_pairs_inconclusive():
    trials = [mk("A", "t1", 0, 1, 1, True), mk("B", "t1", 0, 1, 1, True, pair="other")]
    assert verdict(trials, shape="comparative", reps=3, n_boot=50).code == "INCONCLUSIVE"


def test_stat_deterministic():
    t = table(5, 3, cost_f=1.1, jitter=0.2)
    a = verdict(t, shape="comparative", reps=3, n_boot=300, seed=7)
    b = verdict(t, shape="comparative", reps=3, n_boot=300, seed=7)
    assert a == b


def test_lightning_branches():
    v = verdict(table(6, 1, cost_f=2.0, wall_f=1.0), shape="comparative", reps=1)
    assert v.code == "COSTLIER" and v.label == "LIKELY COSTLIER" and v.indicative
    v = verdict(table(6, 1, cost_f=0.5, wall_f=0.5), shape="ab", reps=1)
    assert v.code == "CHEAPER" and v.label == "LIKELY CHEAPER"
    v = verdict(table(6, 1, cost_f=1.2, wall_f=0.9), shape="comparative", reps=1)
    assert v.code == "NO_DIFFERENCE" and v.label == "NO OBVIOUS DIFFERENCE"
    # harmful: ref passes, cand fails
    rows = [(f"t{i}", 0, 1, 1, 1, 1, True, i != 2) for i in range(6)]
    v = verdict(build(rows), shape="comparative", reps=1)
    assert v.code == "HARMFUL" and v.label == "LIKELY HARMFUL" and "t2" in v.reasons[0]


def test_lightning_needs_five_of_six_and_gm():
    def rows_with(factors):
        return build([(f"t{i}", 0, 1.0, f, 1.0, 1.0, True, True) for i, f in enumerate(factors)])

    # 5 of 6 higher, gm = (1.6**5 * 0.9)**(1/6) > 1.5? 1.6^5=10.49*0.9=9.44 -> ^(1/6)=1.45 -> no
    assert verdict(rows_with([1.6] * 5 + [0.9]), shape="comparative", reps=1).code == "NO_DIFFERENCE"
    assert verdict(rows_with([2.0] * 5 + [0.9]), shape="comparative", reps=1).code == "COSTLIER"
    # only 4 of 6 higher even with big gm
    assert verdict(rows_with([4.0] * 4 + [0.9, 0.9]), shape="comparative", reps=1).code == "NO_DIFFERENCE"
    assert verdict(rows_with([0.4] * 5 + [1.1]), shape="comparative", reps=1).code == "CHEAPER"
    # smaller suites: ceil(5/6*4) = 4
    assert verdict(rows_with([2.0] * 4), shape="comparative", reps=1).code == "COSTLIER"
    assert verdict(rows_with([2.0] * 3 + [0.9]), shape="comparative", reps=1).code == "NO_DIFFERENCE"
