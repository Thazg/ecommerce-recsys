# Data Quality and Exploratory Analysis Report

**Project:** Production E-Commerce Recommendation Platform
**Repository:** `ecommerce-recsys`
**Document Version:** `v1.0.0`
**Status:** Accepted
**Date:** 2026-09-05
**Milestone:** Milestone 2 — Data Quality, EDA, and Interaction Semantics

**Historical note (2026-10-05):** The `>= 3 events` implication below belongs to the original per-user leave-last-out design. The current rolling M4–M6 benchmark evaluates warm users with at least one earlier interaction and reports first-time users separately; see [ROLLING_EVALUATION_PROTOCOL.md](ROLLING_EVALUATION_PROTOCOL.md).

---

## 1. Executive Summary

This report documents the empirical properties, distributions, and semantic
decisions derived from the raw Retailrocket e-commerce interaction dataset.

Key conclusions:
1. Zero data loss: All 2,756,101 raw interactions are preserved.
2. High cold-start sparsity: 71.15% of visitors have only 1 interaction.
3. Steep behavioral funnel: Conversion from view to purchase is 0.83%.
4. Repeated interactions: 15.52% of user-item pairs exhibit repeat behavior.
5. Canonical artifacts generated: `interactions.parquet` and `items.parquet`.

---

## 2. Dataset Scale and Invariants

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

User-level funnel progression:
* 1,404,179 unique users viewed at least one item.
* 37,722 unique users added at least one item to cart (2.69% of viewers).
* 11,719 unique users completed a purchase (0.83% of viewers, 31.07% of carters).

Empirical Rationale (ADR-002):
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

Architectural Implication:
Users with only 1 interaction cannot support temporal personalized evaluation
(train on past, evaluate on future). The serving architecture must employ a
two-tier strategy:
1. Personalized Collaborative Filtering for users with history (>= 3 events).
2. Popularity / Trending Fallback for anonymous or 1-event cold-start visitors.

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

1. Zero Silent Deletion:
   No rows are discarded during the processing stage.
2. Chronological Ordering:
   Interactions are sorted strictly by `timestamp` ascending.
3. Repeat Interaction Preservation:
   Consecutive views are retained to preserve session frequency signals.
4. Output Artifacts:
   - `data/processed/interactions.parquet` (53.84 MB)
   - `data/processed/items.parquet` (5.49 MB)
