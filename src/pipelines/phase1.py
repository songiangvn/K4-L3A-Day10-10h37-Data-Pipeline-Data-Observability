from __future__ import annotations

from datetime import datetime
import logging
import re
from typing import Any

import pandas as pd

from core.config import Settings, load_settings
from core.utils import now_utc, read_json, write_csv, write_json
from evaluation.metrics import evaluate_pipeline
from evaluation.testset import build_test_set
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import LAST_FETCH_INFO, fetch_source_records
from observability.dashboard import build_dashboard
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_phase1_report
from retrieval.index import LocalEmbeddingIndex

logger = logging.getLogger(__name__)

DEMO_QUESTIONS = [
    "Which papers discuss data quality gates for RAG systems?",
    "What does the corpus say about freshness SLAs for LLM knowledge?",
]


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "chromadb", "sentence_transformers", "great_expectations", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def save_clean_artifacts(df: pd.DataFrame, csv_path, json_path) -> None:
    write_csv(df, csv_path)
    records = df.astype(object).where(df.notna(), None).to_dict(orient="records")
    write_json(json_path, records)


def load_clean_json(path) -> pd.DataFrame:
    """Load a clean JSON artifact with the same dtypes the pipeline produced."""
    df = pd.DataFrame(read_json(path))
    if "age_days" in df:
        df["age_days"] = pd.to_numeric(df["age_days"], errors="coerce").astype("Int64")
    return df


_SECRET_RE = re.compile(r"(sk|sk-proj|sk-ant|AIza)[-_A-Za-z0-9*]{8,}")


def _safe_error(exc: Exception) -> str:
    """Short error text with anything that looks like an API key redacted (never persist secrets)."""
    return f"{type(exc).__name__}: {_SECRET_RE.sub('[REDACTED]', str(exc))[:200]}"


def run_agent_demo(settings: Settings, index: LocalEmbeddingIndex) -> list[dict[str, Any]]:
    """Optional LangChain tool-calling agent demo; skipped gracefully if the provider cannot run tools."""
    from retrieval.agent import build_agent, run_agent_question

    answers: list[dict[str, Any]] = []
    try:
        agent = build_agent(settings, index)
    except Exception as exc:
        return [{"status": "skipped", "provider": settings.llm_provider, "reason": _safe_error(exc)}]
    for question in DEMO_QUESTIONS:
        try:
            answers.append({"question": question, "answer": run_agent_question(agent, question), "status": "ok"})
        except Exception as exc:
            answers.append({"question": question, "status": "error", "reason": _safe_error(exc)})
    return answers


def main() -> None:
    configure_logging()
    settings = load_settings()
    paths = settings.paths
    run_date: datetime = now_utc()

    # 1-2. Ingestion (live API or offline snapshot) + raw preservation.
    records = fetch_source_records(settings)
    logger.info("Raw records: %s", len(records))

    # 3-4. Cleaning + clean artifacts.
    clean_df = build_clean_dataframe(records, run_date)
    save_clean_artifacts(clean_df, paths.clean_csv, paths.clean_json)
    logger.info("Clean rows: %s -> %s", len(records), len(clean_df))

    # 5. Quality gate before serving (GX 1.x + freshness).
    quality = run_data_quality_checks(clean_df, settings, "baseline")
    freshness = build_freshness_report(clean_df, settings, paths.freshness_report)
    if not quality["success"]:
        raise RuntimeError(f"Baseline quality gate failed: {quality['failed_checks']}. Refusing to index bad data.")

    # 6. Chroma index (collection papers-baseline).
    index = LocalEmbeddingIndex.build(clean_df, settings, paths.embeddings_json)
    logger.info("Indexed %s docs into collection %s", index.collection.count(), index.collection_name)

    # 7. Fixed evaluation set (reused by corrupted/repaired runs).
    if settings.refresh_test_set or not paths.eval_testset.exists():
        build_test_set(clean_df, paths.eval_testset)
    test_set = read_json(paths.eval_testset)
    known_ids = set(clean_df["paper_id"])
    if not all(doc in known_ids for item in test_set for doc in item["ground_truth_doc_ids"]):
        logger.warning("Existing test set references unknown documents; rebuilding it.")
        build_test_set(clean_df, paths.eval_testset)

    # 8. Evaluate baseline.
    bundle = evaluate_pipeline(settings, index, paths.eval_testset, paths.baseline_metrics, paths.baseline_answers)
    logger.info("Baseline metrics: %s", {k: v for k, v in bundle.summary.items() if k != "ragas"})

    # 9. Optional agent demo.
    write_json(paths.demo_answers, run_agent_demo(settings, index))

    # 10. Report.
    source_summary = {
        "source_api": settings.source_api,
        "query": settings.source_query,
        "filter": settings.source_filter,
        "mode": LAST_FETCH_INFO.get("mode", "unknown"),
        "raw_response": paths.raw_api_response.relative_to(paths.project_dir).as_posix(),
        "raw_records": paths.raw_records_json.relative_to(paths.project_dir).as_posix(),
        "raw_record_count": len(records),
        "clean_row_count": len(clean_df),
        "run_date": run_date.date().isoformat(),
        "embedding_model": settings.embedding_model,
        "collection": index.collection_name,
        "indexed_documents": index.collection.count(),
        "top_k": settings.top_k,
        "llm_provider": settings.llm_provider,
    }
    write_json(paths.project_dir / "data" / "results" / "phase1_run.json", source_summary)
    generate_phase1_report(paths.baseline_report, source_summary, bundle.summary, quality, freshness)

    print("\n=== Phase 1 baseline complete ===")
    for key in ("samples", "retrieval_hit_rate", "mean_token_f1", "judge_accuracy", "mean_judge_score"):
        print(f"{key:>20}: {bundle.summary[key]}")
    print(f"{'quality_gate':>20}: {quality['success']}")
    print(f"{'is_fresh':>20}: {freshness['is_fresh']}")
    print(f"Report: {paths.baseline_report.relative_to(paths.project_dir).as_posix()}")
    print(f"Dashboard: {build_dashboard(settings).relative_to(paths.project_dir).as_posix()}")


if __name__ == "__main__":
    main()
