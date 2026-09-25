from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import html
import logging
import re
import time
from typing import Any

import requests

from core.config import Settings
from core.utils import normalize_whitespace, read_json, write_json

logger = logging.getLogger(__name__)

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
USER_AGENT = "day10-data-observability-lab/0.1 (mailto:lab@example.com)"

_TAG_RE = re.compile(r"<[^>]+>")

# Populated by `fetch_source_records` so orchestrators can report lineage (live vs snapshot).
LAST_FETCH_INFO: dict[str, Any] = {}


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    title: str
    summary: str
    authors: list[str]
    categories: list[str]
    primary_category: str
    published: str
    updated: str
    abs_url: str
    pdf_url: str
    comment: str


def strip_markup(value: str) -> str:
    """Remove JATS/HTML tags (e.g. `<jats:p>`), unescape entities and collapse whitespace."""
    return normalize_whitespace(html.unescape(_TAG_RE.sub(" ", value or "")))


def _date_from_parts(block: Any) -> str:
    """Convert a Crossref date block (`{"date-parts": [[2026, 5, 20]]}`) to `YYYY-MM-DD`."""
    if not isinstance(block, dict):
        return ""
    parts = (block.get("date-parts") or [[]])[0] or []
    if not parts or parts[0] is None:
        date_time = block.get("date-time")
        return str(date_time)[:10] if date_time else ""
    year = int(parts[0])
    month = int(parts[1]) if len(parts) > 1 and parts[1] else 1
    day = int(parts[2]) if len(parts) > 2 and parts[2] else 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _first_date(item: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _date_from_parts(item.get(key))
        if value:
            return value
    return ""


def _author_name(author: dict) -> str:
    name = " ".join(part for part in (author.get("given"), author.get("family")) if part)
    return normalize_whitespace(name or author.get("name", ""))


def _pdf_url(item: dict, fallback: str) -> str:
    for link in item.get("link") or []:
        if "pdf" in str(link.get("content-type", "")).lower() and link.get("URL"):
            return str(link["URL"])
    return fallback


def parse_crossref_payload(payload: dict) -> list[PaperRecord]:
    """Parse a Crossref `/works` payload into validated, de-duplicated `PaperRecord`s.

    Records without DOI, title or abstract are dropped because they cannot be
    embedded or referenced by the evaluation set.
    """
    items = (payload.get("message") or {}).get("items") or []
    records: list[PaperRecord] = []
    seen: set[str] = set()

    for item in items:
        doi = normalize_whitespace(str(item.get("DOI") or "")).lower()
        title = strip_markup(" ".join(item.get("title") or []))
        summary = strip_markup(item.get("abstract") or "")
        if not doi or not title or not summary or doi in seen:
            continue
        seen.add(doi)

        authors = [name for name in (_author_name(author) for author in item.get("author") or []) if name]
        categories = [normalize_whitespace(subject) for subject in item.get("subject") or [] if subject]
        published = _first_date(item, ("published", "published-print", "published-online", "issued", "created"))
        updated = _first_date(item, ("updated", "deposited", "indexed")) or published
        abs_url = str(item.get("URL") or f"https://doi.org/{doi}")

        records.append(
            PaperRecord(
                paper_id=doi,
                title=title,
                summary=summary,
                authors=authors,
                categories=categories,
                primary_category=categories[0] if categories else "Uncategorized",
                published=published,
                updated=updated,
                abs_url=abs_url,
                pdf_url=_pdf_url(item, abs_url),
                comment=f"Crossref record {doi}",
            )
        )
    return records


def _request_crossref(settings: Settings, max_attempts: int = 4, backoff_seconds: float = 2.0) -> dict:
    params = {
        "query": settings.source_query,
        "filter": settings.source_filter,
        "rows": settings.max_results,
        "select": "DOI,title,abstract,author,subject,published,published-print,published-online,"
        "issued,created,updated,deposited,URL,link",
    }
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(
                CROSSREF_WORKS_URL,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            if response.status_code in RETRYABLE_STATUS_CODES:
                raise requests.HTTPError(f"Retryable status {response.status_code}", response=response)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < max_attempts:
                wait = backoff_seconds * (2 ** (attempt - 1))
                logger.warning("Crossref attempt %s/%s failed (%s); retrying in %.1fs", attempt, max_attempts, exc, wait)
                time.sleep(wait)
    raise RuntimeError(f"Crossref API unavailable after {max_attempts} attempts: {last_error}")


def fetch_source_records(settings: Settings) -> list[PaperRecord]:
    """Fetch Crossref records, preserve raw artifacts and return parsed records.

    Dual mode:
    - Offline (default): reuse the snapshot `data/raw/crossref_response.json` so runs are reproducible.
    - Live (`REFRESH_SOURCE=1` or no snapshot yet): call the Crossref API with retry/backoff on
      429/5xx. If the live call fails or returns no usable records, fall back to the snapshot.
    """
    raw_path = settings.paths.raw_api_response
    payload: dict | None = None
    mode = "snapshot"

    if settings.refresh_source or not raw_path.exists():
        try:
            live_payload = _request_crossref(settings)
            if parse_crossref_payload(live_payload):
                payload = live_payload
                mode = "live"
                write_json(raw_path, payload)
            else:
                logger.warning("Crossref live response had no usable records; using snapshot.")
        except RuntimeError as exc:
            logger.warning("%s; falling back to local snapshot.", exc)

    if payload is None:
        if not raw_path.exists():
            raise FileNotFoundError(f"No Crossref snapshot at {raw_path} and the live API is unavailable.")
        payload = read_json(raw_path)

    records = parse_crossref_payload(payload)
    write_json(settings.paths.raw_records_json, [asdict(record) for record in records])
    LAST_FETCH_INFO.clear()
    LAST_FETCH_INFO.update({"mode": mode, "items_in_payload": len(payload["message"]["items"]), "records": len(records)})
    logger.info("Loaded %s Crossref records (mode=%s)", len(records), mode)
    return records


def load_raw_records(path: Path) -> list[PaperRecord]:
    """Read the raw records snapshot and map each row back to `PaperRecord`."""
    rows = read_json(Path(path))
    fields = PaperRecord.__dataclass_fields__.keys()
    records: list[PaperRecord] = []
    for row in rows:
        values = {field: row.get(field) for field in fields}
        values["authors"] = list(values["authors"] or [])
        values["categories"] = list(values["categories"] or [])
        for field in fields - {"authors", "categories"}:
            values[field] = "" if values[field] is None else str(values[field])
        records.append(PaperRecord(**values))
    return records
