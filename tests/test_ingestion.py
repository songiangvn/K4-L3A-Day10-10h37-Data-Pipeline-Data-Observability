from __future__ import annotations

import requests

from core.config import load_settings
from core.utils import read_json
from ingestion import crossref
from ingestion.crossref import fetch_source_records, load_raw_records, parse_crossref_payload, strip_markup

PAYLOAD = {
    "message": {
        "items": [
            {
                "DOI": "10.1/ABC",
                "title": ["  A   Title  "],
                "abstract": "<jats:p>Hello &amp; <jats:italic>world</jats:italic></jats:p>",
                "author": [{"given": "Ada", "family": "Lovelace"}, {"name": "Consortium X"}],
                "subject": ["AI"],
                "published": {"date-parts": [[2026, 5]]},
                "URL": "https://doi.org/10.1/abc",
                "link": [{"content-type": "application/pdf", "URL": "https://x/pdf"}],
            },
            {"DOI": "10.1/abc", "title": ["dup"], "abstract": "dup"},
            {"DOI": "10.1/noabstract", "title": ["t"]},
            {"title": ["no doi"], "abstract": "x"},
            {"DOI": "10.1/dt", "title": ["t2"], "abstract": "a", "created": {"date-time": "2026-01-02T00:00:00Z"}},
        ]
    }
}


class _Response:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


def test_strip_markup_removes_jats_and_whitespace():
    assert strip_markup("<jats:p>  a\n b &lt;c&gt; </jats:p>") == "a b <c>"


def test_parse_payload_normalises_and_filters():
    records = parse_crossref_payload(PAYLOAD)
    assert [r.paper_id for r in records] == ["10.1/abc", "10.1/dt"]
    first = records[0]
    assert first.title == "A Title"
    assert first.summary == "Hello & world"
    assert first.authors == ["Ada Lovelace", "Consortium X"]
    assert first.published == "2026-05-01"
    assert first.pdf_url == "https://x/pdf"
    assert first.primary_category == "AI"
    assert records[1].published == "2026-01-02"
    assert records[1].primary_category == "Uncategorized"


def test_snapshot_parses_to_24_records(settings):
    records = parse_crossref_payload(read_json(settings.paths.raw_api_response))
    assert len(records) == 24
    assert all("<jats" not in r.summary for r in records)


def test_fetch_uses_snapshot_offline(settings, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("network must not be called in offline mode")

    monkeypatch.setattr(crossref.requests, "get", boom)
    records = fetch_source_records(settings)
    assert len(records) == 24
    assert crossref.LAST_FETCH_INFO["mode"] == "snapshot"
    assert len(read_json(settings.paths.raw_records_json)) == 24


def test_fetch_live_retries_429_then_succeeds(project, monkeypatch):
    monkeypatch.setenv("REFRESH_SOURCE", "1")
    live_settings = load_settings(project)
    responses = iter([_Response(429), _Response(200, PAYLOAD)])
    monkeypatch.setattr(crossref.requests, "get", lambda *a, **k: next(responses))
    monkeypatch.setattr(crossref.time, "sleep", lambda s: None)
    records = fetch_source_records(live_settings)
    assert len(records) == 2
    assert crossref.LAST_FETCH_INFO["mode"] == "live"
    assert read_json(live_settings.paths.raw_api_response) == PAYLOAD


def test_fetch_live_failure_falls_back_to_snapshot(project, monkeypatch):
    monkeypatch.setenv("REFRESH_SOURCE", "1")
    live_settings = load_settings(project)
    monkeypatch.setattr(crossref.requests, "get", lambda *a, **k: _Response(503))
    monkeypatch.setattr(crossref.time, "sleep", lambda s: None)
    records = fetch_source_records(live_settings)
    assert len(records) == 24
    assert crossref.LAST_FETCH_INFO["mode"] == "snapshot"


def test_load_raw_records_roundtrip(settings):
    records = load_raw_records(settings.paths.raw_records_json)
    assert len(records) == 24
    assert isinstance(records[0].authors, list)
