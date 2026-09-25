from __future__ import annotations

import pytest

from core.config import load_settings, normalized_provider, require_llm_credentials
from core.utils import read_json
from evaluation.metrics import _token_f1, evaluate_pipeline
from evaluation.testset import build_test_set
from observability.reporting import generate_phase1_report
from retrieval.index import LocalEmbeddingIndex
from retrieval.llm import build_llm
from retrieval.qa import answer_question


def test_test_set_covers_four_types(clean_df, settings):
    test_set = build_test_set(clean_df, settings.paths.eval_testset)
    assert len(test_set) == 10
    assert {item["question_type"] for item in test_set} == {"summary", "authors", "date", "categories"}
    assert len({item["ground_truth_doc_ids"][0] for item in test_set}) == 10
    assert read_json(settings.paths.eval_testset) == test_set


def test_test_set_requires_enough_docs(clean_df, settings):
    with pytest.raises(ValueError):
        build_test_set(clean_df.head(5), settings.paths.eval_testset)


def test_index_search_lookup_and_eval(clean_df, settings):
    index = LocalEmbeddingIndex.build(clean_df, settings, settings.paths.embeddings_json)
    assert index.collection_name == "papers-baseline"
    assert index.collection.count() == 24
    assert read_json(settings.paths.embeddings_json)["persist_path"] == "data/chroma"

    reloaded = LocalEmbeddingIndex.load(settings)
    title = clean_df.loc[3, "title"]
    paper_id = clean_df.loc[3, "paper_id"]
    assert reloaded.lookup(title)["paper_id"] == paper_id
    assert reloaded.lookup("does-not-exist") is None
    # The corpus has near-duplicate "Advanced Perspectives on ..." twins, so the exact paper must be in the top-2.
    assert paper_id in [hit.paper_id for hit in reloaded.search(title, top_k=2)]

    assert answer_question(f"Who authored the paper '{title}'?", settings, index).answer == clean_df.loc[3, "authors_joined"]
    assert answer_question(f"When was the paper '{title}' published?", settings, index).answer == clean_df.loc[3, "published"]

    build_test_set(clean_df, settings.paths.eval_testset)
    bundle = evaluate_pipeline(
        settings, index, settings.paths.eval_testset, settings.paths.baseline_metrics, settings.paths.baseline_answers
    )
    assert bundle.summary["retrieval_hit_rate"] == 1.0
    assert bundle.summary["mean_token_f1"] == 1.0
    assert set(bundle.summary["by_question_type"]) == {"summary", "authors", "date", "categories"}

    quality = {"engine": "gx", "row_count": 24, "success": True, "expectations": [], "failed_checks": []}
    freshness = {"is_fresh": True, "stale_rows": 0, "total_rows": 24, "threshold_days": 180}
    generate_phase1_report(settings.paths.baseline_report, {"source": "x"}, bundle.summary, quality, freshness)
    assert "Phase 1 Report" in settings.paths.baseline_report.read_text(encoding="utf-8")


def test_token_f1():
    assert _token_f1("a b c", "a b c") == 1.0
    assert _token_f1("a b", "c d") == 0.0
    assert _token_f1("", "x") == 0.0


@pytest.mark.parametrize(
    "provider,key_env,expected",
    [
        ("gemini", "GOOGLE_API_KEY", "ChatGoogleGenerativeAI"),
        ("google", "GOOGLE_API_KEY", "ChatGoogleGenerativeAI"),
        ("openai", "OPENAI_API_KEY", "ChatOpenAI"),
        ("anthropic", "ANTHROPIC_API_KEY", "ChatAnthropic"),
        ("openrouter", "OPENROUTER_API_KEY", "ChatOpenAI"),
        ("ollama", None, "ChatOllama"),
        ("mock", None, "FakeListChatModel"),
    ],
)
def test_multi_provider_router(project, monkeypatch, provider, key_env, expected):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    if key_env:
        monkeypatch.setenv(key_env, "test-key-not-real")
    assert type(build_llm(load_settings(project))).__name__ == expected


def test_custom_provider_and_missing_credentials(project, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "custom-llm")
    monkeypatch.setenv("CUSTOM_LLM_BASE_URL", "http://localhost:9999/v1")
    settings = load_settings(project)
    assert normalized_provider(settings) == "custom"
    assert type(build_llm(settings)).__name__ == "ChatOpenAI"

    for provider, env in [
        ("openai", "OPENAI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("openrouter", "OPENROUTER_API_KEY"),
        ("gemini", "GOOGLE_API_KEY"),
    ]:
        monkeypatch.setenv("LLM_PROVIDER", provider)
        monkeypatch.setenv(env, "")
        with pytest.raises(RuntimeError):
            require_llm_credentials(load_settings(project))
    monkeypatch.setenv("LLM_PROVIDER", "unknown")
    with pytest.raises(RuntimeError):
        require_llm_credentials(load_settings(project))
