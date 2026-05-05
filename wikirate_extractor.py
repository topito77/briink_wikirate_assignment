"""
WikiRate ESG Data Extractor
============================
Fetches ESG metric answers from the WikiRate API and transforms them into
a structured JSON format suitable for ML evaluation.

Usage:
    python wikirate_extractor.py

Output:
    output.json  –  list of records following the Briink evaluation schema

Requires:
    pip install requests
"""

import json
import os
import re
import sys
import time
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# API key is read from the environment variable WIKIRATE_API_KEY.
# A fallback demo key is provided for convenience during evaluation; replace
# it with your own key or unset the fallback before deploying to production.
API_KEY = os.getenv("WIKIRATE_API_KEY", "yexBJaUij2HvTrsUILvvJgtt")
BASE_URL = "https://wikirate.org"

# Three ESG metrics chosen (value_type=Number so data_type maps to "Metric"):
#   1. Scope 1 GHG Emissions  – Environmental pillar
#   2. Scope 2 GHG Emissions  – Environmental pillar
#   3. Women on Board (%)     – Governance pillar
#
# Each entry:
#   metric_id  – the WikiRate card name  "{designer}+{metric_name}"
#   question   – human-readable question as shown on WikiRate
METRICS = [
    {
        "metric_id": "Commons+Scope_1_emissions_tCO2e",
        "question": "What are the company's Scope 1 (direct) greenhouse gas emissions in metric tonnes of CO2 equivalent?",
    },
    {
        "metric_id": "Commons+Scope_2_emissions_tCO2e",
        "question": "What are the company's Scope 2 (indirect, energy-related) greenhouse gas emissions in metric tonnes of CO2 equivalent?",
    },
    {
        "metric_id": "Commons+Women_on_Board",
        "question": "What percentage of the company's board of directors are women?",
    },
]

# Minimum number of companies per metric required by the task
MIN_COMPANIES = 10

# WikiRate API page size (max 100 per request)
PAGE_SIZE = 100

OUTPUT_FILE = "output.json"


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


def _get(endpoint: str, params: Optional[dict] = None) -> dict:
    """Perform a GET request against the WikiRate API and return parsed JSON.

    Raises a RuntimeError on HTTP errors so that callers can handle failures.
    A small sleep is added between calls to be polite to the API.
    """
    if params is None:
        params = {}
    params["api_key"] = API_KEY

    url = f"{BASE_URL}/{endpoint}"
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"API request failed for {url}: {exc}") from exc

    time.sleep(0.25)  # polite throttle
    return response.json()


def fetch_metric_metadata(metric_id: str) -> dict:
    """Return the metadata card for a single metric."""
    return _get(f"{metric_id}.json")


def fetch_answers(metric_id: str, limit: int = PAGE_SIZE) -> list[dict]:
    """Fetch all answers for *metric_id* that have at least one source.

    Paginates automatically until no more results or *limit* is reached.
    Only answers that include at least one source with a non-empty
    ``file_url`` are kept, as required by the output schema.
    """
    results: list[dict] = []
    offset = 0

    while True:
        data = _get(
            f"{metric_id}+Answer.json",
            params={"limit": PAGE_SIZE, "offset": offset},
        )

        items = data.get("items", [])
        if not items:
            break

        for item in items:
            sources = item.get("source", []) or []
            # Keep only answers that have at least one usable source file
            usable_sources = [
                s for s in sources if s.get("file_url")
            ]
            if usable_sources:
                results.append(item)

        offset += PAGE_SIZE
        if offset >= data.get("total", 0) or len(results) >= limit:
            break

    return results[:limit]


# ---------------------------------------------------------------------------
# Page-number extraction
# ---------------------------------------------------------------------------

_PAGE_PATTERNS = [
    re.compile(r"p(?:age|\.)\s*(\d+)", re.IGNORECASE),
    re.compile(r"pg\.\s*(\d+)", re.IGNORECASE),
    re.compile(r"\bpage\s+(\d+)\b", re.IGNORECASE),
]


def _extract_page_number(comment: Optional[str]) -> Optional[int]:
    """Try to pull a page number from the answer comment text.

    Returns an integer if a pattern like "page 43", "p. 43", or "pg. 43" is
    found, otherwise None.
    """
    if not comment:
        return None
    for pattern in _PAGE_PATTERNS:
        match = pattern.search(comment)
        if match:
            return int(match.group(1))
    return None


# ---------------------------------------------------------------------------
# Schema transformation
# ---------------------------------------------------------------------------


def _build_file_metas(sources: list[dict]) -> list[dict]:
    """Convert WikiRate source objects to the file_metas schema."""
    return [
        {
            "file_name": s.get("title", "Unknown"),
            "file_url": s.get("file_url", ""),
        }
        for s in sources
        if s.get("file_url")
    ]


def _build_source_documents(
    sources: list[dict], page_number: Optional[int]
) -> list[dict]:
    """Convert WikiRate source objects to the source_documents schema.

    Adds ``page_number`` only when it can be parsed from the answer comment.
    """
    docs = []
    for s in sources:
        if not s.get("file_url"):
            continue
        doc: dict = {
            "file_name": s.get("title", "Unknown"),
            "file_url": s.get("file_url", ""),
        }
        if page_number is not None:
            doc["page_number"] = page_number
        docs.append(doc)
    return docs


def _build_structured_data(
    value: str, metric_id: str, year: str
) -> list[dict]:
    """Build the optional structured_data array.

    Parses the numeric value and infers the unit from the metric id.
    """
    # Attempt to parse numeric value (WikiRate stores values as strings)
    try:
        numeric_value: Optional[float] = float(value)
    except (ValueError, TypeError):
        numeric_value = None

    # Infer unit from metric id suffix
    unit: Optional[str] = None
    lower_id = metric_id.lower()
    if "tco2e" in lower_id:
        unit = "tCO2e"
    elif "_mwh" in lower_id:
        unit = "MWh"
    elif "_gj" in lower_id:
        unit = "GJ"
    elif "percent" in lower_id or "women_on_board" in lower_id:
        unit = "%"

    if numeric_value is None:
        return []

    entry: dict = {"value": numeric_value, "time_period": str(year)}
    if unit:
        entry["unit"] = unit
    return [entry]


def transform_answer(answer: dict, metric: dict) -> dict:
    """Transform a single WikiRate answer into the Briink evaluation schema."""
    metric_id = metric["metric_id"]
    question = metric["question"]

    company_name: str = answer.get("company", "Unknown")
    year: str = str(answer.get("year", ""))
    value: str = str(answer.get("value", ""))
    comment: Optional[str] = answer.get("comment")

    sources = [s for s in (answer.get("source") or []) if s.get("file_url")]

    page_number = _extract_page_number(comment)
    file_metas = _build_file_metas(sources)
    source_documents = _build_source_documents(sources, page_number)
    structured_data = _build_structured_data(value, metric_id, year)

    # Build the answer string – include the year so context is self-contained
    answer_text = value
    if year:
        answer_text = f"{value} ({year})"

    record: dict = {
        "input": {
            "question": question,
            "custom_id": metric_id,
            "data_type": "Metric",
            "company": company_name,
            "file_metas": file_metas,
        },
        "reference_output": {
            "answer": answer_text,
            "source_documents": source_documents,
        },
    }

    if structured_data:
        record["structured_data"] = structured_data

    return record


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def extract_and_transform() -> list[dict]:
    """Fetch data for all configured metrics and return transformed records."""
    all_records: list[dict] = []

    for metric in METRICS:
        metric_id = metric["metric_id"]
        print(f"\nProcessing metric: {metric_id}")

        try:
            answers = fetch_answers(metric_id)
        except RuntimeError as exc:
            print(f"  ERROR – skipping metric: {exc}", file=sys.stderr)
            continue

        print(f"  Found {len(answers)} answers with sources.")

        if len(answers) < MIN_COMPANIES:
            print(
                f"  WARNING: only {len(answers)} answers found "
                f"(target is {MIN_COMPANIES}+).",
                file=sys.stderr,
            )

        for answer in answers:
            record = transform_answer(answer, metric)
            all_records.append(record)

    return all_records


def main() -> None:
    print("WikiRate ESG Data Extractor")
    print("=" * 40)

    records = extract_and_transform()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)

    print(f"\nDone. {len(records)} records written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
