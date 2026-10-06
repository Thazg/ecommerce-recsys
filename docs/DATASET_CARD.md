# Dataset Card — Retailrocket E-Commerce Dataset

**Project:** Offline E-Commerce Recommendation System
**Repository:** `ecommerce-recsys`
**Document Version:** `v0.2.1`
**Status:** Accepted Primary Dataset
**Last Updated:** 2026-10-06
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
  - Supports global temporal folds under [ADR-11](DECISIONS.md).

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
   - Trade-off: Supports collaborative and sequential models but does not provide readable text for NLP-based item features.

2. Extreme Sparsity & Cold Start:
   - High proportion of users with only 1 interaction.
   - Trade-off: Highlights real-world e-commerce challenges (cold-start,
     popularity fallback, and K-core filtering requirements).

3. Reproduction cost:
   - The interaction log is manageable locally, while the item-property CSVs and nine-fold model sweeps require substantially more storage and computation.
   - CI covers unit tests and static checks; the full benchmark uses separately obtained raw data and saved, content-hashed artifacts.

## 6. Benchmark input provenance

The [rolling manifest](../benchmarks/rolling/manifest.json) records the input
identities, exact millisecond cutoffs, cohort counts and SHA-256 of every fold
file. The canonical manifest fingerprint is
`5e6a22d5afaca8bc52b1103ad17bed247d9553756945dbbce99981d19bf1f9c3`.

| Input | Recorded SHA-256 |
| :--- | :--- |
| Processed `interactions.parquet` | `5fdbf3e6b8cfdb80fe0aca1066786ac9c6c72326943f988529accfccfaf77a7e` |
| Raw `item_properties_part1.csv` | `30aad5aeca58b2dc27dcc73e1708565f5818e45adb3eb57401f91e87355b0b81` |
| Raw `item_properties_part2.csv` | `d5e7d1a91dc40f522aeb596b267e6c87d8aed689a7192d12369cfb165eb987e5` |

Returning-user targets and first-time-user targets use distinct denominators.
Historical leave-last-out and rolling results use different eligibility rules;
their scores are not interchangeable. See the
[protocol and metric glossary](METRICS_AND_PROTOCOLS.md).

Document revision 0.2.1 clarifies the benchmark provenance and comparison
boundaries. The logical schema is specified by [data contract 0.2.1](DATA_CONTRACT.md).
