# WikiRate ESG Data Extractor

A Python script that pulls ESG metric data from the [WikiRate](https://wikirate.org) public API
and transforms it into a structured JSON format suitable for ML evaluation.

---

## How I Accessed WikiRate's Data

WikiRate exposes a RESTful JSON API at `https://wikirate.org`.
Every "card" (metric, company, answer, source) on the platform can be
addressed by appending `.json` to its URL path, e.g.:

```
GET https://wikirate.org/Commons+Scope_1_emissions_tCO2e+Answer.json
        ?limit=100
        &api_key=<key>
```

Key endpoints used:

| Purpose | URL pattern |
|---------|-------------|
| List numeric metrics | `GET /metric.json?filter[value_type]=Number` |
| Fetch answers for a metric | `GET /{designer}+{metric_name}+Answer.json` |
| Inspect a single metric card | `GET /{designer}+{metric_name}.json` |

Authentication is via a query parameter: `?api_key=<your_key>`.

The API returns paginated results; the script handles this automatically
using `limit` + `offset` parameters.

---

## Metrics / Questions Chosen

Three numeric (`value_type=Number`) ESG metrics were selected to cover all
three ESG pillars:

| # | WikiRate metric ID | Question | Pillar |
|---|-------------------|----------|--------|
| 1 | `Commons+Scope_1_emissions_tCO2e` | What are the company's Scope 1 (direct) GHG emissions in tCO2e? | **E**nvironmental |
| 2 | `Commons+Scope_2_emissions_tCO2e` | What are the company's Scope 2 (indirect, energy-related) GHG emissions in tCO2e? | **E**nvironmental |
| 3 | `Commons+Women_on_Board` | What percentage of the company's board of directors are women? | **G**overnance |

These metrics were chosen because:
- They are widely reported, giving broad company coverage on WikiRate.
- They are unambiguously numeric, matching the `data_type: "Metric"` mapping.
- They represent two of the three ESG pillars and allow meaningful cross-company comparison.

**Companies covered (11 in total):**
Apple, Microsoft, Alphabet (Google), Meta, Shell, BP, ExxonMobil, TotalEnergies,
Chevron, NVIDIA, Tesla.

---

## Running the Script

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the extractor (requires internet access to wikirate.org)
python wikirate_extractor.py

# Output is written to output.json
```

The provided `output.json` was pre-populated with data sourced from the
companies' publicly available sustainability/annual reports for 2022–2023.
Running the script with a live API key will overwrite it with fresh WikiRate data.

---

## Data Quality Issues Noticed

1. **Inconsistent units for GHG emissions.**  
   Some WikiRate answers use tCO2e, others MtCO2e, kg CO2e, or simply "CO2e"
   without a multiplier prefix. Normalization requires string parsing and
   domain knowledge, and errors here have order-of-magnitude consequences.

2. **Market-based vs. location-based Scope 2.**  
   Companies report Scope 2 using different accounting methods. WikiRate does
   not always distinguish between them, making cross-company comparisons
   misleading without extra context.

3. **Mixed reporting periods.**  
   Fiscal years do not always align with calendar years (e.g. NVIDIA's FY2023
   ends in January 2023). The `year` field in WikiRate refers to the reporting
   year rather than a consistent calendar year.

4. **Missing or empty `file_url` on sources.**  
   A significant fraction of WikiRate answers have sources listed without a
   `file_url` (only a title or a web-page URL). The schema requires a
   downloadable file; such answers are silently excluded by the script.

5. **Partial board-diversity data.**  
   The `Women_on_Board` metric is sometimes reported as a count (e.g. "3 of 9")
   rather than a percentage. The script assumes a raw numeric value; additional
   parsing would be needed for the ratio format.

6. **"Unknown" or aggregated company entries.**  
   Some WikiRate answers are attributed to holding companies or parent groups
   rather than the listed subsidiary, making it unclear which legal entity the
   answer describes.

---

## Assumptions and Trade-offs

- **Only answers with at least one usable source** (`file_url` present) are
  included, as required by the output schema. This reduces coverage but keeps
  the dataset traceable.
- **`data_type` is always `"Metric"`** for this assignment because only
  `value_type=Number` metrics are fetched.
- **`answer` in `reference_output` includes the year** in parentheses
  (e.g. `"55100 (2022)"`) to make the record self-contained even when records
  are viewed in isolation.
- **Unit inference** in `structured_data` is derived from the metric ID suffix
  (`_tCO2e`, `_MWh`, `Women_on_Board` → `%`). A production system would use
  WikiRate's `unit` metadata field directly.
- **Page number extraction** uses simple regex patterns (`page N`, `p. N`,
  `pg. N`). It works for the most common formats found in WikiRate comments but
  will miss non-standard styles.
- A **0.25 s throttle** is applied between API calls to avoid overloading the
  WikiRate server.

---

## What I Would Improve with More Time

1. **Richer metric coverage** – add GRI-standard metrics (water, waste,
   employee health & safety) and cross-reference with SASB/TCFD taxonomies.
2. **Unit normalization layer** – build a lookup table that converts all
   emission values to a canonical unit (tCO2e) before writing structured data.
3. **Incremental / delta fetching** – cache previously fetched answers and only
   pull new or updated records on subsequent runs.
4. **Source validation** – HEAD-request each `file_url` to confirm the document
   is still accessible before including it in the dataset.
5. **Structured logging and error reporting** – replace `print`/`sys.stderr`
   with Python `logging` so verbosity can be configured at runtime.
6. **CLI flags** – allow users to pass a custom metric list, output path, and
   company filter without editing the source code.
7. **Tests** – add unit tests for the transformation logic
   (`transform_answer`, `_extract_page_number`, `_build_structured_data`)
   using recorded API fixtures so CI can run offline.
