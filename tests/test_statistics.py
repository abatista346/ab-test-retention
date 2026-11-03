"""Tests for the A/B test statistics and the SQL layer."""

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from analyze import mde, proportion_test, srm_check

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def test_srm_passes_for_balanced_split():
    result = srm_check(50_000, 50_100)
    assert not result["srm_detected"]
    assert result["p_value"] > 0.05


def test_srm_flags_broken_assignment():
    result = srm_check(50_000, 52_000)
    assert result["srm_detected"]


def test_proportion_test_direction_and_ci():
    r = proportion_test(success_c=2_000, n_c=10_000, success_t=1_800, n_t=10_000)
    assert r["abs_diff"] == pytest.approx(-0.02)
    assert r["abs_diff_ci95"][0] < r["abs_diff"] < r["abs_diff_ci95"][1]
    assert r["abs_diff_ci95"][1] < 0  # clearly significant drop
    assert r["p_value"] < 0.001


def test_proportion_test_no_effect():
    r = proportion_test(1_000, 5_000, 1_000, 5_000)
    assert r["abs_diff"] == 0
    assert r["abs_diff_ci95"][0] < 0 < r["abs_diff_ci95"][1]
    assert r["p_value"] == pytest.approx(1.0)


def test_mde_shrinks_with_sample_size():
    assert mde(0.19, 45_000) < mde(0.19, 5_000)
    # At ~45k per arm and a 19% base rate the detectable lift is under 1 percentage point.
    assert 0.003 < mde(0.19, 45_000) < 0.01


@pytest.fixture
def players() -> duckdb.DuckDBPyConnection:
    rng = np.random.default_rng(3)
    n = 1_000
    df = pd.DataFrame({
        "userid": np.arange(n),
        "version": np.where(np.arange(n) % 2 == 0, "gate_30", "gate_40"),
        "sum_gamerounds": rng.integers(0, 200, n),
        "retention_1": rng.random(n) < 0.45,
        "retention_7": rng.random(n) < 0.19,
    })
    con = duckdb.connect()
    con.register("players_df", df)
    con.execute("CREATE TABLE players AS SELECT * FROM players_df")
    return con


def test_data_quality_sql_on_clean_data(players):
    row = players.execute((SQL_DIR / "01_data_quality.sql").read_text()).df().iloc[0]
    assert row["n_rows"] == 1_000
    assert row["n_duplicate_rows"] == 0
    assert row["n_unknown_variant"] == 0
    assert row["n_invalid_rounds"] == 0


def test_data_quality_sql_catches_duplicates(players):
    players.execute("INSERT INTO players SELECT * FROM players LIMIT 3")
    row = players.execute((SQL_DIR / "01_data_quality.sql").read_text()).df().iloc[0]
    assert row["n_duplicate_rows"] == 3


def test_variant_summary_matches_pandas(players):
    summary = players.execute((SQL_DIR / "02_variant_summary.sql").read_text()).df().set_index("version")
    raw = players.execute("SELECT * FROM players").df()
    expected = raw.groupby("version")["retention_7"].mean()
    for v in ["gate_30", "gate_40"]:
        assert summary.loc[v, "players"] == 500
        assert summary.loc[v, "d7_rate"] == pytest.approx(expected[v])


def test_engagement_segments_cover_every_player(players):
    seg = players.execute((SQL_DIR / "03_engagement_segments.sql").read_text()).df()
    assert seg["players"].sum() == 1_000
