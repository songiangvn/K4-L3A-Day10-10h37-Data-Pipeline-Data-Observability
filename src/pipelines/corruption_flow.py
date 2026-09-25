from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import logging
from typing import Any

import pandas as pd

from core.config import Settings, load_settings
from core.utils import now_utc, read_json, write_json
from evaluation.metrics import evaluate_pipeline
from ingestion.cleaning import build_clean_dataframe
from ingestion.corruption import corrupt_clean_dataframe
from ingestion.crossref import load_raw_records
from observability.dashboard import build_dashboard
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import METRIC_KEYS, generate_corruption_report
from pipelines.phase1 import configure_logging, load_clean_json, save_clean_artifacts
from retrieval.index import LocalEmbeddingIndex

logger = logging.getLogger(__name__)


def dataframe_fingerprint(df: pd.DataFrame) -> str:
    """Order-independent content hash of a clean dataframe (used to prove idempotency)."""
    columns = ["paper_id", "title", "summary", "published", "authors_joined", "categories_joined", "text_for_embedding"]
    canonical = df[columns].astype(str).sort_values("paper_id").to_csv(index=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def baseline_run_date(settings: Settings) -> datetime:
    """Reuse the baseline run date so the repaired `age_days` match the baseline exactly."""
    run_file = settings.paths.project_dir / "data" / "results" / "phase1_run.json"
    if run_file.exists():
        value = read_json(run_file).get("run_date")
        if value:
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    return now_utc()


def repair_from_raw(settings: Settings, run_date: datetime) -> pd.DataFrame:
    """Idempotent repair: rebuild the clean dataset from the immutable raw snapshot.

    Never patches the corrupted frame; it recomputes everything from `data/raw/crossref_records.json`,
    so running it N times always yields the same output.
    """
    records = load_raw_records(settings.paths.raw_records_json)
    return build_clean_dataframe(records, run_date)


def self_healing_gate(
    df: pd.DataFrame, quality: dict[str, Any], settings: Settings, run_date: datetime
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    """Auto-repair loop (bonus B2): validate; if the gate or freshness SLA fails, rebuild from raw and re-validate.

    Returns (data safe to serve, actions log, final quality report).
    """
    actions: dict[str, Any] = {
        "initial_gate_success": quality["success"],
        "initial_is_fresh": quality["freshness"]["is_fresh"],
        "initial_failed_checks": quality["failed_checks"],
        "auto_repair_triggered": False,
    }
    if quality["success"] and quality["freshness"]["is_fresh"]:
        return df, actions, quality

    logger.warning("Quality gate failed %s -> triggering automatic repair from raw", quality["failed_checks"])
    actions["auto_repair_triggered"] = True
    repaired = repair_from_raw(settings, run_date)
    repaired_quality = run_data_quality_checks(repaired, settings, "repaired")
    actions["repair_source"] = settings.paths.raw_records_json.relative_to(settings.paths.project_dir).as_posix()
    actions["repaired_gate_success"] = repaired_quality["success"]
    actions["repaired_is_fresh"] = repaired_quality["freshness"]["is_fresh"]
    if not repaired_quality["success"]:
        raise RuntimeError(f"Repair from raw still fails the quality gate: {repaired_quality['failed_checks']}")
    return repaired, actions, repaired_quality


def _print_comparison(baseline: dict, corrupted: dict, repaired: dict, qualities: list[dict], freshness: list[dict]) -> None:
    header = f"{'metric':<22}{'baseline':>12}{'corrupted':>12}{'repaired':>12}"
    print("\n=== Baseline vs Corrupted vs Repaired ===")
    print(header)
    print("-" * len(header))
    for key in METRIC_KEYS:
        print(f"{key:<22}{baseline[key]:>12.4f}{corrupted[key]:>12.4f}{repaired[key]:>12.4f}")
    print(f"{'quality_gate':<22}" + "".join(f"{str(q['success']):>12}" for q in qualities))
    print(f"{'is_fresh':<22}" + "".join(f"{str(f['is_fresh']):>12}" for f in freshness))


def main() -> None:
    configure_logging()
    settings = load_settings()
    paths = settings.paths
    if not paths.baseline_metrics.exists() or not paths.clean_json.exists():
        raise FileNotFoundError("Baseline artifacts missing. Run `python script/run_phase1.py` first.")

    # 1. Baseline state.
    baseline_metrics = read_json(paths.baseline_metrics)
    baseline_answers = read_json(paths.baseline_answers)
    clean_df = load_clean_json(paths.clean_json)
    baseline_quality = run_data_quality_checks(clean_df, settings, "baseline")
    baseline_freshness = read_json(paths.freshness_report) if paths.freshness_report.exists() else baseline_quality["freshness"]
    run_date = baseline_run_date(settings)

    # 2-3. Corrupt + save artifacts.
    corrupted_df = corrupt_clean_dataframe(clean_df, paths.corruption_log)
    save_clean_artifacts(corrupted_df, paths.corrupted_clean_csv, paths.corrupted_clean_json)

    # 4. Observe corrupted data (quality gate + freshness) — we deliberately index it anyway
    #    to measure the silent failure the gate would have prevented.
    corrupted_quality = run_data_quality_checks(corrupted_df, settings, "corrupted")
    corrupted_freshness = build_freshness_report(
        corrupted_df, settings, paths.quality_dir / "corrupted_freshness_report.json"
    )
    corrupted_index = LocalEmbeddingIndex.build(corrupted_df, settings, paths.corrupted_embeddings_json)
    corrupted_bundle = evaluate_pipeline(
        settings, corrupted_index, paths.eval_testset, paths.corrupted_metrics, paths.corrupted_answers
    )

    # 5-6. Self-healing gate: failure detected -> automatic repair from raw snapshot.
    repaired_df, heal_actions, repaired_quality = self_healing_gate(corrupted_df, corrupted_quality, settings, run_date)
    second_pass = repair_from_raw(settings, run_date)
    save_clean_artifacts(repaired_df, paths.repaired_clean_csv, paths.repaired_clean_json)
    repaired_freshness = build_freshness_report(
        repaired_df, settings, paths.quality_dir / "repaired_freshness_report.json"
    )

    # 7. Evaluate repaired data in its own collection.
    repaired_index = LocalEmbeddingIndex.build(repaired_df, settings, paths.repaired_embeddings_json)
    repaired_bundle = evaluate_pipeline(
        settings, repaired_index, paths.eval_testset, paths.repaired_metrics, paths.repaired_answers
    )

    fingerprints = {
        "baseline": dataframe_fingerprint(clean_df),
        "repaired_run_1": dataframe_fingerprint(repaired_df),
        "repaired_run_2": dataframe_fingerprint(second_pass),
        "corrupted": dataframe_fingerprint(corrupted_df.drop_duplicates(subset="paper_id")),
    }
    repair_summary = {
        **heal_actions,
        "repair_run_date": run_date.date().isoformat(),
        "repaired_rows": len(repaired_df),
        "baseline_sha256": fingerprints["baseline"][:16],
        "repaired_run_1_sha256": fingerprints["repaired_run_1"][:16],
        "repaired_run_2_sha256": fingerprints["repaired_run_2"][:16],
        "corrupted_sha256": fingerprints["corrupted"][:16],
        "idempotent (run_1 == run_2)": fingerprints["repaired_run_1"] == fingerprints["repaired_run_2"],
        "repaired == baseline": fingerprints["repaired_run_1"] == fingerprints["baseline"],
    }
    write_json(paths.project_dir / "data" / "results" / "repair_summary.json", repair_summary)

    # 8. Comparison report.
    generate_corruption_report(
        paths.comparison_report,
        baseline_metrics,
        corrupted_bundle.summary,
        repaired_bundle.summary,
        corrupted_quality,
        repaired_quality,
        corrupted_freshness,
        repaired_freshness,
        baseline_quality=baseline_quality,
        baseline_freshness=baseline_freshness,
        corruption_log=read_json(paths.corruption_log),
        answers={
            "baseline": baseline_answers,
            "corrupted": corrupted_bundle.answers,
            "repaired": repaired_bundle.answers,
        },
        repair_summary=repair_summary,
    )

    _print_comparison(
        baseline_metrics,
        corrupted_bundle.summary,
        repaired_bundle.summary,
        [baseline_quality, corrupted_quality, repaired_quality],
        [baseline_freshness, corrupted_freshness, repaired_freshness],
    )
    print(f"auto_repair_triggered: {heal_actions['auto_repair_triggered']}")
    print(f"idempotent repair: {repair_summary['idempotent (run_1 == run_2)']}, "
          f"repaired == baseline: {repair_summary['repaired == baseline']}")
    print(f"Report: {paths.comparison_report.relative_to(paths.project_dir).as_posix()}")
    print(f"Dashboard: {build_dashboard(settings).relative_to(paths.project_dir).as_posix()}")


if __name__ == "__main__":
    main()
