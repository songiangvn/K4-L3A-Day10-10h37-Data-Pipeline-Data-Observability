from __future__ import annotations

from core.utils import read_json


def test_phase1_artifacts(e2e_project):
    paths = e2e_project.paths
    for path in (
        paths.clean_csv,
        paths.clean_json,
        paths.eval_testset,
        paths.baseline_metrics,
        paths.baseline_report,
        paths.baseline_quality_report,
        paths.freshness_report,
        paths.demo_answers,
    ):
        assert path.exists(), path
    metrics = read_json(paths.baseline_metrics)
    assert metrics["samples"] == 10
    assert metrics["retrieval_hit_rate"] == 1.0


def test_corruption_flow_degrades_then_recovers(e2e_project):
    paths = e2e_project.paths
    baseline = read_json(paths.baseline_metrics)
    corrupted = read_json(paths.corrupted_metrics)
    repaired = read_json(paths.repaired_metrics)
    assert corrupted["retrieval_hit_rate"] < baseline["retrieval_hit_rate"]
    assert corrupted["mean_token_f1"] < baseline["mean_token_f1"]
    assert repaired["retrieval_hit_rate"] == baseline["retrieval_hit_rate"]
    assert repaired["mean_token_f1"] == baseline["mean_token_f1"]
    assert read_json(paths.corrupted_quality_report)["success"] is False
    assert read_json(paths.quality_dir / "repaired_quality_report.json")["success"] is True

    summary = read_json(paths.project_dir / "data" / "results" / "repair_summary.json")
    assert summary["auto_repair_triggered"] is True
    assert summary["idempotent (run_1 == run_2)"] is True
    assert summary["repaired == baseline"] is True

    report = paths.comparison_report.read_text(encoding="utf-8")
    assert "Baseline" in report and "Corrupted" in report and "Repaired" in report
    assert len(read_json(paths.corruption_log)["corruptions"]) == 6
