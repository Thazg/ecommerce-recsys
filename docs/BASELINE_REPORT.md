# Historical baseline benchmark (per-user leave-last-out)

> This report documents the original M4–M5 evaluation. Its per-user split does not enforce a global training cutoff. Use the [rolling benchmark](ROLLING_BENCHMARK_REPORT.md) for current cross-model comparisons.

**Metric units:** Accuracy and coverage are fractions in `[0, 1]`. Historical
leave-last-out scores are not comparable with rolling scores. See
[metrics, protocols and model references](METRICS_AND_PROTOCOLS.md).

## 1. Overview

This report evaluates the baseline recommendation models for the Production E-Commerce Recommendation Platform.

The report preserves the original baseline comparison and its model trade-offs. Model selection for subsequent work uses the rolling temporal benchmark.

The benchmark evaluates six recommendation approaches:

- Random
- Global Popularity
- Recent Popularity
- Category Popularity
- ItemKNN
- Alternating Least Squares (ALS)

The first four models constitute the core simple baselines defined for Task 4. ItemKNN and ALS are included as additional collaborative-filtering reference models to understand how more complex approaches compare against the simple baselines.

Models in this historical comparison share the per-user leave-last-out split.
Rolling and M7 retrieval use separate protocols and are excluded from this table.

The original M4 snapshot is preserved in [`baseline_v1.json`](../benchmarks/baseline/baseline_v1.json). This report also includes the support-aware ItemKNN configuration evaluated during M5.

## 2. Evaluation Protocol

### 2.1 Dataset

The benchmark uses the following processed datasets:

- Training split: data/processed/train.parquet
- Evaluation split: data/processed/test.parquet
- Catalog metadata: data/processed/items.parquet

Dataset statistics:

| Property | Value |
| :--- | ---: |
| Total interactions | 2,756,101 |
| Training interactions | 2,356,045 |
| Evaluation users | 200,028 |
| Catalog items | 235,061 |
| Evaluation targets | 200,028 |
| K values | 5, 10, 20 |

Each evaluation user has exactly one held-out target item.

The evaluation users are warm-start users at the user level: all evaluation users have historical interactions in the training split.

The held-out interaction follows that user's earlier interactions. The shared model-training set is not globally earlier than every target, so this split cannot estimate future-facing performance without cross-user temporal leakage.

### 2.2 Metrics

The benchmark evaluates:

- Recall@K
- MRR@K
- NDCG@K
- Catalog Coverage
- Recommendation latency

The implementation currently reports the Recall@K-equivalent metric as HR@K.

Because each evaluation user has exactly one positive target item:

HR@K = Recall@K

Therefore, HR@K values in the benchmark are interpreted as Recall@K.

Coverage is calculated using the Top-20 recommendation lists, so the reported coverage should be interpreted as Coverage@20.

Latency measures per-user recommendation/inference time only. Model fitting and training time are excluded from latency measurements.

The benchmark records:

- Average latency
- P50 latency
- P95 latency
- P99 latency

### 2.3 Reproducibility

The benchmark uses:

- Random seed: 42
- Recent popularity window: 30 days
- Fixed train/test splits
- Fixed model hyperparameters
- Shared evaluation harness

The frozen Task 4 benchmark artifact is stored at:

benchmarks/baseline/baseline_v1.json

Milestone 5 ItemKNN experiments additionally use a fixed 20,000-user subset with random_state=42 for shrinkage hyperparameter comparison before running the selected configuration on the full evaluation set.

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

The standalone M4 Category recommender traverses the history categories and
backfills from global popularity. The M7 Category source pools category counts
and returns no global backfill; its behavior is documented separately.

This provides a lightweight form of personalization without requiring collaborative filtering or latent-factor models.

### 3.5 ItemKNN

ItemKNN is an item-based collaborative filtering model.

The historical M5 configuration shown here uses:

n_neighbors = 20
min_item_interactions = 5
shrinkage_lambda = 100

The model indexes items with sufficient interaction support and computes item-item similarity using cosine similarity.

Milestone 5 introduced support-aware similarity shrinkage. The adjusted similarity is:

adjusted_similarity = similarity × support / (support + lambda)

where support represents the number of users contributing to the item-item co-occurrence.

The shrinkage reduces the influence of similarities supported by very few interactions while preserving stronger similarities with larger support.

The shrinkage parameter was evaluated using:

lambda ∈ {0, 5, 10, 20, 50, 100, 200, 500}

The results showed a clear improvement over the raw similarity configuration and a performance plateau at larger lambda values.

Lambda 100 was selected as the representative final configuration because it provided strong performance while avoiding unnecessary complexity from selecting a larger value whose improvement over the plateau was negligible.

ItemKNN is included as an additional collaborative-filtering reference and is also an important candidate for future candidate-generation experiments because of its substantially broader catalog coverage.

### 3.6 ALS

ALS is a latent-factor collaborative filtering model implemented using the implicit library.

The benchmark configuration uses:

Factors: 64
Iterations: 20
Regularization: 0.01

ALS is included to provide a latent-factor reference point for comparison with the simpler baselines and ItemKNN.

The standalone ALS recommender uses a popularity fallback for unknown users.
The M7 direct ALS source returns an empty list for unknown users; the hybrid
attributes fallback products to explicit popularity sources.

## 4. Benchmark Results

### 4.1 Ranking Metrics

The historical evaluation results are:

| Model | Recall@5 | Recall@10 | Recall@20 | NDCG@20 |
| :--- | ---: | ---: | ---: | ---: |
| Random | 0.000010 | 0.000020 | 0.000035 | 0.000011 |
| Global Popularity | 0.003035 | 0.006354 | 0.011438 | 0.004223 |
| Recent Popularity | 0.003265 | 0.006349 | 0.009799 | 0.003804 |
| Category Popularity | 0.035890 | 0.056902 | 0.085063 | 0.036614 |
| ItemKNN | 0.035735 | 0.048078 | 0.058972 | 0.031628 |
| ALS | 0.015223 | 0.021807 | 0.030636 | 0.014577 |

The fixed M4 baseline is in [`baseline_v1.json`](../benchmarks/baseline/baseline_v1.json) (ALS with 64 factors). ItemKNN λ=100 values were produced by `scripts/benchmark_item_knn_final.py`; its CSV output is generated locally. The later M6 ALS result is in [`als_final_v1.json`](../benchmarks/mf/als_final_v1.json) and the [MF experiment report](MF_EXPERIMENT_REPORT.md).

At Recall@20, these historical results rank as follows:

Category Popularity: 0.085063
ItemKNN: 0.058972
ALS: 0.030636
Global Popularity: 0.011438
Recent Popularity: 0.009799
Random: 0.000035

Category Popularity had the highest Recall@20 in this historical comparison.

ItemKNN improved over its raw cosine configuration after introducing support-aware similarity shrinkage.

### 4.2 ItemKNN Shrinkage Experiment

Milestone 5 evaluated support-aware similarity shrinkage on a fixed 20,000-user evaluation subset.

The main Recall@20 results were:

| Lambda | Recall@5 | Recall@10 | Recall@20 |
| :--- | ---: | ---: | ---: |
| 0 | 0.033100 | 0.043650 | 0.055400 |
| 5 | 0.035200 | 0.046700 | 0.057400 |
| 10 | 0.035550 | 0.047250 | 0.057800 |
| 20 | 0.036200 | 0.047700 | 0.058450 |
| 50 | 0.036650 | 0.048150 | 0.058900 |
| 100 | 0.037100 | 0.048600 | 0.059050 |
| 200 | 0.037050 | 0.048600 | 0.059150 |
| 500 | 0.037050 | 0.048600 | 0.059200 |

The sweep indicates that support-aware shrinkage consistently improves the raw similarity configuration.

The largest practical gains occur before the higher lambda values reach a plateau.

On the fixed subset, lambda 100 has the following approximate relative changes:

- +11.3% Recall@10
- +16.8% MRR@10
- +14.7% NDCG@10

The final full evaluation confirms the same direction of improvement.

The full evaluation comparison between lambda 0 and lambda 100 is:

| Metric | Lambda 0 | Lambda 100 |
| :--- | ---: | ---: |
| Recall@5 | 0.031296 | 0.035735 |
| Recall@10 | 0.042799 | 0.048078 |
| Recall@20 | 0.055712 | 0.058972 |
| MRR@5 | 0.018422 | 0.021286 |
| MRR@10 | 0.019947 | 0.022939 |
| MRR@20 | 0.020843 | 0.023698 |
| NDCG@5 | 0.021612 | 0.024873 |
| NDCG@10 | 0.025321 | 0.028870 |
| NDCG@20 | 0.028586 | 0.031628 |
| Coverage@20 | 0.258826 | 0.256333 |

The selected configuration therefore improves ranking quality while maintaining broadly similar catalog coverage.

The small coverage decrease is treated as an acceptable trade-off because the primary objective of the shrinkage experiment was to improve ranking quality rather than maximize exploration.

## 5. Coverage Results

The historical Coverage@20 results are:

| Model | Coverage@20 |
| :--- | ---: |
| Random | 1.000000 |
| ItemKNN | 0.256333 |
| Category Popularity | 0.086173 |
| ALS | 0.015119 |
| Global Popularity | 0.000085 |
| Recent Popularity | 0.000085 |

Random achieves the highest coverage because it explores the catalog broadly, but its recommendation quality is effectively negligible.

Global and Recent Popularity have extremely low coverage because they recommend the same small set of popular items to many users.

ItemKNN provides a substantially broader recommendation set, covering approximately 0.256000 of the full catalog.

This coverage is calculated against the complete catalog of 235,061 items. ItemKNN indexes 84,077 items during fitting, so its 0.256000 recommendation coverage should not be interpreted as coverage of the indexed subset alone.

Category Popularity provides a different accuracy/coverage trade-off: it achieves the highest Recall@20 while covering approximately 0.086000 of the catalog.

## 6. Latency Results

Recommendation latency was measured per user, excluding model fitting/training time.

The historical benchmark reports:

| Model | Avg (ms) | P50 (ms) | P95 (ms) | P99 (ms) |
| :--- | ---: | ---: | ---: | ---: |
| Global Popularity | 0.000374 | 0.0003 | 0.0004 | 0.0012 |
| Recent Popularity | 0.000514 | 0.0004 | 0.0007 | 0.0018 |
| Category Popularity | 0.010005 | 0.0075 | 0.0139 | 0.0271 |
| ItemKNN | 0.044495 | 0.0211 | 0.1272 | 0.306973 |
| Random | 0.028585 | 0.0247 | 0.0384 | 0.0657 |
| ALS | 3.077617 | 3.0086 | 3.6234 | 4.1909 |

Category Popularity remains extremely inexpensive at inference time despite providing substantially stronger recommendation quality than the non-personalized popularity baselines.

ItemKNN remains lightweight in per-user recommendation latency even after introducing support-aware similarity adjustment.

ALS has the highest recommendation latency among the evaluated models.

These latency measurements represent offline recommendation computation only. They should not be interpreted as end-to-end API latency because network, request processing, serialization, model loading, storage access, and other serving overheads are not included.

The ItemKNN latency differences between shrinkage configurations are small relative to the overall benchmark and should not be interpreted as a meaningful production latency comparison.

## 7. Key Findings

### 7.1 Category information is a strong signal

The most important finding is that Category Popularity substantially outperforms the non-personalized baselines.

At Recall@20:

Global Popularity: 0.011438
Category Popularity: 0.085063

Category Popularity therefore achieves approximately 7.4x the Recall@20 of Global Popularity.

This indicates that the user's observed product categories contain a strong predictive signal for the next held-out interaction.

The result is particularly valuable because Category Popularity is substantially simpler than collaborative filtering or latent-factor models.

### 7.2 Recent popularity does not outperform global popularity

The 30-day Recent Popularity baseline achieves Recall@20 of 0.009799, compared with 0.011438 for Global Popularity.

Therefore, the selected 30-day recency window does not improve performance over global popularity on this historical evaluation split.

This should not be interpreted as evidence that recency is universally ineffective. It only shows that this historical 30-day configuration does not outperform the global popularity baseline under this evaluation protocol.

### 7.3 Support-aware shrinkage improves ItemKNN

Milestone 5 demonstrated that raw cosine similarity can be improved by accounting for the amount of evidence supporting each item-item relationship.

The shrinkage experiment showed consistent improvements in Recall, MRR, and NDCG as lambda increased from zero toward the plateau region.

The final lambda 100 configuration achieved:

Recall@5: 0.035735
Recall@10: 0.048078
Recall@20: 0.058972
NDCG@20: 0.031628

compared with the raw lambda 0 configuration:

Recall@5: 0.031296
Recall@10: 0.042799
Recall@20: 0.055712
NDCG@20: 0.028586

Support-aware similarity shrinkage was therefore retained as the final ItemKNN configuration.

Lambda 100 was selected as a representative configuration because performance had already entered a plateau region around larger values. The decision is not based on lambda 100 uniquely maximizing every metric.

### 7.4 A simple personalized heuristic still beats the collaborative-filtering references

Category Popularity achieves:

Recall@20 = 0.085063

compared with:

ItemKNN = 0.058972

ALS = 0.030636

Therefore, neither of the evaluated collaborative-filtering references outperforms the lightweight category-based heuristic under these historical configurations and this evaluation split.

This demonstrates the importance of establishing strong baselines before introducing more complex recommendation models.

At the same time, ItemKNN and ALS provide useful reference points for future candidate-generation experiments. Their value should therefore not be judged only by whether they beat the strongest simple baseline on a single ranking metric.

### 7.5 ItemKNN provides substantially higher catalog coverage

Although ItemKNN does not achieve the highest Recall@20, it reaches 0.256333 Coverage@20.

This is substantially higher than Category Popularity's 0.086173.

Therefore, ItemKNN provides a different accuracy/coverage trade-off and may be useful in a future candidate-generation or hybrid recommendation architecture.

Its broad recommendation coverage is particularly relevant when future system stages require multiple candidate sources rather than a single final recommender.

### 7.6 ALS trade-offs in the historical baseline

ALS achieves Recall@20 of 0.030636, which is below both Category Popularity and ItemKNN.

It also has the highest recommendation latency:

P95 = 3.6234 ms

This does not mean ALS is intrinsically unsuitable for recommendation systems.

It means that this historical configuration does not provide a favorable accuracy/latency trade-off compared with the stronger baselines on this dataset.

ALS remains valuable as a latent-factor reference and as a model from which future candidate-generation experiments can be designed.

### 7.7 Recommendation concentration is an important consideration

The M5 analysis also examined how ItemKNN recommendations are distributed across the catalog.

The historical raw-neighbor distribution analysis (lambda 0) reported 195,237
nonempty recommendation requests among 200,028 users and 60,840 unique output
items, corresponding to Coverage@20 of 0.258826. This is distinct from the
selected lambda-100 coverage above. The archived ItemKNN artifact separately
records 16,168 `cold_start_users`; this diagnostic field is not an empty-output
count, because standalone popularity fallback can supply recommendations.
The top 10 items accounted for approximately 3.72% of all recommendation slots.
The top 100 items accounted for approximately 18.83% of recommendation slots.
The top 1,000 items accounted for approximately 45.75% of recommendation slots.

This shows that ItemKNN provides substantially broader catalog exposure than popularity-based methods, but recommendation traffic is still concentrated among a relatively small subset of items.

This concentration should be monitored in future candidate-generation and re-ranking stages rather than assuming that high catalog coverage automatically implies uniform item exposure.

## 8. Historical model ranking

The table uses Recall@20 under the archived leave-last-out protocol. ItemKNN
uses the M5 shrinkage configuration; ALS is the M4 baseline with 64 factors and
20 iterations.

| Model | Historical Recall@20 |
| :--- | ---: |
| Category Popularity | 0.085063 |
| ItemKNN | 0.058972 |
| ALS | 0.030636 |
| Global Popularity | 0.011438 |
| Recent Popularity | 0.009799 |
| Random | 0.000035 |

## 9. Interpretation

Category Popularity provides a strong accuracy reference within this historical
comparison. Its score does not set a performance threshold for the rolling task,
which has different targets, eligibility rules and training boundaries.

ItemKNN's broader recommendation distribution motivates measuring it as a
candidate source. Historical Top-20 metrics alone do not establish Candidate
Recall@100/500/1000; that stage is measured in the
[candidate retrieval report](CANDIDATE_RETRIEVAL_REPORT.md).

Model comparisons require a shared protocol and should consider ranking quality,
catalog coverage, recommendation concentration, cold-start behavior, inference
latency, fitting cost and operational complexity together.

## 10. Limitations

These historical results have important limits:

The split checks ordering within each user but does not impose a global training cutoff. Events from other users can occur after a target, and 86,949 of the 200,028 targets were already in their users' training histories. The [rolling benchmark](ROLLING_BENCHMARK_REPORT.md) addresses both issues; its scores must not be compared numerically with this table.

First, the evaluation uses one held-out target item per user. This makes Recall@K equivalent to Hit Rate@K, but it does not capture the full ranking quality that would be observed with multiple positive and negative evaluation items.

Second, the benchmark evaluates offline recommendation computation rather than complete production serving latency.

Third, the current Category Popularity model depends on category metadata. Approximately 21.2% of catalog items do not have category metadata, so category-aware recommendation cannot directly use category information for those items.

Fourth, this evaluation used a single Recent Popularity window of 30 days. Other temporal windows may produce different results.

Fifth, ItemKNN and ALS are evaluated with fixed configurations rather than an exhaustive hyperparameter search. Their results should therefore be interpreted as reference configurations rather than globally optimized model performance.

Sixth, the ItemKNN evaluation is warm-start at the user level but has additional item-index coverage constraints. Items below the min_item_interactions threshold are not indexed by ItemKNN, and users whose historical interactions do not map to indexed items may require fallback behavior.

Seventh, recommendation concentration remains present in ItemKNN. High catalog coverage does not imply that recommendation slots are uniformly distributed across all indexed items.

Finally, offline latency numbers should not be treated as production service latency. A production recommendation API would include additional overhead from request handling, serialization, model loading, data access, networking, caching, and other infrastructure components.

## 11. Reproducibility

The baseline benchmark can be reproduced using the benchmark runner:

scripts/benchmark_baselines.py

The frozen Task 4 benchmark artifact is:

benchmarks/baseline/baseline_v1.json

The benchmark uses:

Training data: train.parquet
Evaluation data: test.parquet
Catalog metadata: items.parquet
K values: 5, 10, 20
Random seed: 42
Recent popularity window: 30 days
Coverage measured at Top-20
Per-user recommendation latency
Training/fitting time excluded from latency

Milestone 5 ItemKNN experiments can additionally be reproduced using:

scripts/benchmark_item_knn_shrinkage.py

The shrinkage sweep artifact is:

benchmarks/item_knn_shrinkage_sweep.csv

The final ItemKNN comparison can be reproduced using:

scripts/benchmark_item_knn_final.py

The M5 analysis tooling includes:

scripts/analyze_item_knn_empty_users.py
scripts/analyze_recommendation_concentration.py
scripts/analyze_recommendation_distribution.py

The benchmark artifact records the original protocol, model configurations, and metrics for provenance.

The original `baseline_v1.json` artifact remains unchanged. M5 ItemKNN results are documented in the tables above and can be reproduced with the listed scripts.

## 12. Conclusion

This report records the original model comparison and the ItemKNN shrinkage study. It is not a performance floor for the current rolling task.

In this historical comparison, Category Popularity is the strongest simple baseline, achieving 0.085063 Recall@20 while maintaining very low recommendation latency.

The benchmark also demonstrates that increasing model complexity does not automatically produce better recommendation quality. Under these historical configurations, both ItemKNN and ALS are outperformed by the simpler category-aware heuristic in Recall@20.

However, ItemKNN provides a substantially broader recommendation distribution and demonstrates a useful accuracy/coverage trade-off. Milestone 5 further improved ItemKNN through support-aware similarity shrinkage, with lambda 100 selected as the final representative configuration after a reproducible sweep.

The historical model trade-offs can be summarized as:

Category Popularity: strongest simple accuracy baseline.
ItemKNN: broader coverage and stronger ranking quality than ALS in this historical comparison.
ALS: historical latent-factor reference with higher inference cost and weaker ranking performance.
Global Popularity: strong simplicity baseline but extremely concentrated.
Recent Popularity: useful recency reference but not stronger than global popularity under this historical 30-day configuration.
Random: lower-bound sanity-check baseline.

Current model comparisons use the shared rolling cohort in the [rolling benchmark report](ROLLING_BENCHMARK_REPORT.md). The historical accuracy and coverage patterns here motivate candidate-source experiments, but they do not establish a winner under the current protocol.
