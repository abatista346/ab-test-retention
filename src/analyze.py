"""End-to-end A/B test readout for the Cookie Cats gate experiment.

Control  = gate_30 (first progression gate at level 30)
Treatment = gate_40 (gate moved to level 40)

Steps:
1. Load the CSV into DuckDB and run the SQL checks in sql/.
2. Sample-ratio mismatch (SRM) check — chi-square against the planned 50/50 split.
   If assignment is broken, no downstream result is trustworthy.
3. Primary metric (pre-declared): 7-day retention.
   Secondary: 1-day retention. Engagement (rounds played) is reported as a guardrail.
   Two-proportion z-tests with 95% CIs for the absolute difference,
   Holm correction across the two retention metrics, and a bootstrap
   check that does not rely on the normal approximation.
4. Engagement: heavy-tailed, so Mann-Whitney U plus a bootstrap CI of the
   difference in means after capping at the 99th percentile.
5. Power: minimum detectable effect at 80% power for this sample size,
   so a null result can be read as "no effect larger than X", not "no effect".
6. Decision written into README.md between the RESULTS markers.
"""

import json
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import confint_proportions_2indep, proportion_effectsize, proportions_ztest

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "cookie_cats.csv"
SQL_DIR = ROOT / "sql"
OUT = ROOT / "outputs"
FIG = OUT / "figures"
README = ROOT / "README.md"
START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"

CONTROL, TREATMENT = "gate_30", "gate_40"
ALPHA = 0.05
POWER = 0.80
N_BOOT = 2000
SEED = 7

COLOR_CONTROL = "#9AAABB"
COLOR_TREATMENT = "#1D5FD6"
COLOR_TEXT = "#4A5B6E"


def run_sql(con: duckdb.DuckDBPyConnection, name: str) -> pd.DataFrame:
    return con.execute((SQL_DIR / name).read_text()).df()


def srm_check(n_control: int, n_treatment: int) -> dict:
    total = n_control + n_treatment
    chi2, p = stats.chisquare([n_control, n_treatment], [total / 2, total / 2])
    return {"n_control": n_control, "n_treatment": n_treatment, "control_share": round(n_control / total, 4),
            "chi2": round(float(chi2), 3), "p_value": round(float(p), 4), "srm_detected": bool(p < 0.001)}


def proportion_test(success_c: int, n_c: int, success_t: int, n_t: int) -> dict:
    z, p = proportions_ztest([success_t, success_c], [n_t, n_c])
    lo, hi = confint_proportions_2indep(success_t, n_t, success_c, n_c, method="newcomb")
    rate_c, rate_t = success_c / n_c, success_t / n_t
    return {"control_rate": rate_c, "treatment_rate": rate_t, "abs_diff": rate_t - rate_c,
            "abs_diff_ci95": [float(lo), float(hi)], "rel_diff": (rate_t - rate_c) / rate_c, "z": float(z), "p_value": float(p)}


def bootstrap_diff(c: np.ndarray, t: np.ndarray, rng: np.random.Generator, stat=np.mean) -> np.ndarray:
    return np.array([stat(rng.choice(t, len(t))) - stat(rng.choice(c, len(c))) for _ in range(N_BOOT)])


def mde(rate: float, n_per_arm: int) -> float:
    """Smallest absolute lift detectable with ALPHA / POWER at this sample size."""
    h = NormalIndPower().solve_power(nobs1=n_per_arm, alpha=ALPHA, power=POWER, ratio=1.0)
    # Invert Cohen's h around the control rate.
    return float(np.sin(np.arcsin(np.sqrt(rate)) + h / 2) ** 2 - rate)


def main() -> None:
    con = duckdb.connect()
    con.execute(f"CREATE TABLE players AS SELECT * FROM read_csv_auto('{RAW.as_posix()}')")

    quality = run_sql(con, "01_data_quality.sql").iloc[0].to_dict()
    summary = run_sql(con, "02_variant_summary.sql").set_index("version")
    segments = run_sql(con, "03_engagement_segments.sql")
    players = con.execute("SELECT version, sum_gamerounds, CAST(retention_1 AS INT) r1, CAST(retention_7 AS INT) r7 FROM players").df()
    print("Data quality:", quality)
    print(summary)

    c, t = summary.loc[CONTROL], summary.loc[TREATMENT]
    srm = srm_check(int(c["players"]), int(t["players"]))

    d7 = proportion_test(int(c["retained_d7"]), int(c["players"]), int(t["retained_d7"]), int(t["players"]))
    d1 = proportion_test(int(c["retained_d1"]), int(c["players"]), int(t["retained_d1"]), int(t["players"]))
    _, holm_p, _, _ = multipletests([d7["p_value"], d1["p_value"]], method="holm")
    d7["p_holm"], d1["p_holm"] = float(holm_p[0]), float(holm_p[1])

    rng = np.random.default_rng(SEED)
    grp = {v: g for v, g in players.groupby("version")}
    boot_d7 = bootstrap_diff(grp[CONTROL]["r7"].to_numpy(), grp[TREATMENT]["r7"].to_numpy(), rng)
    d7["bootstrap_ci95"] = [float(x) for x in np.percentile(boot_d7, [2.5, 97.5])]
    d7["bootstrap_share_below_zero"] = float((boot_d7 < 0).mean())

    cap = float(players["sum_gamerounds"].quantile(0.99))
    rc = grp[CONTROL]["sum_gamerounds"].clip(upper=cap).to_numpy()
    rt = grp[TREATMENT]["sum_gamerounds"].clip(upper=cap).to_numpy()
    u_stat, u_p = stats.mannwhitneyu(rt, rc, alternative="two-sided")
    boot_rounds = bootstrap_diff(rc, rt, rng)
    engagement = {"cap_p99": cap, "mean_control_capped": float(rc.mean()), "mean_treatment_capped": float(rt.mean()),
                  "diff_ci95": [float(x) for x in np.percentile(boot_rounds, [2.5, 97.5])], "mann_whitney_p": float(u_p)}

    n_arm = int(min(c["players"], t["players"]))
    power = {"n_per_arm": n_arm, "mde_d7_abs": mde(float(c["d7_rate"]), n_arm), "mde_d1_abs": mde(float(c["d1_rate"]), n_arm)}

    results = {"data_quality": {k: (float(v) if isinstance(v, (int, float, np.number)) else v) for k, v in quality.items()},
               "srm": srm, "primary_d7": d7, "secondary_d1": d1, "engagement_guardrail": engagement, "power": power}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=float))
    print(json.dumps(results, indent=2, default=float))

    plot_retention(d1, d7)
    plot_bootstrap(boot_d7, d7)
    plot_segments(segments)
    write_readme(results, segments)


def plot_retention(d1: dict, d7: dict) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    labels = ["Day-1 retention", "Day-7 retention (primary)"]
    x = np.arange(2)
    for offset, key, color, name in [(-0.18, "control_rate", COLOR_CONTROL, "gate_30 (control)"), (0.18, "treatment_rate", COLOR_TREATMENT, "gate_40 (treatment)")]:
        vals = [d1[key] * 100, d7[key] * 100]
        bars = ax.bar(x + offset, vals, width=0.36, color=color, label=name)
        ax.bar_label(bars, fmt="%.1f%%", fontsize=9, color=COLOR_TEXT)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Players retained (%)")
    ax.set_title("Retention by variant", loc="left", fontsize=12, fontweight="bold")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG / "01_retention_by_variant.png", dpi=150)
    plt.close(fig)


def plot_bootstrap(boot: np.ndarray, d7: dict) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.hist(boot * 100, bins=50, color=COLOR_TREATMENT, alpha=0.85)
    ax.axvline(0, color=COLOR_TEXT, linestyle="--", linewidth=1.2, label="No difference")
    for edge in d7["bootstrap_ci95"]:
        ax.axvline(edge * 100, color=COLOR_CONTROL, linewidth=1.2)
    ax.set_xlabel("gate_40 − gate_30, day-7 retention (percentage points)")
    ax.set_ylabel("Bootstrap resamples")
    ax.set_title("Bootstrap distribution of the day-7 retention difference", loc="left", fontsize=12, fontweight="bold")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG / "02_bootstrap_d7_difference.png", dpi=150)
    plt.close(fig)


def plot_segments(seg: pd.DataFrame) -> None:
    pivot = seg.pivot_table(index=["bucket_order", "engagement_bucket"], columns="version", values="d7_rate").reset_index()
    fig, ax = plt.subplots(figsize=(9, 4.5))
    x = np.arange(len(pivot))
    ax.bar(x - 0.18, pivot[CONTROL] * 100, width=0.36, color=COLOR_CONTROL, label="gate_30")
    ax.bar(x + 0.18, pivot[TREATMENT] * 100, width=0.36, color=COLOR_TREATMENT, label="gate_40")
    ax.set_xticks(x, pivot["engagement_bucket"], fontsize=9)
    ax.set_ylabel("Day-7 retention (%)")
    ax.set_xlabel("Rounds played in first 14 days (descriptive — measured after assignment)")
    ax.set_title("Day-7 retention by engagement level", loc="left", fontsize=12, fontweight="bold")
    ax.legend(frameon=False, ncol=2, loc="lower right", bbox_to_anchor=(1.0, 1.0))
    fig.tight_layout()
    fig.savefig(FIG / "03_d7_by_engagement.png", dpi=150)
    plt.close(fig)


def pp(x: float) -> str:
    return f"{x * 100:+.2f} pp"


def write_readme(r: dict, seg: pd.DataFrame) -> None:
    srm, d7, d1, e, pw = r["srm"], r["primary_d7"], r["secondary_d1"], r["engagement_guardrail"], r["power"]
    d7_sig = d7["p_holm"] < ALPHA
    if srm["srm_detected"]:
        decision = "**Do not act on this test.** The sample-ratio check failed, which means assignment or logging is broken; results below are shown for completeness only."
    elif d7_sig and d7["abs_diff"] < 0:
        decision = (f"**Keep the gate at level 30.** Moving it to level 40 lowers 7-day retention by {abs(d7['abs_diff']) * 100:.2f} pp "
                    f"({d7['rel_diff']:.1%} relative; 95% CI {d7['abs_diff_ci95'][0] * 100:.2f} to {d7['abs_diff_ci95'][1] * 100:.2f} pp), "
                    "and the result survives multiple-testing correction and a bootstrap check that makes no normality assumption.")
    elif d7_sig and d7["abs_diff"] > 0:
        decision = (f"**Ship the gate at level 40.** It raises 7-day retention by {d7['abs_diff'] * 100:.2f} pp "
                    f"(95% CI {d7['abs_diff_ci95'][0] * 100:.2f} to {d7['abs_diff_ci95'][1] * 100:.2f} pp).")
    else:
        decision = (f"**No detectable effect on 7-day retention.** With {pw['n_per_arm']:,} players per arm the test could detect a change of about "
                    f"{pw['mde_d7_abs'] * 100:.2f} pp; any true effect is smaller than that. Decide on other grounds (e.g. monetization) or extend the test.")

    lines = [
        START, "",
        "## Results", "",
        f"**Decision:** {decision}", "",
        "| Check | gate_30 | gate_40 | Difference (95% CI) | p (Holm) |",
        "|---|---|---|---|---|",
        f"| Sample ratio (SRM, χ² vs 50/50) | {srm['n_control']:,} | {srm['n_treatment']:,} | control share {srm['control_share']:.2%} | p = {srm['p_value']:.3f} |",
        f"| **Day-7 retention (primary)** | {d7['control_rate']:.2%} | {d7['treatment_rate']:.2%} | {pp(d7['abs_diff'])} ({d7['abs_diff_ci95'][0] * 100:.2f} to {d7['abs_diff_ci95'][1] * 100:.2f}) | {d7['p_holm']:.4f} |",
        f"| Day-1 retention | {d1['control_rate']:.2%} | {d1['treatment_rate']:.2%} | {pp(d1['abs_diff'])} ({d1['abs_diff_ci95'][0] * 100:.2f} to {d1['abs_diff_ci95'][1] * 100:.2f}) | {d1['p_holm']:.4f} |",
        f"| Rounds played, capped at p99 (guardrail) | {e['mean_control_capped']:.1f} | {e['mean_treatment_capped']:.1f} | {e['diff_ci95'][0]:+.1f} to {e['diff_ci95'][1]:+.1f} rounds | Mann-Whitney p = {e['mann_whitney_p']:.3f} |",
        "",
        f"- **Assignment is {'not ' if srm['srm_detected'] else ''}healthy**: the split is {srm['control_share']:.2%} / {1 - srm['control_share']:.2%} (SRM p = {srm['p_value']:.3f}).",
        f"- **Robustness**: the bootstrap 95% interval for the day-7 difference is {d7['bootstrap_ci95'][0] * 100:.2f} to {d7['bootstrap_ci95'][1] * 100:.2f} pp, "
        f"and {d7['bootstrap_share_below_zero']:.1%} of resamples fall below zero.",
        f"- **Sensitivity**: at 80% power and α = 0.05 this sample detects absolute changes of ~{pw['mde_d7_abs'] * 100:.2f} pp in day-7 and ~{pw['mde_d1_abs'] * 100:.2f} pp in day-1 retention.",
        "",
        "![Retention by variant](outputs/figures/01_retention_by_variant.png)",
        "![Bootstrap distribution](outputs/figures/02_bootstrap_d7_difference.png)",
        "",
        "### Where the effect comes from (descriptive)", "",
        "Rounds played is measured *after* assignment, so splitting by it is not a randomized comparison — the gate itself can change "
        "who ends up in each bucket. The chart is useful to see *where* retention diverges, not to estimate a causal effect within a bucket.", "",
        "![Day-7 retention by engagement](outputs/figures/03_d7_by_engagement.png)", "",
        END,
    ]
    section = "\n".join(lines)
    text = README.read_text()
    text = text.split(START)[0] + section + text.split(END)[1] if START in text and END in text else text + "\n" + section + "\n"
    README.write_text(text)
    print("README results section updated")


if __name__ == "__main__":
    main()
