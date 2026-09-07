# Baseline Benchmark Report

## 1. Overview

This report evaluates the baseline recommendation models for the Production E-Commerce Recommendation Platform.

The purpose of the baseline benchmark is to establish simple and reproducible reference points that future personalized recommendation models must outperform.

The benchmark evaluates six recommendation approaches:

* Random
* Global Popularity
* Recent Popularity
* Category Popularity
* ItemKNN
* Alternating Least Squares (ALS)

The first four models constitute the core simple baselines defined for Task 4. ItemKNN and ALS are included as additional collaborative-filtering reference models to understand how more complex approaches compare against the simple baselines.

All models are evaluated under the same evaluation harness and the same temporal train/test split.

---

## 2. Evaluation Protocol

### 2.1 Dataset

The benchmark uses the following processed datasets:

* Training split: `data/processed/train.parquet`
* Evaluation split: `data/processed/test.parquet`
* Catalog metadata: `data/processed/items.parquet`

Dataset statistics:

| Property              |     Value |
| --------------------- | --------: |
| Training interactions | 2,356,045 |
| Evaluation users      |   200,028 |
| Catalog items         |   235,061 |
| Evaluation targets    |   200,028 |
| K values              | 5, 10, 20 |

Each evaluation user has exactly one held-out target item.

The evaluation users are warm-start users at the user level: all evaluation users have historical interactions in the training split.

The split is temporal, with the held-out evaluation interaction occurring after the interactions used for model fitting. This prevents future interactions from being used to construct the training-time recommendation models.

### 2.2 Metrics

The benchmark evaluates:

* Recall@K
* MRR@K
* NDCG@K
* Catalog Coverage
* Recommendation latency

The implementation currently reports the Recall@K-equivalent metric as `HR@K`.

Because each evaluation user has exactly one positive target item:

`HR@K = Recall@K`

Therefore, HR@K values in the benchmark are interpreted as Recall@K.

Coverage is calculated using the Top-20 recommendation lists, so the reported coverage should be interpreted as Coverage@20.

Latency measures per-user recommendation/inference time only. Model fitting and training time are excluded from latency measurements.

The benchmark records:

* Average latency
* P50 latency
* P95 latency
* P99 latency

### 2.3 Reproducibility

The benchmark uses:

* Random seed: `42`
* Recent popularity window: `30 days`
* Fixed train/test splits
* Fixed model hyperparameters
* Shared evaluation harness

The benchmark artifact is stored at:

`benchmarks/baseline/baseline_v1.json`

---

## 3. Models

### 3.1 Random

The Random recommender samples items from the catalog while maintaining reproducibility through a fixed random seed.

Previously seen items are excluded from the recommendation list.

The purpose of this model is to establish a lower-bound reference for recommendation quality.

### 3.2 Global Popularity

The Global Popularity recommender ranks items by their total number of training interactions and recommends the globally most popular items.

This is a non-personalized baseline.

Its main purpose is to determine how much predictive performance can be obtained without modeling individual user preferences.

### 3.3 Recent Popularity

The Recent Popularity recommender ranks items using interactions occurring within the most recent 30-day window of the training data.

This baseline tests whether recent user activity provides a stronger signal than overall historical popularity.

### 3.4 Category Popularity

The Category Popularity recommender uses the categories of items in the user's interaction history.

It recommends popular items within the user's observed categories and falls back to global popularity when necessary.

This provides a lightweight form of personalization without requiring collaborative filtering or latent-factor models.

### 3.5 ItemKNN

ItemKNN is an item-based collaborative filtering model.

The benchmark configuration uses:

* `n_neighbors = 20`
* `min_item_interactions = 5`

It is included as an additional collaborative-filtering reference rather than as one of the core simple Task 4 baselines.

### 3.6 ALS

ALS is a latent-factor collaborative filtering model.

The benchmark configuration uses:

* Factors: `64`
* Iterations: `20`
* Regularization: `0.01`

ALS is included to provide a latent-factor reference point for comparison with the simpler baselines.

---

## 4. Benchmark Results

### 4.1 Ranking Metrics

The main results are:

| Model               | Recall@5 | Recall@10 | Recall@20 | NDCG@20 |
| ------------------- | -------: | --------: | --------: | ------: |
| Random              |  0.0010% |   0.0020% |   0.0035% | 0.0011% |
| Global Popularity   |  0.3035% |   0.6354% |   1.1438% | 0.4223% |
| Recent Popularity   |  0.3265% |   0.6349% |   0.9799% | 0.3804% |
| Category Popularity |  3.5890% |   5.6902% |   8.5063% | 3.6614% |
| ItemKNN             |  3.1271% |   4.2774% |   5.5662% | 2.8562% |
| ALS                 |  1.5223% |   2.1807% |   3.0636% | 1.4577% |

The strongest model in this benchmark is Category Popularity.

At Recall@20:

* Category Popularity: 8.5063%
* ItemKNN: 5.5662%
* ALS: 3.0636%
* Global Popularity: 1.1438%
* Recent Popularity: 0.9799%
* Random: 0.0035%

---

## 5. Coverage Results

Coverage@20:

| Model               | Coverage@20 |
| ------------------- | ----------: |
| Random              |   100.0000% |
| ItemKNN             |    25.8826% |
| Category Popularity |     8.6173% |
| ALS                 |     1.5119% |
| Global Popularity   |     0.0085% |
| Recent Popularity   |     0.0085% |

Random achieves the highest coverage because it explores the catalog broadly, but its recommendation quality is effectively negligible.

Global and Recent Popularity have extremely low coverage because they recommend the same small set of popular items to many users.

ItemKNN provides a significantly broader recommendation set, covering approximately 25.9% of the catalog.

Category Popularity provides a useful middle ground: it achieves the highest Recall@20 while covering approximately 8.6% of the catalog.

---

## 6. Latency Results

Recommendation latency was measured per user, excluding model fitting/training time.

| Model               | Avg (ms) | P50 (ms) | P95 (ms) | P99 (ms) |
| ------------------- | -------: | -------: | -------: | -------: |
| Global Popularity   | 0.000374 |   0.0003 |   0.0004 |   0.0012 |
| Recent Popularity   | 0.000514 |   0.0004 |   0.0007 |   0.0018 |
| Category Popularity | 0.010005 |   0.0075 |   0.0139 |   0.0271 |
| ItemKNN             | 0.026231 |   0.0117 |   0.0702 | 0.169973 |
| Random              | 0.028585 |   0.0247 |   0.0384 |   0.0657 |
| ALS                 | 3.077617 |   3.0086 |   3.6234 |   4.1909 |

Category Popularity remains extremely inexpensive at inference time despite providing substantially stronger recommendation quality than the non-personalized popularity baselines.

ALS has the highest recommendation latency among the evaluated models.

These latency measurements represent offline recommendation computation only. They should not be interpreted as end-to-end API latency because network, request processing, serialization, model loading, storage access, and other serving overheads are not included.

---

## 7. Key Findings

### 7.1 Category information is a strong signal

The most important finding is that Category Popularity substantially outperforms the non-personalized baselines.

At Recall@20:

* Global Popularity: 1.1438%
* Category Popularity: 8.5063%

Category Popularity therefore achieves approximately 7.4x the Recall@20 of Global Popularity.

This indicates that the user's observed product categories contain a strong predictive signal for the next held-out interaction.

The result is particularly valuable because Category Popularity is substantially simpler than collaborative filtering or latent-factor models.

### 7.2 Recent popularity does not outperform global popularity

The 30-day Recent Popularity baseline achieves Recall@20 of 0.9799%, compared with 1.1438% for Global Popularity.

Therefore, the selected 30-day recency window does not improve performance over global popularity on the current evaluation split.

This should not be interpreted as evidence that recency is universally ineffective. It only shows that the current 30-day configuration does not outperform the global popularity baseline under this evaluation protocol.

### 7.3 A simple personalized heuristic beats the collaborative-filtering references

Category Popularity achieves:

Recall@20 = 8.5063%

compared with:

ItemKNN = 5.5662%

ALS = 3.0636%

Therefore, neither of the evaluated collaborative-filtering references outperforms the lightweight category-based heuristic under the current configuration and evaluation split.

This demonstrates the importance of establishing strong baselines before introducing more complex recommendation models.

### 7.4 ItemKNN provides substantially higher catalog coverage

Although ItemKNN does not achieve the highest Recall@20, it reaches 25.8826% Coverage@20.

This is substantially higher than Category Popularity's 8.6173%.

Therefore, ItemKNN provides a different accuracy/coverage trade-off and may still be useful in a future candidate-generation or hybrid recommendation architecture.

### 7.5 ALS is not competitive under the current configuration

ALS achieves Recall@20 of 3.0636%, which is below both Category Popularity and ItemKNN.

It also has the highest recommendation latency:

P95 = 3.6234 ms

This does not mean ALS is intrinsically unsuitable for recommendation systems. It means that the current configuration does not provide a favorable accuracy/latency trade-off compared with the stronger baselines on this dataset.

---

## 8. Baseline Ranking

Using Recall@20 as the primary ranking metric, the current models rank as follows:

1. Category Popularity — 8.5063%
2. ItemKNN — 5.5662%
3. ALS — 3.0636%
4. Global Popularity — 1.1438%
5. Recent Popularity — 0.9799%
6. Random — 0.0035%

For the core Task 4 baselines specifically:

1. Category Popularity
2. Global Popularity
3. Recent Popularity
4. Random

Category Popularity is therefore the strongest simple baseline that future personalized models should be expected to beat.

---

## 9. Interpretation for Future Models

The benchmark establishes an important performance floor for future recommendation models.

A future model should not be considered successful merely because it improves over Random or Global Popularity.

In particular, a personalized model should demonstrate improvement over Category Popularity, which currently achieves:

Recall@5 = 3.5890%

Recall@10 = 5.6902%

Recall@20 = 8.5063%

NDCG@20 = 3.6614%

and Coverage@20 = 8.6173%.

This baseline is computationally inexpensive and therefore represents a strong practical reference point.

Future collaborative filtering, neural retrieval, learning-to-rank, or sequential recommendation models should be evaluated using the same evaluation harness and temporal evaluation protocol.

Any increase in recommendation quality should also be considered together with catalog coverage and serving latency.

---

## 10. Limitations

Several limitations should be considered when interpreting these results.

First, the evaluation uses one held-out target item per user. This makes Recall@K equivalent to Hit Rate@K, but it does not capture the full ranking quality that would be observed with multiple positive and negative evaluation items.

Second, the benchmark evaluates offline recommendation computation rather than complete production serving latency.

Third, the current Category Popularity model depends on category metadata. Approximately 21.2% of catalog items do not have category metadata, so category-aware recommendation cannot directly use category information for those items.

Fourth, the current benchmark uses a single Recent Popularity window of 30 days. Other temporal windows may produce different results.

Finally, ItemKNN and ALS are evaluated with fixed configurations rather than an exhaustive hyperparameter search. Their results should therefore be interpreted as reference configurations rather than globally optimized model performance.

---

## 11. Reproducibility

The benchmark can be reproduced using the benchmark runner:

`scripts/evaluate_baselines.py`

The frozen benchmark artifact is:

`benchmarks/baseline/baseline_v1.json`

The benchmark uses:

* Training data: `train.parquet`
* Evaluation data: `test.parquet`
* Catalog metadata: `items.parquet`
* K values: 5, 10, 20
* Random seed: 42
* Recent popularity window: 30 days
* Coverage measured at Top-20
* Per-user recommendation latency
* Training/fitting time excluded from latency

The benchmark artifact stores the evaluation protocol, model configurations, and resulting metrics so that future experiments can be compared against the same reference point.

---

## 12. Conclusion

The baseline benchmark successfully establishes reproducible reference points for the recommendation system.

The most important result is that Category Popularity is currently the strongest simple baseline, achieving 8.5063% Recall@20 while maintaining very low recommendation latency.

The benchmark also demonstrates that increasing model complexity does not automatically produce better recommendation quality. Under the current configurations, both ItemKNN and ALS are outperformed by the simpler category-aware heuristic in Recall@20.

Therefore, future recommendation models should be evaluated against Category Popularity rather than only against random or global popularity.

Task 4 baseline benchmarking is considered complete once the benchmark artifact and this report are frozen together with a reproducibility run confirming the same protocol and results.
