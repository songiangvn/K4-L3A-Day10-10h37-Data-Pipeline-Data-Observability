from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from core.utils import compact_join, normalize_whitespace
from ingestion.crossref import PaperRecord, strip_markup

CLEAN_COLUMNS = [
    "paper_id",
    "title",
    "summary",
    "authors",
    "categories",
    "primary_category",
    "published",
    "updated",
    "age_days",
    "authors_joined",
    "categories_joined",
    "summary_chars",
    "abs_url",
    "pdf_url",
    "comment",
    "text_for_embedding",
]


def build_text_for_embedding(title: str, authors_joined: str, published: str, categories_joined: str, summary: str) -> str:
    """5-part document text that is embedded into the vector store."""
    return (
        f"Title: {title}\n"
        f"Authors: {authors_joined}\n"
        f"Published: {published}\n"
        f"Categories: {categories_joined}\n"
        f"Summary: {summary}"
    )


def add_derived_columns(df: pd.DataFrame, run_date: datetime) -> pd.DataFrame:
    """(Re)compute `age_days`, joined helper columns and `text_for_embedding` from base columns.

    Shared by cleaning and corruption so corrupted fields propagate into the embedded text.
    """
    out = df.copy()
    run_day = pd.Timestamp(_as_utc(run_date).date())
    published = pd.to_datetime(out["published"], errors="coerce")
    out["age_days"] = (run_day - published).dt.days.astype("Int64")
    out["authors_joined"] = out["authors"].map(lambda items: compact_join(items or []))
    out["categories_joined"] = out["categories"].map(lambda items: compact_join(items or []))
    out["summary_chars"] = out["summary"].fillna("").str.len().astype(int)
    out["text_for_embedding"] = [
        build_text_for_embedding(row.title, row.authors_joined, row.published, row.categories_joined, row.summary)
        for row in out.itertuples(index=False)
    ]
    return out


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _normalize_date(value: str) -> str:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return "" if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def build_clean_dataframe(records: list[PaperRecord], run_date: datetime) -> pd.DataFrame:
    """Clean raw records into an embedding-ready dataframe.

    Rules:
    - strip JATS/HTML tags and collapse whitespace in title/summary/authors/categories
    - normalise `published`/`updated` to ISO dates (`updated` falls back to `published`)
    - drop rows without paper_id/title/summary/published
    - de-duplicate on `paper_id` (keep the most recently updated version)
    - derive `age_days`, joined helper columns and the 5-part `text_for_embedding`
    - sort newest first, then by `paper_id` for a deterministic order
    """
    rows = []
    for record in records:
        published = _normalize_date(record.published)
        rows.append(
            {
                "paper_id": normalize_whitespace(record.paper_id).lower(),
                "title": strip_markup(record.title),
                "summary": strip_markup(record.summary),
                "authors": [normalize_whitespace(name) for name in record.authors if normalize_whitespace(name)],
                "categories": [normalize_whitespace(c) for c in record.categories if normalize_whitespace(c)],
                "primary_category": normalize_whitespace(record.primary_category) or "Uncategorized",
                "published": published,
                "updated": _normalize_date(record.updated) or published,
                "abs_url": normalize_whitespace(record.abs_url),
                "pdf_url": normalize_whitespace(record.pdf_url),
                "comment": normalize_whitespace(record.comment),
            }
        )

    df = pd.DataFrame(rows, columns=[c for c in CLEAN_COLUMNS if c not in {
        "age_days", "authors_joined", "categories_joined", "summary_chars", "text_for_embedding"
    }])
    if df.empty:
        return pd.DataFrame(columns=CLEAN_COLUMNS)

    required = ["paper_id", "title", "summary", "published"]
    df = df[(df[required] != "").all(axis=1)]
    df = df.sort_values(["paper_id", "updated"], ascending=[True, False])
    df = df.drop_duplicates(subset="paper_id", keep="first")

    df = add_derived_columns(df, run_date)
    df = df.sort_values(["published", "paper_id"], ascending=[False, True]).reset_index(drop=True)
    return df[CLEAN_COLUMNS]
