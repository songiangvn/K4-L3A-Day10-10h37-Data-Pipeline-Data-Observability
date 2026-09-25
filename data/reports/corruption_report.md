# Corruption Report — Baseline vs Corrupted vs Repaired

_Generated at 2026-09-25T08:29:22.275239+00:00 by `script/run_corruption_flow.py`. All three states are evaluated on the same `data/eval/test_set.json`._

## 1. Three-state comparison

| Metric / signal | Baseline | Corrupted | Repaired | Δ corruption | Recovery |
| --- | ---: | ---: | ---: | ---: | ---: |
| `retrieval_hit_rate` | 1.0000 | 0.7000 | 1.0000 | -0.3000 | 100% |
| `mean_token_f1` | 1.0000 | 0.6800 | 1.0000 | -0.3200 | 100% |
| `judge_accuracy` | 1.0000 | 0.7000 | 1.0000 | -0.3000 | 100% |
| `mean_judge_score` | 5 | 3.6000 | 5 | -1.4000 | 100% |
| Row count | 24 | 25 | 24 | - | - |
| GX quality gate | PASS (7/7) | FAIL (4/7) | PASS (7/7) | - | - |
| Freshness is_fresh (stale ratio) | True (0.0417) | False (0.4400) | True (0.0417) | - | - |

_Recovery = (repaired − corrupted) / (baseline − corrupted)._

## 2. Quality gate per expectation

| Check | Dimension | Baseline | Corrupted | Repaired | Corrupted detail |
| --- | --- | --- | --- | --- | --- |
| `row_count_between` | Volume | PASS | PASS | PASS | 25 |
| `paper_id_not_null` | Completeness | PASS | PASS | PASS | 0 unexpected rows |
| `title_not_null` | Completeness | PASS | PASS | PASS | 0 unexpected rows |
| `text_for_embedding_not_null` | Completeness | PASS | PASS | PASS | 0 unexpected rows |
| `paper_id_unique` | Uniqueness | PASS | FAIL | PASS | 12 unexpected rows |
| `summary_min_length` | Validity | PASS | FAIL | PASS | 5 unexpected rows |
| `title_min_length` | Validity | PASS | FAIL | PASS | 7 unexpected rows |

## 3. Injected corruptions

Seed `42`; rows 24 → 25. Full list of affected `paper_id`s in `data/results/corruption_log.json`.

| # | Corruption | Description | Affected rows | Detected by |
| ---: | --- | --- | ---: | --- |
| 1 | `drop_latest_records` | Dropped the newest 20% of papers by published date. | 5 | Not caught by GX (row count still in range) → visible as `latest_published` moving back + hit-rate drop |
| 2 | `blank_summary` | Replaced the abstract with an empty string. | 4 | `summary_min_length` |
| 3 | `inject_noise` | Wrapped the abstract with garbage tokens. | 3 | Not caught by GX (length still valid) → only visible in token F1 |
| 4 | `truncate_title` | Cut titles to 7 characters (< 8). | 5 | `title_min_length` |
| 5 | `stale_date` | Moved the published date back 365 days. | 8 | Freshness SLA (`is_fresh=False`) |
| 6 | `duplicate_rows` | Appended exact copies of existing rows. | 6 | `paper_id_unique` |

## 4. Per-question impact

| id | type | Corruptions on target doc | Hit B/C/R | F1 B/C/R | Corrupted answer |
| --- | --- | --- | --- | --- | --- |
| eval_001 | summary | drop_latest_records | ✓/✗/✓ | 1.00/0.00/1.00 |  |
| eval_002 | authors | drop_latest_records | ✓/✗/✓ | 1.00/1.00/1.00 | Bao Do, Linh Ngo |
| eval_003 | date | drop_latest_records | ✓/✗/✓ | 1.00/0.00/1.00 | 2026-06-02 |
| eval_004 | categories | truncate_title, stale_date | ✓/✓/✓ | 1.00/1.00/1.00 | Data Quality, DevOps |
| eval_005 | summary | inject_noise | ✓/✓/✓ | 1.00/0.80/1.00 | #@!$%^ lorem ipsum ##ERR## 0xDEADBEEF Embedding quality checks directl |
| eval_006 | authors | blank_summary, stale_date, duplicate_rows | ✓/✓/✓ | 1.00/1.00/1.00 | Huy Dinh, Trang Vo |
| eval_007 | date | stale_date, duplicate_rows | ✓/✓/✓ | 1.00/0.00/1.00 | 2025-06-04 |
| eval_008 | categories | none | ✓/✓/✓ | 1.00/1.00/1.00 | Software Engineering, Data Systems |
| eval_009 | summary | stale_date | ✓/✓/✓ | 1.00/1.00/1.00 | Dense vector search excels at conceptual similarity but struggles with |
| eval_010 | authors | none | ✓/✓/✓ | 1.00/1.00/1.00 | Long Trinh, Ha Chu |

## 5. Analysis

1. **Silent failure.** On corrupted data the agent still answered every question without raising an error, but retrieval hit rate went 1.0000 → 0.7000 and token F1 1.0000 → 0.6800. Nothing in the answer path signals the problem; only the data-quality layer does.
2. **Quality gate as early warning.** GX flagged the corrupted batch (`success=False`, failed: paper_id_unique, summary_min_length, title_min_length) and the freshness SLA reported `is_fresh=False` (stale ratio 0.4400). In production this gate blocks the index swap.
3. **Root causes of the drop.** See the attribution table below (computed from section 4): a corruption only hurts a question when it touches that question's ground-truth document *and* the field the question asks about.
4. **Blind spot.** `inject_noise` keeps summaries long enough to pass `summary_min_length`, so it is only visible through answer metrics — a content-level check (e.g. character-class ratio) would be needed to catch it.
5. **Repair.** Rebuilding from the immutable raw snapshot restored hit rate to 1.0000 and token F1 to 1.0000, with the quality gate back to `success=True` and `is_fresh=True`.

### Impact attribution per corruption

| Corruption | Test questions whose target doc is affected | Lost retrieval hit | Lower token F1 |
| --- | --- | --- | --- |
| `drop_latest_records` | eval_001 (summary), eval_002 (authors), eval_003 (date) | eval_001, eval_002, eval_003 | eval_001, eval_003 |
| `blank_summary` | eval_006 (authors) | none | none |
| `inject_noise` | eval_005 (summary) | none | eval_005 |
| `truncate_title` | eval_004 (categories) | none | none |
| `stale_date` | eval_004 (categories), eval_006 (authors), eval_007 (date), eval_009 (summary) | none | eval_007 |
| `duplicate_rows` | eval_006 (authors), eval_007 (date) | none | eval_007 |

_A question can appear under several corruptions when they overlap on the same document; questions whose field was not touched (e.g. an `authors` question on a blanked-summary doc) keep F1 = 1.0._

## 6. Idempotent repair evidence

| Field | Value |
| --- | --- |
| initial_gate_success | False |
| initial_is_fresh | False |
| initial_failed_checks | ['paper_id_unique', 'summary_min_length', 'title_min_length'] |
| auto_repair_triggered | True |
| repair_source | data/raw/crossref_records.json |
| repaired_gate_success | True |
| repaired_is_fresh | True |
| repair_run_date | 2026-09-25 |
| repaired_rows | 24 |
| baseline_sha256 | f0be02afc5d4360f |
| repaired_run_1_sha256 | f0be02afc5d4360f |
| repaired_run_2_sha256 | f0be02afc5d4360f |
| corrupted_sha256 | 0625190a6dec882e |
| idempotent (run_1 == run_2) | True |
| repaired == baseline | True |
