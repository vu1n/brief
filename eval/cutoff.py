"""Choose a System One gate's cutoff from saved scores and stated costs, cross-validated.

Every brief gate turns P(a person should see this) into an action: below the cutoff the
model clears it (auto-ratify, suppress the ask), at or above it a person sees it. The two
mistakes cost different amounts, so state them first and let the data pick the cutoff:

- a **needless review**: a harmless case reaches a person. This is the unit (cost 1).
- a **miss**: a case a person should have seen is cleared. `--miss-cost` says how many
  needless reviews one miss is worth.

A cutoff is only as good as the rule that picked it, so the rule is judged on cases it
didn't see (Husain and Saha, "How To Use Decision Models for Evals", 2026-10-20): repeated
stratified k-fold, the rule picks a cutoff on the training folds, the held-out fold says what
it costs. Two rules are compared against "a person sees everything" and the shipped cutoff:

- **empirical:** the cutoff with the least training cost (fewest misses on a tie, then the
  lower cutoff), optionally capped below the lowest training should-see score minus a margin.
- **calibrated:** Platt-scale the scores on the training folds, then clear a case when its
  calibrated P is below 1 / (1 + miss_cost), the Bayes-optimal rule if calibration holds.

No model calls: it reads `eval/*/results/*.jsonl`. Stdlib only.

    python eval/cutoff.py eval/amend/results/clef.jsonl --miss-cost 20
    python eval/cutoff.py eval/amend/results/clef.jsonl --sweep 5,10,20,50,100
    python eval/cutoff.py eval/s1/results/typesafe_jev-1.13.jsonl --shipped 0.1
    python eval/cutoff.py --pool eval/amend/results/clef.jsonl eval/amend/results/feedback/clef.jsonl
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

# result-file shape -> (label field: True = a person should see it, score field)
SHAPES = (("escalate", "review"), ("violates", "p"))


def load(paths: list[Path]) -> list[tuple[float, bool]]:
    """(score, should_see) per scored row of every file, pooled. A row with no score escalates
    in brief, so it is neither a miss nor a saving at any cutoff and drops out."""
    out, models = [], set()
    for path in paths:
        rows = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
        label, score = next((s for s in SHAPES if rows and set(s) <= rows[0].keys()), (None, None))
        if label is None:
            sys.exit(f"{path}: rows need one of {SHAPES}")
        # "@cf/cloudflare/clef" (CI) and "clef" (eval) are one model; anything else stays whole
        models |= {r["model"].removeprefix("@cf/cloudflare/") for r in rows if r.get("model")}
        out += [(float(r[score]), bool(r[label])) for r in rows if r.get(score) is not None]
    if len(models) > 1:  # a resumed run against another endpoint: scales don't compare
        sys.exit(f"{' + '.join(map(str, paths))}: scores from more than one model ({', '.join(sorted(models))})")
    return out


def counts(data, t: float) -> tuple[int, int]:
    """(misses, needless reviews) when cases scoring below `t` are cleared."""
    return (sum(p < t for p, y in data if y), sum(p >= t for p, y in data if not y))


def cost(data, t: float, miss_cost: float) -> float:
    m, r = counts(data, t)
    return miss_cost * m + r


def empirical(train, miss_cost: float, margin: float | None) -> float:
    """Least-cost cutoff on `train`; with `margin`, never above lowest should-see - margin."""
    ps = sorted({p for p, _ in train})
    cands = [0.0] + [(a + b) / 2 for a, b in zip(ps, ps[1:])] + [ps[-1] + 1e-9]
    if margin is not None:
        cap = min((p for p, y in train if y), default=1.0) - margin
        cands = [t for t in cands if t <= cap] or [0.0]
    return min(cands, key=lambda t: (cost(train, t, miss_cost), counts(train, t)[0], t))


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def platt(train, ridge: float = 1e-2) -> tuple[float, float]:
    """(a, b) for P(should see) = sigmoid(a * logit(p) + b), by Newton's method. The small
    ridge keeps a separable training set (no overlap at all) from running off to infinity."""
    xs = [_logit(p) for p, _ in train]
    ys = [1.0 if y else 0.0 for _, y in train]
    a, b = 1.0, 0.0
    for _ in range(100):
        ga, gb, haa, hab, hbb = ridge * a, ridge * b, ridge, 0.0, ridge
        for x, y in zip(xs, ys):
            q = _sigmoid(a * x + b)
            w = q * (1 - q)
            ga += (q - y) * x
            gb += q - y
            haa += w * x * x
            hab += w * x
            hbb += w
        det = haa * hbb - hab * hab
        da, db = (hbb * ga - hab * gb) / det, (haa * gb - hab * ga) / det
        a, b = a - da, b - db
        if abs(da) + abs(db) < 1e-9:
            break
    return a, b


def calibrate(p: float, ab: tuple[float, float]) -> float:
    return _sigmoid(ab[0] * _logit(p) + ab[1])


def brier(pairs) -> float:
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def folds(data, k: int, rng: random.Random) -> list[list[int]]:
    """Stratified k-fold indices: should-see and harmless dealt round-robin."""
    out = [[] for _ in range(k)]
    for cls in (True, False):
        idx = [i for i, (_, y) in enumerate(data) if y is cls]
        rng.shuffle(idx)
        for j, i in enumerate(idx):
            out[j % k].append(i)
    return out


def crossval(data, miss_cost: float, shipped: float | None, margin: float | None,
             k: int, repeats: int, seed: int) -> dict:
    """Held-out (misses, needless reviews) per rule, summed over every repeat, plus the
    out-of-fold calibrated scores for a Brier comparison."""
    rules = ("everything to a person", "empirical", "calibrated") + (("shipped",) if shipped is not None else ())
    # "shipped" is scored on the same held-out folds, but it was picked on all the data: its
    # row is in-sample however it is split, and only the two rules are honest estimates.
    tot = {r: [0, 0] for r in rules}
    cuts = {"empirical": [], "calibrated": []}
    oof = []
    rng = random.Random(seed)
    for _ in range(repeats):
        for held in folds(data, k, rng):
            hs = set(held)
            train = [d for i, d in enumerate(data) if i not in hs]
            test = [data[i] for i in held]
            ab = platt(train)
            t_emp = empirical(train, miss_cost, margin)
            cuts["empirical"].append(t_emp)
            oof += [(calibrate(p, ab), y) for p, y in test]
            # calibrated P < 1/(1+c) is the raw cutoff below, the rule brief deploys (p < cutoff).
            # A flat or inverted fit has no such cutoff: fail closed and clear nothing.
            t_cal = _raw_for(1 / (1 + miss_cost), ab)
            t_cal = 0.0 if t_cal != t_cal else t_cal
            cuts["calibrated"].append(t_cal)
            for rule, t in (("everything to a person", 0.0), ("empirical", t_emp), ("calibrated", t_cal),
                            ("shipped", shipped)):
                if rule in tot:
                    m, r = counts(test, t)
                    tot[rule][0] += m
                    tot[rule][1] += r
    return {"totals": tot, "cuts": cuts, "oof": oof}


def _raw_for(q: float, ab: tuple[float, float]) -> float:
    """The raw score whose calibrated value is q (nan when Platt came out flat/inverted)."""
    a, b = ab
    if a <= 0:
        return float("nan")
    return _sigmoid((_logit(q) - b) / a)


def upper95(k: int, n: int) -> float:
    """One-sided 95% upper bound on a rate seen k times in n (exact for k=0: rule of three)."""
    if n == 0:
        return 1.0
    lo, hi = k / n, 1.0
    for _ in range(60):  # Clopper-Pearson by bisection on the binomial tail
        mid = (lo + hi) / 2
        tail = sum(math.comb(n, i) * mid ** i * (1 - mid) ** (n - i) for i in range(k + 1))
        lo, hi = (mid, hi) if tail > 0.05 else (lo, mid)
    return hi


def report(paths: list[Path], miss_cost: float, shipped: float | None, margin: float | None,
           k: int, repeats: int, seed: int) -> str:
    data = load(paths)
    path = " + ".join(map(str, paths))
    pos = sum(y for _, y in data)
    neg = len(data) - pos
    cv = crossval(data, miss_cost, shipped, margin, k, repeats, seed)
    n_pos, n_neg = pos * repeats, neg * repeats
    base_cost = neg  # everything to a person: every harmless case is a needless review
    lines = [f"{path}: {len(data)} scored ({pos} should see, {neg} harmless); "
             f"a miss costs {miss_cost:g} needless reviews; {repeats}x stratified {k}-fold", "",
             "| rule | cutoff (median over folds) | misses held out | harmless cleared held out | "
             "cost per 100 cases | vs everything to a person |",
             "|---|---|---|---|---|---|"]
    for rule, (m, r) in cv["totals"].items():
        cuts = cv["cuts"].get(rule)
        cut = (f"{sorted(cuts)[len(cuts) // 2]:.3f}" if cuts else
               ("0 (clears nothing)" if rule.startswith("everything") else f"{shipped:g}"))
        per100 = 100 * (miss_cost * m + r) / (len(data) * repeats)
        saving = 1 - (miss_cost * m + r) / (base_cost * repeats) if base_cost else 0.0
        lines.append(f"| {rule} | {cut} | {m}/{n_pos} ({m / max(n_pos, 1):.1%}) | "
                     f"{n_neg - r}/{n_neg} ({(n_neg - r) / max(n_neg, 1):.0%}) | {per100:.1f} | {saving:+.0%} |")
    t_all = empirical(data, miss_cost, margin)
    m_all, r_all = counts(data, t_all)
    ab = platt(data)
    oof = cv["oof"]
    lines += ["",
              f"Empirical rule on all {len(data)}: cutoff {t_all:.3f} "
              f"({m_all} misses, clears {neg - r_all}/{neg} harmless in-sample).",
              f"In-sample misses are not a miss rate: {m_all} in {pos} still allows up to "
              f"{upper95(m_all, pos):.1%} at 95%.",
              f"Brier raw {brier([(p, y) for p, y in data]):.3f}, Platt out-of-fold {brier(oof):.3f}; "
              f"Platt on all: a={ab[0]:.2f} b={ab[1]:.2f}, so calibrated P = 1/(1+{miss_cost:g}) "
              f"at raw {_raw_for(1 / (1 + miss_cost), ab):.3f}."]
    if shipped is not None:
        m_s, r_s = counts(data, shipped)
        lines.append(f"Shipped {shipped:g} (picked on these cases, so its row above is in-sample): "
                     f"{m_s} misses, clears {neg - r_s}/{neg} harmless.")
    for t in sorted({_raw_for(1 / (1 + miss_cost), ab)} | ({shipped} if shipped is not None else set())):
        if t == t:  # not nan
            exp = sum(calibrate(p, ab) for p, _ in data if p < t)
            lines.append(f"Platt-implied misses at {t:.3f}: {100 * exp / len(data):.2f} per 100 cases "
                         f"(a case scoring just under it is should-see with P={calibrate(t, ab):.3f}, "
                         f"so it pays when a miss costs under {(1 - calibrate(t, ab)) / calibrate(t, ab):.0f}).")
    lines += ["", "Lowest should-see scores: " +
              ", ".join(f"{p:.3f}" for p in sorted(p for p, y in data if y)[:5]),
              "Calibration (raw score bin: should-see / n):  " + "  ".join(
                  f"[{lo:.1f},{lo + 0.2:.1f}) {sum(y for p, y in data if lo <= p < lo + 0.2)}/"
                  f"{sum(lo <= p < lo + 0.2 for p, _ in data)}" for lo in (0.0, 0.2, 0.4, 0.6, 0.8))]
    return "\n".join(lines)


def sweep(paths: list[Path], costs: list[float], shipped: float | None, margin: float | None,
          k: int, repeats: int, seed: int) -> str:
    """One row per miss cost: which rule wins held out, and at what cutoff."""
    data = load(paths)
    path = " + ".join(map(str, paths))
    n = len(data) * repeats
    lines = [f"{path}: held-out cost per 100 cases by miss cost ({repeats}x {k}-fold)", "",
             "| a miss costs | everything to a person | empirical (cutoff) | calibrated (cutoff) |"
             + (f" shipped {shipped:g} |" if shipped is not None else ""),
             "|---|---|---|---|" + ("---|" if shipped is not None else "")]
    for c in costs:
        cv = crossval(data, c, shipped, margin, k, repeats, seed)
        cell = {r: 100 * (c * m + x) / n for r, (m, x) in cv["totals"].items()}
        med = {r: sorted(v)[len(v) // 2] for r, v in cv["cuts"].items()}
        row = (f"| {c:g} | {cell['everything to a person']:.1f} | {cell['empirical']:.1f} "
               f"({med['empirical']:.3f}) | {cell['calibrated']:.1f} ({med['calibrated']:.3f}) |")
        if shipped is not None:
            row += f" {cell['shipped']:.1f} |"
        lines.append(row)
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("results", type=Path, nargs="+")
    ap.add_argument("--pool", action="store_true",
                    help="one dataset from every file (same model), e.g. eval cases + feedback/")
    ap.add_argument("--miss-cost", type=float, default=20.0,
                    help="a miss costs this many needless reviews (default 20)")
    ap.add_argument("--sweep", help="comma-separated miss costs: one table row each")
    ap.add_argument("--shipped", type=float, help="the cutoff in the code, to score alongside")
    ap.add_argument("--margin", type=float,
                    help="cap the empirical cutoff at lowest training should-see minus this")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--repeats", type=int, default=200,
                    help="a miss needs its few lowest should-see cases held out together: repeat enough to see it")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    for path in ([a.results] if a.pool else [[p] for p in a.results]):
        if a.sweep:
            print(sweep(path, [float(x) for x in a.sweep.split(",")], a.shipped, a.margin,
                        a.folds, a.repeats, a.seed))
        else:
            print(report(path, a.miss_cost, a.shipped, a.margin, a.folds, a.repeats, a.seed))
        print()


if __name__ == "__main__":
    main()
