# Data Quality and Exploratory Analysis Report

**Project:** Production E-Commerce Recommendation Platform
**Repository:** `ecommerce-recsys`
**Document Version:** `v1.0.1`
**Status:** Accepted
**Date:** 2026-09-05
**Updated:** 2026-10-24 — ingestion validation; dataset statistics unchanged.
**Milestone:** Milestone 2 — Data Quality, EDA, and Interaction Semantics

**Evaluation scope:** The activity distribution below describes the raw dataset. The [rolling benchmark](ROLLING_EVALUATION_PROTOCOL.md) evaluates returning users with at least one earlier interaction and reports first-time users separately.

---

## 1. Executive Summary

This report documents the empirical properties, distributions, and semantic
decisions derived from the raw Retailrocket e-commerce interaction dataset.

Key conclusions:
1. Row-count preservation: Raw and processed interaction counts are both 2,756,101.
2. High cold-start sparsity: 71.15% of visitors have only 1 interaction.
3. User-count ratio: Transaction-user count / view-user count is 0.83%.
4. Repeated interactions: 15.52% of user-item pairs exhibit repeat behavior.
5. Canonical artifacts generated: `interactions.parquet` and `items.parquet`.

---

## 2. Dataset Scale and Invariants

The interaction builder validates raw fields before normalization or output.
Visitor/item IDs must be non-negative signed 64-bit integers; timestamps must
be positive integer milliseconds. Only `view`, `addtocart` and `transaction`
events are accepted. Transaction IDs may be null, otherwise they must be
non-negative signed 64-bit integers. Integer fields are read as text before
validation to preserve precision. Invalid input is rejected before an output
file is created or replaced; valid repeated events are retained.

* Total Interaction Events: 2,756,101
* Unique Users (`user_id`): 1,407,580
* Unique Catalog Items (`item_id`): 235,061
* Temporal Duration: 138.0 days (2015-05-03 to 2015-09-18 UTC)
* Data Completeness:
  - `timestamp`: 0 nulls (100% complete)
  - `visitorid`: 0 nulls (100% complete)
  - `itemid`: 0 nulls (100% complete)
  - `event`: 0 nulls (100% complete)
  - `transactionid`: exactly 22,457 non-nulls matching transaction count.

---

## 3. Behavioral Funnel Analysis

Event counts and proportions:
* `view`: 2,664,312 events (96.67%)
* `addtocart`: 69,332 events (2.52%)
* `transaction`: 22,457 events (0.81%)

User-level behavior counts (over the entire observation period, without enforcing
event order or attributing a purchase to a particular earlier view):
* 1,404,179 unique users viewed at least one item.
* 37,722 unique users have an `addtocart` event (ratio to view-user count: 2.69%).
* 11,719 unique users have a transaction (ratio to view-user count: 0.83%).

The ratios 11,719 / 1,404,179 = 0.83% and 11,719 / 37,722 = 31.07% compare
whole-period user counts. They are not conditional view-to-purchase or
cart-to-purchase conversion rates: the numerators are not restricted to users
with a corresponding earlier view/cart event. The 0.81% transaction-event share
above has a different denominator: 22,457 / 2,756,101 interaction events.

Empirical Rationale (ADR-07):
A purchase event is approximately 120 times rarer than a view event.
Assigning arbitrary static weights (e.g. view=1, purchase=5) fails to reflect
this empirical rarity. Raw event types are therefore preserved unweighted.

---

## 4. User Sparsity and Cold-Start Distribution

* Users with exactly 1 interaction: 1,001,560 (71.15%)
* Users with >= 3 interactions: 200,028 (14.21%)
* Users with >= 5 interactions: 81,620 (5.80%)

Activity Percentiles:
* p25: 1.0 event
* p50 (median): 1.0 event
* p75: 2.0 events
* p90: 3.0 events
* p95: 5.0 events
* p99: 13.0 events

Evaluation implication:
Users with only one event cannot supply both a past interaction and a future target. The rolling benchmark therefore separates returning users from first-time users; popularity-based recommendations provide the measured cold-user fallback. A returning user's eligibility depends on history available at the fold cutoff, not a lifetime threshold of three events.

---

## 5. Item Popularity and Long-Tail Decay

* Top 1% of catalog items (2,350 items) generate 22.95% of all interactions.
* Item Interaction Percentiles:
  - p50: 3.0 interactions
  - p75: 9.0 interactions
  - p90: 25.0 interactions
  - p99: 143.0 interactions
* Category Coverage:
  - 185,246 items (78.8%) have category IDs mapped from catalog properties.

---

## 6. Interaction Semantics and Processing Policy

1. Row-count Preservation:
   Raw and processed interactions both contain 2,756,101 rows.
2. Chronological Ordering:
   Interactions are sorted by `timestamp` in nondecreasing order; events can share a timestamp.
3. Repeat Interaction Preservation:
   Consecutive views are retained to preserve session frequency signals.
4. Output Artifacts:
   - `data/processed/interactions.parquet` (56,456,419 bytes; 53.84 MiB)
   - `data/processed/items.parquet` (5,755,039 bytes; 5.49 MiB)
