from __future__ import annotations

import math
import random
from typing import Any

import pandas as pd

from core.utils import now_utc, write_json
from ingestion.cleaning import build_text_for_embedding

SEED = 42
DROP_LATEST_RATIO = 0.20
BLANK_SUMMARY_RATIO = 0.20
NOISE_RATIO = 0.20
TRUNCATE_TITLE_RATIO = 0.25
STALE_DATE_RATIO = 0.40
STALE_SHIFT_DAYS = 365
DUPLICATE_RATIO = 0.30
TITLE_MAX_CHARS = 7
NOISE_TOKEN = "#@!$%^ lorem ipsum ##ERR## 0xDEADBEEF"


def _sample(rng: random.Random, population: list[int], ratio: float) -> list[int]:
    if not population:
        return []
    count = max(1, math.ceil(len(population) * ratio))
    return sorted(rng.sample(population, min(count, len(population))))


def _ids(df: pd.DataFrame, positions: list[int]) -> list[str]:
    return [str(df.loc[p, "paper_id"]) for p in positions]


def corrupt_clean_dataframe(df: pd.DataFrame, output_log_path) -> pd.DataFrame:
    """Inject 6 realistic, deterministic (seed=42) data incidents into a clean dataframe.

    1. drop_latest_records  - lose the newest 20% of papers (ingestion lag / missed increment)
    2. blank_summary        - empty abstracts (scraper returned empty field)
    3. inject_noise         - garbage characters prepended to abstracts (encoding / parsing noise)
    4. truncate_title       - titles cut below 8 chars (column width / truncation bug)
    5. stale_date           - published date pushed back 365 days (stale snapshot)
    6. duplicate_rows       - rows appended twice (non-idempotent re-load)

    `text_for_embedding`, `summary_chars` and `age_days` are rebuilt so the damage reaches the index.
    A JSON log with parameters and affected `paper_id`s is written to `output_log_path`.
    """
    rng = random.Random(SEED)
    corrupted = df.copy()
    corrupted["authors"] = corrupted["authors"].map(lambda v: list(v) if isinstance(v, (list, tuple)) else v)
    corrupted["categories"] = corrupted["categories"].map(lambda v: list(v) if isinstance(v, (list, tuple)) else v)
    log: list[dict[str, Any]] = []

    # 1. Drop latest records.
    ordered = corrupted.sort_values(["published", "paper_id"], ascending=[False, True])
    drop_count = max(1, math.ceil(len(ordered) * DROP_LATEST_RATIO))
    dropped = ordered.head(drop_count)
    corrupted = corrupted.drop(index=dropped.index).reset_index(drop=True)
    log.append(
        {
            "corruption": "drop_latest_records",
            "description": f"Dropped the newest {DROP_LATEST_RATIO:.0%} of papers by published date.",
            "params": {"ratio": DROP_LATEST_RATIO},
            "affected_rows": int(drop_count),
            "affected_paper_ids": dropped["paper_id"].astype(str).tolist(),
        }
    )

    positions = list(range(len(corrupted)))

    # 2. Blank summary.
    blank = _sample(rng, positions, BLANK_SUMMARY_RATIO)
    corrupted.loc[blank, "summary"] = ""
    log.append(
        {
            "corruption": "blank_summary",
            "description": "Replaced the abstract with an empty string.",
            "params": {"ratio": BLANK_SUMMARY_RATIO},
            "affected_rows": len(blank),
            "affected_paper_ids": _ids(corrupted, blank),
        }
    )

    # 3. Inject noise into summaries that still have text.
    noise_pool = [p for p in positions if p not in set(blank)]
    noisy = _sample(rng, noise_pool, NOISE_RATIO)
    corrupted.loc[noisy, "summary"] = corrupted.loc[noisy, "summary"].map(lambda s: f"{NOISE_TOKEN} {s} {NOISE_TOKEN}")
    log.append(
        {
            "corruption": "inject_noise",
            "description": "Wrapped the abstract with garbage tokens.",
            "params": {"ratio": NOISE_RATIO, "noise_token": NOISE_TOKEN},
            "affected_rows": len(noisy),
            "affected_paper_ids": _ids(corrupted, noisy),
        }
    )

    # 4. Truncate titles.
    truncated = _sample(rng, positions, TRUNCATE_TITLE_RATIO)
    corrupted.loc[truncated, "title"] = corrupted.loc[truncated, "title"].map(lambda t: str(t)[:TITLE_MAX_CHARS])
    log.append(
        {
            "corruption": "truncate_title",
            "description": f"Cut titles to {TITLE_MAX_CHARS} characters (< 8).",
            "params": {"ratio": TRUNCATE_TITLE_RATIO, "max_chars": TITLE_MAX_CHARS},
            "affected_rows": len(truncated),
            "affected_paper_ids": _ids(corrupted, truncated),
        }
    )

    # 5. Stale dates.
    stale = _sample(rng, positions, STALE_DATE_RATIO)
    shifted = pd.to_datetime(corrupted.loc[stale, "published"]) - pd.Timedelta(days=STALE_SHIFT_DAYS)
    corrupted.loc[stale, "published"] = shifted.dt.strftime("%Y-%m-%d")
    corrupted.loc[stale, "updated"] = corrupted.loc[stale, "published"]
    corrupted["age_days"] = pd.to_numeric(corrupted["age_days"]).astype("Int64")
    corrupted.loc[stale, "age_days"] = corrupted.loc[stale, "age_days"] + STALE_SHIFT_DAYS
    log.append(
        {
            "corruption": "stale_date",
            "description": f"Moved the published date back {STALE_SHIFT_DAYS} days.",
            "params": {"ratio": STALE_DATE_RATIO, "shift_days": STALE_SHIFT_DAYS},
            "affected_rows": len(stale),
            "affected_paper_ids": _ids(corrupted, stale),
        }
    )

    # 6. Duplicate rows.
    duplicated = _sample(rng, positions, DUPLICATE_RATIO)
    corrupted = pd.concat([corrupted, corrupted.loc[duplicated]], ignore_index=True)
    log.append(
        {
            "corruption": "duplicate_rows",
            "description": "Appended exact copies of existing rows.",
            "params": {"ratio": DUPLICATE_RATIO},
            "affected_rows": len(duplicated),
            "affected_paper_ids": _ids(corrupted, duplicated),
        }
    )

    # 7. Rebuild derived text so corrupted fields reach the embeddings.
    corrupted["summary_chars"] = corrupted["summary"].fillna("").str.len().astype(int)
    corrupted["text_for_embedding"] = [
        build_text_for_embedding(row.title, row.authors_joined, row.published, row.categories_joined, row.summary)
        for row in corrupted.itertuples(index=False)
    ]

    # 8. Write corruption log.
    write_json(
        output_log_path,
        {
            "generated_at": now_utc().isoformat(),
            "seed": SEED,
            "input_rows": int(len(df)),
            "output_rows": int(len(corrupted)),
            "corruption_count": len(log),
            "corruptions": log,
        },
    )
    return corrupted
