from __future__ import annotations

from typing import Any

import pandas as pd

from core.utils import compact_join, first_sentence, write_json

MIN_DOCUMENTS = 10

# (question_type, template) — wording must match the intent rules in `retrieval/qa.py::_extract_answer`.
QUESTION_PLAN: list[tuple[str, str]] = [
    ("summary", "What is the summary of the paper '{title}'?"),
    ("authors", "Who authored the paper '{title}'?"),
    ("date", "When was the paper '{title}' published?"),
    ("categories", "What categories does the paper '{title}' belong to?"),
    ("summary", "What is the summary of the paper '{title}'?"),
    ("authors", "Who authored the paper '{title}'?"),
    ("date", "When was the paper '{title}' published?"),
    ("categories", "What categories does the paper '{title}' belong to?"),
    ("summary", "What is the summary of the paper '{title}'?"),
    ("authors", "Who authored the paper '{title}'?"),
]


def _as_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [] if value is None or value != value else [str(value)]


def _ground_truth(row: pd.Series, question_type: str) -> str:
    if question_type == "summary":
        return first_sentence(str(row["summary"]))
    if question_type == "authors":
        return str(row.get("authors_joined") or compact_join(_as_list(row["authors"])))
    if question_type == "date":
        return str(row["published"])[:10]
    if question_type == "categories":
        return str(row.get("categories_joined") or compact_join(_as_list(row["categories"])))
    raise ValueError(f"Unknown question type: {question_type}")


def build_test_set(df: pd.DataFrame, output_path) -> list[dict[str, Any]]:
    """Build a fixed 10-question benchmark covering summary/authors/date/categories.

    Papers are picked at evenly spaced positions of the date-sorted corpus (newest first) so the
    set spans fresh and older records; each question targets a different paper and stores the
    DOI as `ground_truth_doc_ids` for retrieval hit-rate. Titles containing `'` are skipped because
    the QA layer extracts the quoted title for exact lookup.
    """
    candidates = df[~df["title"].astype(str).str.contains("'")].copy()
    candidates = candidates.drop_duplicates(subset="paper_id")
    if len(candidates) < MIN_DOCUMENTS:
        raise ValueError(f"Need at least {MIN_DOCUMENTS} clean documents to build the test set, got {len(candidates)}.")

    candidates = candidates.sort_values(["published", "paper_id"], ascending=[False, True]).reset_index(drop=True)
    step = len(candidates) / len(QUESTION_PLAN)
    positions = [int(i * step) for i in range(len(QUESTION_PLAN))]

    test_set: list[dict[str, Any]] = []
    for number, (position, (question_type, template)) in enumerate(zip(positions, QUESTION_PLAN), start=1):
        row = candidates.iloc[position]
        test_set.append(
            {
                "id": f"eval_{number:03d}",
                "question_type": question_type,
                "question": template.format(title=row["title"]),
                "ground_truth": _ground_truth(row, question_type),
                "ground_truth_doc_ids": [str(row["paper_id"])],
            }
        )

    write_json(output_path, test_set)
    return test_set
