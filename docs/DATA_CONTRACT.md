# E-Commerce Recommendation Data Contract

**Project:** Offline E-Commerce Recommendation System
**Repository:** `ecommerce-recsys`
**Contract Version:** `v0.2.1`
**Status:** Accepted logical data contract
**Last Updated:** 2026-10-06

---

## 1. Purpose of This Contract

This document defines the canonical logical data contract for the offline
recommendation experiments in this repository.

In alignment with ADR-06, this contract specifies the minimum required
properties and semantics that any candidate dataset must fulfill.

It serves as:
1. Acceptance criteria for the selected dataset and future data sources.
2. The logical baseline for schemas in `src/ecommerce_recsys/data/schemas.py`.
3. The contract for processing interactions without silent data loss.

---

## 2. Core Logical Entities

### 2.1 User Entity
Represents an individual browsing or purchasing entity.

* Identifier: `user_id` (String / Categorical)
* Requirements:
  - Must uniquely identify a persistent entity across sessions.
  - Must support longitudinal interaction history over time.
  - Must NOT require real customer PII (name, email, phone, address).
* Constraints:
  - `session_id` must NOT be treated as `user_id` without explicit analysis.

### 2.2 Item Entity
Represents a recommendable catalog unit (product).

* Identifier: `item_id` (String / Categorical)
* Requirements:
  - Must uniquely identify a stable product in the catalog.
* Constraints:
  - Distinctions among product ID, variant ID, and SKU must be verified.
* Preferred Metadata (Non-blocking):
  - `category_id` / category path
  - `brand`
  - `price`
  - `title` / text description

### 2.3 Interaction Entity
Represents an atomic behavioral event between User and Item.

* Required Attributes:
  - `user_id`: Reference to user.
  - `item_id`: Reference to item.
  - `timestamp`: Precise temporal marker (ISO 8601 or Unix epoch).
* Conditionally Required:
  - `event_type`: Required for multiple logged event types; canonical values are
    `view`, `addtocart` and `transaction` (view, cart addition and purchase).

---

## 3. Mandatory Behavioral Invariants

### 3.1 Strict Temporal Ordering (Required)
* Follows [ADR-11](DECISIONS.md) for global temporal evaluation.
* Every interaction must contain a recoverable, monotonically comparable timestamp.
* Required to construct globally ordered evaluation folds and model recency.
* Training events satisfy `timestamp <= cutoff`; evaluation targets satisfy
  `timestamp > cutoff`. Recency windows and metadata snapshots use that declared
  cutoff, including gaps after the final observed training event.
* Candidate item IDs must be observed in the training snapshot. Category values
  must come from property events at or before the same cutoff.

### 3.2 Preservation of Raw Repeated Interactions (Required)
* Raw ingestion must NOT deduplicate repeated interactions prior to EDA.
* Repeated events carry frequency signals or tracking artifacts that
  require empirical analysis before filtering or merging (ADR-07).

### 3.3 Implicit-Feedback Interpretation
* Follows ADR-01.
* Interactions represent observed positive interest/engagement.
* Absence of interaction does NOT indicate negative preference.

---

## 4. Contract Specification Matrix

* `user_id`:
  - Entity: User / Interaction
  - Requirement: REQUIRED
  - Purpose: History attribution & personalized scoring.
  - Missing Impact: Cannot perform personalized recommendations.

* `item_id`:
  - Entity: Item / Interaction
  - Requirement: REQUIRED
  - Purpose: Item identification & catalog indexing.
  - Missing Impact: Cannot generate or rank recommendations.

* `timestamp`:
  - Entity: Interaction
  - Requirement: REQUIRED
  - Purpose: Temporal evaluation split & chronological ordering.
  - Missing Impact: Prevents causal temporal evaluation under ADR-11.

* `event_type`:
  - Entity: Interaction
  - Requirement: CONDITIONALLY REQUIRED (if multi-event dataset)
  - Purpose: Multi-task scoring or funnel stages (view, cart, purchase).
  - Missing Impact: Collapses all signals into single generic interaction.

* `session_id`:
  - Entity: Interaction context
  - Requirement: OPTIONAL
  - Purpose: Session boundary detection & sequential modeling.

* `category`, `brand`, `price`:
  - Entity: Item Metadata
  - Requirement: PREFERRED
  - Purpose: Filtering, diversity metrics, business rules, cold-start.

* `PII` (Name, Email, Phone):
  - Requirement: FORBIDDEN / NOT REQUIRED
  - Purpose: None. Avoids privacy and legal constraints.

---

## 5. Deliberately Unresolved Semantics

To maintain architectural discipline (ADR-07, ADR-03), the following
are intentionally left UNRESOLVED in this contract:

1. Event Weighting Ratios (e.g. view=1, purchase=5).
2. Positive Interaction Thresholds for metric evaluation.
3. Duplicate Event Policy (aggregate vs drop).
4. User/Item Activity Thresholds (e.g. 5-core filtering).
5. Negative Sampling Strategy (uniform vs popularity-biased).

---

## 6. Reproducibility & Provenance Requirements

Candidate datasets must fulfill:
* Public Accessibility: Documented public URL or official API.
* Deterministic Versioning: Date, version tag, or checksum (SHA-256).
* Licensing: Open-source or academic research usage license.
* Download Script: Able to be downloaded via `scripts/download_data.py`.
