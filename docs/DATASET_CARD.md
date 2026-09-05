# Dataset Card — Retailrocket E-Commerce Dataset

**Project:** Production E-Commerce Recommendation Platform
**Repository:** `ecommerce-recsys`
**Document Version:** `v0.1.0`
**Status:** Accepted Primary Dataset
**Date:** 2026-09-05
**Milestone:** Milestone 1 — Dataset Selection and Data Contract

---

## 1. Dataset Overview

* Name: Retailrocket Recommender System Dataset
* Source: Retailrocket (Published on Kaggle)
* License: Creative Commons Attribution-NonCommercial-ShareAlike 4.0 (CC BY-NC-SA 4.0)
* URL: https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset
* Domain: Real-world retail e-commerce behavior
* Time Period: May 3, 2015 to September 18, 2015 (~4.5 months)

---

## 2. File Manifest

The raw dataset contains the following files:

1. `events.csv`
   - Total rows: 2,756,101 interactions
   - Columns: `timestamp`, `visitorid`, `event`, `itemid`, `transactionid`
   - Timestamp format: Unix epoch millisecond

2. `category_tree.csv`
   - Total rows: 1,669 category relationships
   - Columns: `categoryid`, `parentid`

3. `item_properties_part1.csv` & `item_properties_part2.csv`
   - Time-varying item properties snapshots
   - Columns: `timestamp`, `itemid`, `property`, `value`

---

## 3. Alignment with Data Contract

* `user_id`:
  - Mapped to: `visitorid`
  - Status: Satisfies REQUIRED
  - Characteristics: Integer visitor ID representing anonymous visitor session tracking.

* `item_id`:
  - Mapped to: `itemid`
  - Status: Satisfies REQUIRED
  - Characteristics: Integer item ID representing catalog product unit.

* `timestamp`:
  - Mapped to: `timestamp`
  - Status: Satisfies REQUIRED
  - Characteristics: Monotonically comparable Unix milliseconds.
  - Supports leak-free temporal splitting (ADR-004).

* `event_type`:
  - Mapped to: `event`
  - Status: Satisfies CONDITIONALLY REQUIRED
  - Values: `view`, `addtocart`, `transaction`
  - Forms canonical 3-stage implicit behavioral funnel.

* `category`:
  - Mapped to: `categoryid` (via item properties & category tree)
  - Status: Satisfies PREFERRED

---

## 4. Key Metrics and Characteristics

* Total Interactions: ~2.75 million
* Unique Users (`visitorid`): 1,407,580
* Unique Items (`itemid`): 235,061
* Event Distribution:
  - `view`: ~96.7%
  - `addtocart`: ~2.5%
  - `transaction`: ~0.8%
* Approximate Sparsity: > 99.99%

---

## 5. Engineering Trade-offs & Limitations

1. Hashed / Obfuscated Identifiers:
   - Product titles, brands, and category names are hashed or numeric.
   - Trade-off: Ideal for collaborative filtering, neural embeddings,
     and sequential modeling; unsuitable for pure NLP/text descriptions.

2. Extreme Sparsity & Cold Start:
   - High proportion of users with only 1 interaction.
   - Trade-off: Highlights real-world e-commerce challenges (cold-start,
     popularity fallback, and K-core filtering requirements).

3. Fast Iteration Feasibility:
   - File size (~80 MB compressed, ~200 MB uncompressed) fits easily in RAM.
   - Allows rapid model iteration, fast automated testing, and CI validation.
