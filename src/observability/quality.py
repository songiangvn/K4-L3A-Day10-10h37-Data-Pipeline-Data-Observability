from __future__ import annotations

from typing import Any
import logging

import great_expectations as gx
import great_expectations.expectations as gxe
import pandas as pd

from core.config import Settings
from core.utils import now_utc, write_json

logger = logging.getLogger(__name__)

MIN_ROWS = 5
MAX_ROWS = 5000
MIN_SUMMARY_CHARS = 30
MIN_TITLE_CHARS = 8
MAX_STALE_RATIO = 0.25


def _build_expectations() -> list[tuple[str, str, Any]]:
    """(check name, quality dimension, GX 1.x expectation)."""
    return [
        ("row_count_between", "Volume", gxe.ExpectTableRowCountToBeBetween(min_value=MIN_ROWS, max_value=MAX_ROWS)),
        ("paper_id_not_null", "Completeness", gxe.ExpectColumnValuesToNotBeNull(column="paper_id")),
        ("title_not_null", "Completeness", gxe.ExpectColumnValuesToNotBeNull(column="title")),
        (
            "text_for_embedding_not_null",
            "Completeness",
            gxe.ExpectColumnValuesToNotBeNull(column="text_for_embedding"),
        ),
        ("paper_id_unique", "Uniqueness", gxe.ExpectColumnValuesToBeUnique(column="paper_id")),
        (
            "summary_min_length",
            "Validity",
            gxe.ExpectColumnValueLengthsToBeBetween(column="summary", min_value=MIN_SUMMARY_CHARS),
        ),
        (
            "title_min_length",
            "Validity",
            gxe.ExpectColumnValueLengthsToBeBetween(column="title", min_value=MIN_TITLE_CHARS),
        ),
    ]


def _gx_frame(df: pd.DataFrame) -> pd.DataFrame:
    """GX only needs scalar columns; list columns (authors/categories) are serialised to strings."""
    frame = df.copy()
    for column in frame.columns:
        if frame[column].map(lambda value: isinstance(value, (list, tuple))).any():
            frame[column] = frame[column].map(lambda value: ", ".join(value) if isinstance(value, (list, tuple)) else value)
    for column in ("summary", "title", "text_for_embedding"):
        if column in frame.columns:
            frame[column] = frame[column].fillna("").astype(str)
    return frame


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def run_data_quality_checks(df: pd.DataFrame, settings: Settings, report_name: str) -> dict[str, Any]:
    """Run the Great Expectations 1.x quality gate and write `data/quality/<report_name>_quality_report.json`.

    `success` is True only when every expectation passes. Freshness is measured alongside
    (`freshness` key) but kept as a separate SLA signal.
    """
    context = gx.get_context(mode="ephemeral")
    data_source = context.data_sources.add_pandas(name="papers_source")
    data_asset = data_source.add_dataframe_asset(name="papers_asset")
    batch_def = data_asset.add_batch_definition_whole_dataframe("papers_batch")
    batch = batch_def.get_batch(batch_parameters={"dataframe": _gx_frame(df)})

    suite = context.suites.add(gx.ExpectationSuite(name=f"papers_{report_name}_suite"))
    checks = _build_expectations()
    for _, _, expectation in checks:
        suite.add_expectation(expectation)

    validation = batch.validate(suite, result_format="SUMMARY")
    by_type_and_column: dict[tuple[str, str | None], Any] = {}
    for result in validation.results:
        config = result.expectation_config
        by_type_and_column[(config.type, config.kwargs.get("column"))] = result

    expectations = []
    for name, dimension, expectation in checks:
        result = by_type_and_column[(expectation.expectation_type, getattr(expectation, "column", None))]
        details = result.result or {}
        expectations.append(
            {
                "check": name,
                "dimension": dimension,
                "expectation_type": expectation.expectation_type,
                "column": getattr(expectation, "column", None),
                "success": bool(result.success),
                "observed_value": _json_safe(details.get("observed_value")),
                "unexpected_count": _json_safe(details.get("unexpected_count")),
                "unexpected_percent": _json_safe(details.get("unexpected_percent")),
                "partial_unexpected_list": _json_safe(details.get("partial_unexpected_list", [])[:5]),
            }
        )

    freshness = compute_freshness(df, settings)
    failed = [item["check"] for item in expectations if not item["success"]]
    report = {
        "report_name": report_name,
        "engine": f"great_expectations {gx.__version__}",
        "generated_at": now_utc().isoformat(),
        "row_count": int(len(df)),
        "success": bool(validation.success),
        "evaluated_expectations": len(expectations),
        "successful_expectations": len(expectations) - len(failed),
        "failed_checks": failed,
        "expectations": expectations,
        "freshness": freshness,
    }
    write_json(settings.paths.quality_dir / f"{report_name}_quality_report.json", report)
    logger.info("Quality gate [%s]: success=%s failed=%s", report_name, report["success"], failed)
    return report


def compute_freshness(df: pd.DataFrame, settings: Settings) -> dict[str, Any]:
    published = pd.to_datetime(df["published"], errors="coerce") if "published" in df else pd.Series(dtype="datetime64[ns]")
    ages = pd.to_numeric(df["age_days"], errors="coerce") if "age_days" in df else pd.Series(dtype=float)
    total = int(len(df))
    stale_rows = int((ages > settings.freshness_threshold_days).sum())
    stale_ratio = (stale_rows / total) if total else 1.0
    return {
        "latest_published": published.max().strftime("%Y-%m-%d") if published.notna().any() else None,
        "oldest_published": published.min().strftime("%Y-%m-%d") if published.notna().any() else None,
        "min_age_days": int(ages.min()) if ages.notna().any() else None,
        "max_age_days": int(ages.max()) if ages.notna().any() else None,
        "threshold_days": settings.freshness_threshold_days,
        "stale_rows": stale_rows,
        "total_rows": total,
        "stale_ratio": round(stale_ratio, 4),
        "max_stale_ratio": MAX_STALE_RATIO,
        "is_fresh": bool(total > 0 and stale_ratio <= MAX_STALE_RATIO),
    }


def build_freshness_report(df: pd.DataFrame, settings: Settings, report_path) -> dict[str, Any]:
    """Freshness SLA: stale = `age_days > 180`; dataset is fresh when stale ratio <= 25%."""
    payload = {"generated_at": now_utc().isoformat(), **compute_freshness(df, settings)}
    write_json(report_path, payload)
    return payload
