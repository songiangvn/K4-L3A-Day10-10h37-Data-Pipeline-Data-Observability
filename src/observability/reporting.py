from __future__ import annotations

from typing import Any

from core.utils import now_utc, write_text

METRIC_KEYS = ["retrieval_hit_rate", "mean_token_f1", "judge_accuracy", "mean_judge_score"]


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    if isinstance(value, float):
        return f"{value:.4f}"
    return "-" if value is None else str(value)


def _quality_table(quality: dict[str, Any]) -> list[str]:
    lines = [
        "| Check | Dimension | Expectation (GX 1.x) | Column | Result | Observed / unexpected |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in quality.get("expectations", []):
        observed = item.get("observed_value")
        if observed is None:
            observed = f"{item.get('unexpected_count', 0)} unexpected ({_fmt(item.get('unexpected_percent'))}%)"
        lines.append(
            f"| `{item['check']}` | {item['dimension']} | `{item['expectation_type']}` | {item.get('column') or '-'} "
            f"| {_fmt(item['success'])} | {observed} |"
        )
    return lines


def _freshness_lines(freshness: dict[str, Any]) -> list[str]:
    return [
        "| Field | Value |",
        "| --- | --- |",
        f"| latest_published | {freshness.get('latest_published')} |",
        f"| oldest_published | {freshness.get('oldest_published')} |",
        f"| threshold_days | {freshness.get('threshold_days')} |",
        f"| stale_rows / total_rows | {freshness.get('stale_rows')} / {freshness.get('total_rows')} |",
        f"| stale_ratio (max {freshness.get('max_stale_ratio')}) | {_fmt(freshness.get('stale_ratio'))} |",
        f"| is_fresh | {freshness.get('is_fresh')} |",
    ]


def generate_phase1_report(
    report_path,
    source_summary: dict[str, Any],
    metrics: dict[str, Any],
    quality: dict[str, Any],
    freshness: dict[str, Any],
) -> None:
    """Write the baseline (phase 1) Markdown report."""
    lines = [
        "# Phase 1 Report — Baseline Data Pipeline",
        "",
        f"_Generated at {now_utc().isoformat()} by `script/run_phase1.py`._",
        "",
        "## 1. Source & lineage",
        "",
        "| Field | Value |",
        "| --- | --- |",
    ]
    for key, value in source_summary.items():
        lines.append(f"| {key} | {value} |")

    lines += [
        "",
        "## 2. Baseline RAG evaluation",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| samples | {metrics.get('samples')} |",
        f"| judge_mode | {metrics.get('judge_mode', '-')} |",
    ]
    for key in METRIC_KEYS:
        lines.append(f"| {key} | {_fmt(metrics.get(key))} |")
    ragas = metrics.get("ragas")
    if isinstance(ragas, dict):
        lines.append(f"| ragas | {', '.join(f'{k}={_fmt(v)}' for k, v in ragas.items())} |")

    by_type = metrics.get("by_question_type") or {}
    if by_type:
        lines += ["", "### By question type", "", "| question_type | n | hit_rate | mean_token_f1 |", "| --- | ---: | ---: | ---: |"]
        for qtype, stats in by_type.items():
            lines.append(f"| {qtype} | {stats['n']} | {_fmt(stats['hit_rate'])} | {_fmt(stats['mean_token_f1'])} |")

    lines += [
        "",
        "## 3. Data quality gate (Great Expectations 1.x)",
        "",
        f"- Engine: `{quality.get('engine')}` — ephemeral context, pandas datasource, whole-dataframe batch.",
        f"- Rows validated: **{quality.get('row_count')}**",
        f"- Overall: **{_fmt(quality.get('success'))}** "
        f"({quality.get('successful_expectations')}/{quality.get('evaluated_expectations')} expectations passed)",
        "",
        *_quality_table(quality),
        "",
        "## 4. Freshness SLA",
        "",
        "Stale = `age_days > threshold_days`; the dataset is fresh when the stale ratio is at most 25%.",
        "",
        *_freshness_lines(freshness),
        "",
        "## 5. Interpretation",
        "",
        f"- The quality gate {'passed' if quality.get('success') else 'FAILED'}; "
        f"{'the clean data is safe to serve.' if quality.get('success') else 'failed checks: ' + ', '.join(quality.get('failed_checks', []))}",
        f"- Freshness is {'within' if freshness.get('is_fresh') else 'OUTSIDE'} SLA "
        f"({freshness.get('stale_rows')}/{freshness.get('total_rows')} rows older than {freshness.get('threshold_days')} days).",
        f"- Baseline retrieval hit rate {_fmt(metrics.get('retrieval_hit_rate'))} and token F1 "
        f"{_fmt(metrics.get('mean_token_f1'))} are the reference values for the corruption experiment.",
        "",
    ]
    write_text(report_path, "\n".join(lines))


def _delta(a: Any, b: Any) -> str:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return f"{b - a:+.4f}"
    return "-"


def _recovery(baseline: Any, corrupted: Any, repaired: Any) -> str:
    numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (baseline, corrupted, repaired))
    if not numeric:
        return "-"
    lost = baseline - corrupted
    if abs(lost) < 1e-12:
        return "n/a (no drop)"
    return f"{(repaired - corrupted) / lost:.0%}"


def generate_corruption_report(
    report_path,
    baseline_metrics: dict[str, Any],
    corrupted_metrics: dict[str, Any],
    repaired_metrics: dict[str, Any],
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
    corrupted_freshness: dict[str, Any],
    repaired_freshness: dict[str, Any],
    baseline_quality: dict[str, Any] | None = None,
    baseline_freshness: dict[str, Any] | None = None,
    corruption_log: dict[str, Any] | None = None,
    answers: dict[str, list[dict[str, Any]]] | None = None,
    repair_summary: dict[str, Any] | None = None,
) -> None:
    """Write the Baseline vs Corrupted vs Repaired comparison report."""
    baseline_quality = baseline_quality or {}
    baseline_freshness = baseline_freshness or {}
    lines = [
        "# Corruption Report — Baseline vs Corrupted vs Repaired",
        "",
        f"_Generated at {now_utc().isoformat()} by `script/run_corruption_flow.py`. "
        "All three states are evaluated on the same `data/eval/test_set.json`._",
        "",
        "## 1. Three-state comparison",
        "",
        "| Metric / signal | Baseline | Corrupted | Repaired | Δ corruption | Recovery |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key in METRIC_KEYS:
        b, c, r = baseline_metrics.get(key), corrupted_metrics.get(key), repaired_metrics.get(key)
        lines.append(f"| `{key}` | {_fmt(b)} | {_fmt(c)} | {_fmt(r)} | {_delta(b, c)} | {_recovery(b, c, r)} |")

    def passed(q: dict[str, Any]) -> str:
        if not q:
            return "-"
        return f"{_fmt(q.get('success'))} ({q.get('successful_expectations')}/{q.get('evaluated_expectations')})"

    lines += [
        f"| Row count | {baseline_quality.get('row_count', '-')} | {corrupted_quality.get('row_count')} "
        f"| {repaired_quality.get('row_count')} | - | - |",
        f"| GX quality gate | {passed(baseline_quality)} | {passed(corrupted_quality)} | {passed(repaired_quality)} | - | - |",
        f"| Freshness is_fresh (stale ratio) | {baseline_freshness.get('is_fresh', '-')} ({_fmt(baseline_freshness.get('stale_ratio'))}) "
        f"| {corrupted_freshness.get('is_fresh')} ({_fmt(corrupted_freshness.get('stale_ratio'))}) "
        f"| {repaired_freshness.get('is_fresh')} ({_fmt(repaired_freshness.get('stale_ratio'))}) | - | - |",
        "",
        "_Recovery = (repaired − corrupted) / (baseline − corrupted)._",
        "",
        "## 2. Quality gate per expectation",
        "",
        "| Check | Dimension | Baseline | Corrupted | Repaired | Corrupted detail |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    base_by = {e["check"]: e for e in baseline_quality.get("expectations", [])}
    rep_by = {e["check"]: e for e in repaired_quality.get("expectations", [])}
    for item in corrupted_quality.get("expectations", []):
        detail = item.get("observed_value")
        if detail is None:
            detail = f"{item.get('unexpected_count', 0)} unexpected rows"
        lines.append(
            f"| `{item['check']}` | {item['dimension']} | {_fmt(base_by.get(item['check'], {}).get('success'))} "
            f"| {_fmt(item['success'])} | {_fmt(rep_by.get(item['check'], {}).get('success'))} | {detail} |"
        )

    if corruption_log:
        lines += [
            "",
            "## 3. Injected corruptions",
            "",
            f"Seed `{corruption_log.get('seed')}`; rows {corruption_log.get('input_rows')} → {corruption_log.get('output_rows')}. "
            "Full list of affected `paper_id`s in `data/results/corruption_log.json`.",
            "",
            "| # | Corruption | Description | Affected rows | Detected by |",
            "| ---: | --- | --- | ---: | --- |",
        ]
        detectors = {
            "drop_latest_records": "Not caught by GX (row count still in range) → visible as `latest_published` moving back + hit-rate drop",
            "blank_summary": "`summary_min_length`",
            "inject_noise": "Not caught by GX (length still valid) → only visible in token F1",
            "truncate_title": "`title_min_length`",
            "stale_date": "Freshness SLA (`is_fresh=False`)",
            "duplicate_rows": "`paper_id_unique`",
        }
        for number, item in enumerate(corruption_log.get("corruptions", []), start=1):
            lines.append(
                f"| {number} | `{item['corruption']}` | {item['description']} | {item['affected_rows']} "
                f"| {detectors.get(item['corruption'], '-')} |"
            )

    if answers and corruption_log:
        affected: dict[str, list[str]] = {}
        for item in corruption_log.get("corruptions", []):
            for pid in item["affected_paper_ids"]:
                affected.setdefault(pid, [])
                if item["corruption"] not in affected[pid]:
                    affected[pid].append(item["corruption"])
        lines += [
            "",
            "## 4. Per-question impact",
            "",
            "| id | type | Corruptions on target doc | Hit B/C/R | F1 B/C/R | Corrupted answer |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        base_answers = {a["id"]: a for a in answers.get("baseline", [])}
        rep_answers = {a["id"]: a for a in answers.get("repaired", [])}
        for ans in answers.get("corrupted", []):
            b = base_answers.get(ans["id"], {})
            r = rep_answers.get(ans["id"], {})
            target = ans["ground_truth_doc_ids"][0]
            hits = "/".join("✓" if x.get("retrieval_hit") else "✗" for x in (b, ans, r))
            f1s = "/".join(f"{x.get('token_f1', 0):.2f}" for x in (b, ans, r))
            short = str(ans["answer"]).replace("|", "\\|")[:70]
            lines.append(
                f"| {ans['id']} | {ans['question_type']} | {', '.join(affected.get(target, [])) or 'none'} "
                f"| {hits} | {f1s} | {short} |"
            )

    lines += ["", "## 5. Analysis", ""]
    b_hit, c_hit, r_hit = (m.get("retrieval_hit_rate") for m in (baseline_metrics, corrupted_metrics, repaired_metrics))
    b_f1, c_f1, r_f1 = (m.get("mean_token_f1") for m in (baseline_metrics, corrupted_metrics, repaired_metrics))
    lines += [
        f"1. **Silent failure.** On corrupted data the agent still answered every question without raising an error, "
        f"but retrieval hit rate went {_fmt(b_hit)} → {_fmt(c_hit)} and token F1 {_fmt(b_f1)} → {_fmt(c_f1)}. "
        "Nothing in the answer path signals the problem; only the data-quality layer does.",
        f"2. **Quality gate as early warning.** GX flagged the corrupted batch "
        f"(`success={corrupted_quality.get('success')}`, failed: {', '.join(corrupted_quality.get('failed_checks', [])) or 'none'}) "
        f"and the freshness SLA reported `is_fresh={corrupted_freshness.get('is_fresh')}` "
        f"(stale ratio {_fmt(corrupted_freshness.get('stale_ratio'))}). In production this gate blocks the index swap.",
        "3. **Root causes of the drop.** See the attribution table below (computed from section 4): a corruption only "
        "hurts a question when it touches that question's ground-truth document *and* the field the question asks about.",
        "4. **Blind spot.** `inject_noise` keeps summaries long enough to pass `summary_min_length`, so it is only visible "
        "through answer metrics — a content-level check (e.g. character-class ratio) would be needed to catch it.",
        f"5. **Repair.** Rebuilding from the immutable raw snapshot restored hit rate to {_fmt(r_hit)} and token F1 to "
        f"{_fmt(r_f1)}, with the quality gate back to `success={repaired_quality.get('success')}` and "
        f"`is_fresh={repaired_freshness.get('is_fresh')}`.",
    ]
    if answers and corruption_log:
        lines += [
            "",
            "### Impact attribution per corruption",
            "",
            "| Corruption | Test questions whose target doc is affected | Lost retrieval hit | Lower token F1 |",
            "| --- | --- | --- | --- |",
        ]
        base_answers = {a["id"]: a for a in answers.get("baseline", [])}
        for item in corruption_log.get("corruptions", []):
            ids = set(item["affected_paper_ids"])
            hit_q = [a for a in answers.get("corrupted", []) if a["ground_truth_doc_ids"][0] in ids]
            lost_hit = [a["id"] for a in hit_q if base_answers.get(a["id"], {}).get("retrieval_hit") and not a["retrieval_hit"]]
            lost_f1 = [
                a["id"] for a in hit_q if a["token_f1"] < base_answers.get(a["id"], {}).get("token_f1", 0) - 1e-9
            ]
            lines.append(
                f"| `{item['corruption']}` | {', '.join(a['id'] + ' (' + a['question_type'] + ')' for a in hit_q) or 'none'} "
                f"| {', '.join(lost_hit) or 'none'} | {', '.join(lost_f1) or 'none'} |"
            )
        lines += [
            "",
            "_A question can appear under several corruptions when they overlap on the same document; "
            "questions whose field was not touched (e.g. an `authors` question on a blanked-summary doc) keep F1 = 1.0._",
        ]
    if repair_summary:
        lines += [
            "",
            "## 6. Idempotent repair evidence",
            "",
            "| Field | Value |",
            "| --- | --- |",
        ]
        for key, value in repair_summary.items():
            lines.append(f"| {key} | {value} |")
    lines.append("")
    write_text(report_path, "\n".join(lines))
