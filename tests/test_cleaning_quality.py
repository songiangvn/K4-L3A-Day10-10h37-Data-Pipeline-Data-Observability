from __future__ import annotations

from dataclasses import replace

import pandas as pd

from core.utils import read_json
from ingestion.cleaning import build_clean_dataframe
from ingestion.corruption import corrupt_clean_dataframe
from observability.quality import build_freshness_report, run_data_quality_checks
from tests.conftest import RUN_DATE


def test_clean_dataframe_shape_and_columns(clean_df):
    assert len(clean_df) == 24
    assert clean_df["paper_id"].is_unique
    for column in ("age_days", "authors_joined", "categories_joined", "summary_chars", "text_for_embedding"):
        assert column in clean_df.columns
    text = clean_df.loc[0, "text_for_embedding"]
    for part in ("Title:", "Authors:", "Published:", "Categories:", "Summary:"):
        assert part in text
    assert list(clean_df["published"]) == sorted(clean_df["published"], reverse=True)


def test_age_days_computed_from_run_date(clean_df):
    row = clean_df[clean_df["published"] == "2026-07-22"].iloc[0]
    assert row["age_days"] == (pd.Timestamp("2026-09-25") - pd.Timestamp("2026-07-22")).days


def test_cleaning_dedupes_strips_tags_and_drops_bad_rows(records):
    dirty = records + [
        replace(records[0], title="  <b>Updated</b>   copy ", updated="2027-01-01"),
        replace(records[1], paper_id="10.9/empty", summary="   "),
    ]
    df = build_clean_dataframe(dirty, RUN_DATE)
    assert len(df) == 24
    assert df.set_index("paper_id").loc[records[0].paper_id, "title"] == "Updated copy"


def test_cleaning_empty_input():
    assert build_clean_dataframe([], RUN_DATE).empty


def test_quality_gate_passes_on_clean(clean_df, settings):
    report = run_data_quality_checks(clean_df, settings, "baseline")
    assert report["success"] is True
    assert report["evaluated_expectations"] >= 4
    assert report["engine"].startswith("great_expectations 1.")
    assert settings.paths.baseline_quality_report.exists()


def test_quality_gate_fails_on_corrupted(clean_df, settings):
    corrupted = corrupt_clean_dataframe(clean_df, settings.paths.corruption_log)
    report = run_data_quality_checks(corrupted, settings, "corrupted")
    assert report["success"] is False
    assert {"paper_id_unique", "summary_min_length", "title_min_length"} <= set(report["failed_checks"])
    assert report["freshness"]["is_fresh"] is False
    assert settings.paths.corrupted_quality_report.exists()


def test_quality_gate_row_count(clean_df, settings):
    report = run_data_quality_checks(clean_df.head(3), settings, "tiny")
    assert "row_count_between" in report["failed_checks"]


def test_freshness_report(clean_df, settings):
    report = build_freshness_report(clean_df, settings, settings.paths.freshness_report)
    assert report["total_rows"] == 24
    assert report["latest_published"] == "2026-07-22"
    assert report["is_fresh"] is True
    assert read_json(settings.paths.freshness_report)["stale_rows"] == report["stale_rows"]
    stale = clean_df.assign(age_days=400)
    assert build_freshness_report(stale, settings, settings.paths.freshness_report)["is_fresh"] is False


def test_corruption_log_has_six_scenarios(clean_df, settings):
    corrupted = corrupt_clean_dataframe(clean_df, settings.paths.corruption_log)
    log = read_json(settings.paths.corruption_log)
    names = [c["corruption"] for c in log["corruptions"]]
    assert names == [
        "drop_latest_records",
        "blank_summary",
        "inject_noise",
        "truncate_title",
        "stale_date",
        "duplicate_rows",
    ]
    assert log["output_rows"] == len(corrupted)
    assert not corrupted["paper_id"].is_unique
    assert (corrupted["summary"] == "").any()
    assert (corrupted["title"].str.len() < 8).any()
    dropped = set(log["corruptions"][0]["affected_paper_ids"])
    assert dropped.isdisjoint(set(corrupted["paper_id"]))
    again = corrupt_clean_dataframe(clean_df, settings.paths.corruption_log)
    pd.testing.assert_frame_equal(corrupted, again)
