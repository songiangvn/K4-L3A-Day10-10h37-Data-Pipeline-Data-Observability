# Phase 1 Report — Baseline Data Pipeline

_Generated at 2026-09-25T08:37:38.465671+00:00 by `script/run_phase1.py`._

## 1. Source & lineage

| Field | Value |
| --- | --- |
| source_api | Crossref REST API |
| query | agentic retrieval augmented generation large language model |
| filter | from-pub-date:2026-03-29,has-abstract:true |
| mode | snapshot |
| raw_response | data/raw/crossref_response.json |
| raw_records | data/raw/crossref_records.json |
| raw_record_count | 24 |
| clean_row_count | 24 |
| run_date | 2026-09-25 |
| embedding_model | sentence-transformers/all-MiniLM-L6-v2 |
| collection | papers-baseline |
| indexed_documents | 24 |
| top_k | 4 |
| llm_provider | openai |

## 2. Baseline RAG evaluation

| Metric | Value |
| --- | ---: |
| samples | 10 |
| judge_mode | llm:openai/gpt-4o-mini |
| retrieval_hit_rate | 1.0000 |
| mean_token_f1 | 1.0000 |
| judge_accuracy | 1.0000 |
| mean_judge_score | 5 |
| ragas | skipped=Set RUN_RAGAS=1 to enable the slower Ragas pass. |

### By question type

| question_type | n | hit_rate | mean_token_f1 |
| --- | ---: | ---: | ---: |
| summary | 3 | 1.0000 | 1.0000 |
| authors | 3 | 1.0000 | 1.0000 |
| date | 2 | 1.0000 | 1.0000 |
| categories | 2 | 1.0000 | 1.0000 |

## 3. Data quality gate (Great Expectations 1.x)

- Engine: `great_expectations 1.23.1` — ephemeral context, pandas datasource, whole-dataframe batch.
- Rows validated: **24**
- Overall: **PASS** (7/7 expectations passed)

| Check | Dimension | Expectation (GX 1.x) | Column | Result | Observed / unexpected |
| --- | --- | --- | --- | --- | --- |
| `row_count_between` | Volume | `expect_table_row_count_to_be_between` | - | PASS | 24 |
| `paper_id_not_null` | Completeness | `expect_column_values_to_not_be_null` | paper_id | PASS | 0 unexpected (0.0000%) |
| `title_not_null` | Completeness | `expect_column_values_to_not_be_null` | title | PASS | 0 unexpected (0.0000%) |
| `text_for_embedding_not_null` | Completeness | `expect_column_values_to_not_be_null` | text_for_embedding | PASS | 0 unexpected (0.0000%) |
| `paper_id_unique` | Uniqueness | `expect_column_values_to_be_unique` | paper_id | PASS | 0 unexpected (0.0000%) |
| `summary_min_length` | Validity | `expect_column_value_lengths_to_be_between` | summary | PASS | 0 unexpected (0.0000%) |
| `title_min_length` | Validity | `expect_column_value_lengths_to_be_between` | title | PASS | 0 unexpected (0.0000%) |

## 4. Freshness SLA

Stale = `age_days > threshold_days`; the dataset is fresh when the stale ratio is at most 25%.

| Field | Value |
| --- | --- |
| latest_published | 2026-07-22 |
| oldest_published | 2026-03-28 |
| threshold_days | 180 |
| stale_rows / total_rows | 1 / 24 |
| stale_ratio (max 0.25) | 0.0417 |
| is_fresh | True |

## 5. Interpretation

- The quality gate passed; the clean data is safe to serve.
- Freshness is within SLA (1/24 rows older than 180 days).
- Baseline retrieval hit rate 1.0000 and token F1 1.0000 are the reference values for the corruption experiment.
