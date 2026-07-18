# Retrieval Method Decision Log
**A real instance of "how do you choose a retrieval method when there's no clean API access?"**

This note documents an actual decision made during this project, not a
hypothetical — useful as direct evidence for that exact interview question.

## The situation
SEC's official XBRL data API (`data.sec.gov/api/xbrl/...`) is the
correct first choice for structured financial data — free, no key
required, machine-readable JSON. It was the first option attempted here.

## What happened
The tool environment available for this project could only fetch URLs
that had already surfaced through a search step — a live JSON API
endpoint, called directly, doesn't satisfy that. Rather than fall back to
guessing values or skipping validation, the retrieval strategy moved down
a deliberate hierarchy:

| Priority | Method | Used here? | Why |
|---|---|---|---|
| 1 | Official structured API (SEC XBRL JSON) | Attempted first | Best option in principle: free, structured, canonical |
| 2 | Official document, fetched directly (10-K HTML/XBRL exhibit on EDGAR) | **Used** | Real, citable, machine-readable enough to parse |
| 3 | Official PDF filing/press release, parsed with custom extraction code | **Used** | Needed for genuine PDF-extraction demonstration; also gives a 3rd independent source for cross-validation |
| 4 | Browser automation / scraping | Not needed | Would only be justified if 1-3 were unavailable, and would require checking SEC's terms of service and rate limits first |
| 5 | Manual entry / paid data provider | Not needed | Reserved for cases with no public disclosure at all |

## The result
Because two fallback methods (2 and 3) were used instead of one, the
project ended up with **three independent sources** for the same fiscal
year's numbers instead of one — which is what made real cross-validation
possible (see `03_Validation/`). What looked like a tooling limitation
turned into a stronger, more defensible dataset.

## The general principle this demonstrates
When the "best" method isn't available, the fallback should still be a
**real, citable, official source** — never an assumption or an estimate.
Every value in this project traces to an exact URL and retrieval
timestamp, regardless of which tier of the hierarchy it came from.
