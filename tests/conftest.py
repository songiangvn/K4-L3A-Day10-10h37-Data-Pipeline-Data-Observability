from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import shutil

import pytest

from core.config import load_settings
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import load_raw_records

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_DATE = datetime(2026, 9, 25, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    """Tests never call a paid LLM: force the offline mock provider."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MODEL", "mock")
    monkeypatch.delenv("REFRESH_SOURCE", raising=False)
    monkeypatch.delenv("REFRESH_TEST_SET", raising=False)
    monkeypatch.delenv("RUN_RAGAS", raising=False)


def make_project(root: Path) -> Path:
    raw = root / "data" / "raw"
    raw.mkdir(parents=True)
    for name in ("crossref_response.json", "crossref_records.json"):
        shutil.copy(REPO_ROOT / "data" / "raw" / name, raw / name)
    return root


@pytest.fixture
def project(tmp_path) -> Path:
    return make_project(tmp_path / "project")


@pytest.fixture
def settings(project):
    return load_settings(project)


@pytest.fixture
def records(settings):
    return load_raw_records(settings.paths.raw_records_json)


@pytest.fixture
def clean_df(records):
    return build_clean_dataframe(records, RUN_DATE)


@pytest.fixture(scope="session")
def e2e_project(tmp_path_factory):
    """Run phase 1 + corruption flow once on an isolated copy of the project."""
    import pipelines.corruption_flow as corruption_flow
    import pipelines.phase1 as phase1

    mp = pytest.MonkeyPatch()
    mp.setenv("LLM_PROVIDER", "mock")
    mp.setenv("LLM_MODEL", "mock")
    root = make_project(tmp_path_factory.mktemp("e2e") / "project")
    mp.setattr(phase1, "load_settings", lambda: load_settings(root))
    mp.setattr(corruption_flow, "load_settings", lambda: load_settings(root))
    phase1.main()
    corruption_flow.main()
    yield load_settings(root)
    mp.undo()
