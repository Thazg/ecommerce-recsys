# Offline Evaluation Protocol

> Archived per-user leave-last-out protocol. It checks ordering within each user but does not enforce a global training cutoff. Use the [rolling evaluation protocol](ROLLING_EVALUATION_PROTOCOL.md) for current model comparisons.

**Project:** Production E-Commerce Recommendation Platform
**Repository:** `ecommerce-recsys`
**Document Version:** `v1.0.0`
**Status:** Superseded by the rolling temporal protocol
**Date:** 2026-09-05
**Milestone:** Milestone 3 — Temporal Split and Offline Evaluation Harness

---

## 1. Core Philosophy: Evaluation First

In accordance with ADR-08 and ADR-09, the evaluation benchmark is established
before training any recommendation models.

Recommendation systems require temporal evaluation:
* Shuffling interactions randomly leaks future behavioral patterns into training.
* Inference in production only has access to historical interactions.
* Evaluation must strictly respect chronological causality.

---

## 2. Temporal Splitting Protocol

### 2.1 User Eligibility
Based on Milestone 2 EDA findings:
* 71.15% of users have only 1 interaction (handled via Popularity Fallback).
* Users with >= 3 interactions (200,028 users) form the personalized evaluation cohort.

### 2.2 Leave-Last-Out Protocol
For each eligible user with chronological interactions [e_1, e_2, ..., e_N] (N >= 3):
* Training set: Earlier interactions [e_1, ..., e_{N-2}]
* Validation set: Second-to-last interaction [e_{N-1}]
* Test set: Last interaction [e_N]

---

## 3. Evaluation Metrics

Recommendations are evaluated at cutoff thresholds K in {5, 10, 20}.

### 3.1 HitRate@K (HR@K)
Binary indicator of whether the ground-truth target item appears in the Top-K list:
* HR@K = 1 if target in Top-K else 0

### 3.2 Mean Reciprocal Rank (MRR@K)
Measures how high the target item ranks within Top-K:
* RR@K = 1 / rank if target in Top-K else 0

### 3.3 Normalized Discounted Cumulative Gain (NDCG@K)
Accounts for position decay using logarithmic discounting:
* DCG@K = 1 / log2(rank + 1) if target in Top-K else 0
* IDCG@K = 1.0 (single ground-truth target)
* NDCG@K = DCG@K / IDCG@K

### 3.4 Catalog Coverage
Measures the diversity of recommendations across the entire catalog:
* Coverage = (Unique items recommended across all users) / (Total catalog items)

---

## 4. Within-user checks and limitations

The historical implementation checks:
1. Strict Timestamp Separation:
   max(train_timestamp) < val_timestamp < test_timestamp for each user.
2. Candidate Independence:
   Test items must never be used to construct user histories during inference.
3. Automated ordering tests:
   Unit tests check the per-user timestamp relationship.

These checks do not prevent the shared training set from containing other users' future events relative to a held-out target. They also do not require the held-out item to be unseen by that user. The rolling protocol adds a global cutoff and unseen-target rule.
