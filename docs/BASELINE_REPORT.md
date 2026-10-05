Baseline Benchmark Report

Historical M4 report. Its 200,028-user leave-last-out results use the superseded M3 protocol; see ROLLING_EVALUATION_PROTOCOL.md and the rolling M4–M6 results for current model comparisons.
1. Overview

This report evaluates the baseline recommendation models for the Production E-Commerce Recommendation Platform.

The purpose of the baseline benchmark is to establish simple and reproducible reference points that future personalized recommendation models must outperform.

The benchmark evaluates six recommendation approaches:

Random
Global Popularity
Recent Popularity
Category Popularity
ItemKNN
Alternating Least Squares (ALS)

The first four models constitute the core simple baselines defined for Task 4. ItemKNN and ALS are included as additional collaborative-filtering reference models to understand how more complex approaches compare against the simple baselines.

All models are evaluated under the same evaluation harness and the same temporal train/test split.

The original Task 4 baseline snapshot is preserved separately as benchmarks/baseline/baseline_v1.json. This report reflects the current baseline model configurations, including the support-aware ItemKNN configuration selected during Milestone 5.

2. Evaluation Protocol
2.1 Dataset

The benchmark uses the following processed datasets:

Training split: data/processed/train.parquet
Evaluation split: data/processed/test.parquet
Catalog metadata: data/processed/items.parquet

Dataset statistics:

Property	Value
Total interactions	2,756,101
Training interactions	2,356,045
Evaluation users	200,028
Catalog items	235,061
Evaluation targets	200,028
K values	5, 10, 20

Each evaluation user has exactly one held-out target item.

The evaluation users are warm-start users at the user level: all evaluation users have historical interactions in the training split.

The split is temporal, with the held-out evaluation interaction occurring after the interactions used for model fitting. This prevents future interactions from being used to construct the training-time recommendation models.

2.2 Metrics

The benchmark evaluates:

Recall@K
MRR@K
NDCG@K
Catalog Coverage
Recommendation latency

The implementation currently reports the Recall@K-equivalent metric as HR@K.

Because each evaluation user has exactly one positive target item:

HR@K = Recall@K

Therefore, HR@K values in the benchmark are interpreted as Recall@K.

Coverage is calculated using the Top-20 recommendation lists, so the reported coverage should be interpreted as Coverage@20.

Latency measures per-user recommendation/inference time only. Model fitting and training time are excluded from latency measurements.

The benchmark records:

Average latency
P50 latency
P95 latency
P99 latency
2.3 Reproducibility

The benchmark uses:

Random seed: 42
Recent popularity window: 30 days
Fixed train/test splits
Fixed model hyperparameters
Shared evaluation harness

The frozen Task 4 benchmark artifact is stored at:

benchmarks/baseline/baseline_v1.json

Milestone 5 ItemKNN experiments additionally use a fixed 20,000-user subset with random_state=42 for shrinkage hyperparameter comparison before running the selected configuration on the full evaluation set.

3. Models
3.1 Random

The Random recommender samples items from the catalog while maintaining reproducibility through a fixed random seed.

Previously seen items are excluded from the recommendation list.

The purpose of this model is to establish a lower-bound reference for recommendation quality.

3.2 Global Popularity

The Global Popularity recommender ranks items by their total number of training interactions and recommends the globally most popular items.

This is a non-personalized baseline.

Its main purpose is to determine how much predictive performance can be obtained without modeling individual user preferences.

3.3 Recent Popularity

The Recent Popularity recommender ranks items using interactions occurring within the most recent 30-day window of the training data.

This baseline tests whether recent user activity provides a stronger signal than overall historical popularity.

3.4 Category Popularity

The Category Popularity recommender uses the categories of items in the user's interaction history.

It recommends popular items within the user's observed categories and falls back to global popularity when necessary.

This provides a lightweight form of personalization without requiring collaborative filtering or latent-factor models.

3.5 ItemKNN

ItemKNN is an item-based collaborative filtering model.

The current configuration uses:

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

3.6 ALS

ALS is a latent-factor collaborative filtering model implemented using the implicit library.

The benchmark configuration uses:

Factors: 64
Iterations: 20
Regularization: 0.01

ALS is included to provide a latent-factor reference point for comparison with the simpler baselines and ItemKNN.

The current implementation also uses a popularity fallback for unknown users.

4. Benchmark Results
4.1 Ranking Metrics

The current benchmark results are:

Model	Recall@5	Recall@10	Recall@20	NDCG@20
Random	0.0010%	0.0020%	0.0035%	0.0011%
Global Popularity	0.3035%	0.6354%	1.1438%	0.4223%
Recent Popularity	0.3265%	0.6349%	0.9799%	0.3804%
Category Popularity	3.5890%	5.6902%	8.5063%	3.6614%
ItemKNN	3.5735%	4.8078%	5.8972%	3.1628%
ALS	1.5223%	2.1807%	3.0636%	1.4577%

Source note: the table above is the frozen M4 baseline (`benchmarks/baseline/baseline_v1.json`, ALS factors 64). ItemKNN λ=100 numbers come from `benchmarks/item_knn_final.csv`. The M6 validation-selected ALS final (128/20/0.01, HR@20 ≈ 4.24%) lives separately in `benchmarks/mf/als_final_v1.json` and `docs/MF_EXPERIMENT_REPORT.md`.

At Recall@20, the current ranking is:

Category Popularity: 8.5063%
ItemKNN: 5.8972%
ALS: 3.0636%
Global Popularity: 1.1438%
Recent Popularity: 0.9799%
Random: 0.0035%

Category Popularity remains the strongest model in terms of Recall@20 under the current benchmark configuration.

ItemKNN improved over its raw cosine configuration after introducing support-aware similarity shrinkage.

4.2 ItemKNN Shrinkage Experiment

Milestone 5 evaluated support-aware similarity shrinkage on a fixed 20,000-user evaluation subset.

The main Recall@20 results were:

Lambda	Recall@5	Recall@10	Recall@20
0	3.3100%	4.3650%	5.5400%
5	3.5200%	4.6700%	5.7400%
10	3.5550%	4.7250%	5.7800%
20	3.6200%	4.7700%	5.8450%
50	3.6650%	4.8150%	5.8900%
100	3.7100%	4.8600%	5.9050%
200	3.7050%	4.8600%	5.9150%
500	3.7050%	4.8600%	5.9200%

The sweep indicates that support-aware shrinkage consistently improves the raw similarity configuration.

The largest practical gains occur before the higher lambda values reach a plateau.

On the fixed subset, lambda 100 improved the raw configuration by approximately:

+11.3% Recall@10
+16.8% MRR@10
+14.7% NDCG@10

The final full evaluation confirms the same direction of improvement.

The full evaluation comparison between lambda 0 and lambda 100 is:

Metric	Lambda 0	Lambda 100
Recall@5	3.1296%	3.5735%
Recall@10	4.2799%	4.8078%
Recall@20	5.5712%	5.8972%
MRR@5	1.8422%	2.1286%
MRR@10	1.9947%	2.2939%
MRR@20	2.0843%	2.3698%
NDCG@5	2.1612%	2.4873%
NDCG@10	2.5321%	2.8870%
NDCG@20	2.8586%	3.1628%
Coverage@20	25.8826%	25.6333%

The selected configuration therefore improves ranking quality while maintaining broadly similar catalog coverage.

The small coverage decrease is treated as an acceptable trade-off because the primary objective of the shrinkage experiment was to improve ranking quality rather than maximize exploration.

5. Coverage Results

The current Coverage@20 results are:

Model	Coverage@20
Random	100.0000%
ItemKNN	25.6333%
Category Popularity	8.6173%
ALS	1.5119%
Global Popularity	0.0085%
Recent Popularity	0.0085%

Random achieves the highest coverage because it explores the catalog broadly, but its recommendation quality is effectively negligible.

Global and Recent Popularity have extremely low coverage because they recommend the same small set of popular items to many users.

ItemKNN provides a substantially broader recommendation set, covering approximately 25.6% of the full catalog.

This coverage is calculated against the complete catalog of 235,061 items. ItemKNN indexes 84,077 items during fitting, so its 25.6% recommendation coverage should not be interpreted as coverage of the indexed subset alone.

Category Popularity provides a different accuracy/coverage trade-off: it achieves the highest Recall@20 while covering approximately 8.6% of the catalog.

6. Latency Results

Recommendation latency was measured per user, excluding model fitting/training time.

The current benchmark reports:

Model	Avg (ms)	P50 (ms)	P95 (ms)	P99 (ms)
Global Popularity	0.000374	0.0003	0.0004	0.0012
Recent Popularity	0.000514	0.0004	0.0007	0.0018
Category Popularity	0.010005	0.0075	0.0139	0.0271
ItemKNN	0.044495	0.0211	0.1272	0.306973
Random	0.028585	0.0247	0.0384	0.0657
ALS	3.077617	3.0086	3.6234	4.1909

Category Popularity remains extremely inexpensive at inference time despite providing substantially stronger recommendation quality than the non-personalized popularity baselines.

ItemKNN remains lightweight in per-user recommendation latency even after introducing support-aware similarity adjustment.

ALS has the highest recommendation latency among the evaluated models.

These latency measurements represent offline recommendation computation only. They should not be interpreted as end-to-end API latency because network, request processing, serialization, model loading, storage access, and other serving overheads are not included.

The ItemKNN latency differences between shrinkage configurations are small relative to the overall benchmark and should not be interpreted as a meaningful production latency comparison.

7. Key Findings
7.1 Category information is a strong signal

The most important finding is that Category Popularity substantially outperforms the non-personalized baselines.

At Recall@20:

Global Popularity: 1.1438%
Category Popularity: 8.5063%

Category Popularity therefore achieves approximately 7.4x the Recall@20 of Global Popularity.

This indicates that the user's observed product categories contain a strong predictive signal for the next held-out interaction.

The result is particularly valuable because Category Popularity is substantially simpler than collaborative filtering or latent-factor models.

7.2 Recent popularity does not outperform global popularity

The 30-day Recent Popularity baseline achieves Recall@20 of 0.9799%, compared with 1.1438% for Global Popularity.

Therefore, the selected 30-day recency window does not improve performance over global popularity on the current evaluation split.

This should not be interpreted as evidence that recency is universally ineffective. It only shows that the current 30-day configuration does not outperform the global popularity baseline under this evaluation protocol.

7.3 Support-aware shrinkage improves ItemKNN

Milestone 5 demonstrated that raw cosine similarity can be improved by accounting for the amount of evidence supporting each item-item relationship.

The shrinkage experiment showed consistent improvements in Recall, MRR, and NDCG as lambda increased from zero toward the plateau region.

The final lambda 100 configuration achieved:

Recall@5: 3.5735%
Recall@10: 4.8078%
Recall@20: 5.8972%
NDCG@20: 3.1628%

compared with the raw lambda 0 configuration:

Recall@5: 3.1296%
Recall@10: 4.2799%
Recall@20: 5.5712%
NDCG@20: 2.8586%

Support-aware similarity shrinkage was therefore retained as the final ItemKNN configuration.

Lambda 100 was selected as a representative configuration because performance had already entered a plateau region around larger values. The decision is not based on lambda 100 uniquely maximizing every metric.

7.4 A simple personalized heuristic still beats the collaborative-filtering references

Category Popularity achieves:

Recall@20 = 8.5063%

compared with:

ItemKNN = 5.8972%

ALS = 3.0636%

Therefore, neither of the evaluated collaborative-filtering references outperforms the lightweight category-based heuristic under the current configuration and evaluation split.

This demonstrates the importance of establishing strong baselines before introducing more complex recommendation models.

At the same time, ItemKNN and ALS provide useful reference points for future candidate-generation experiments. Their value should therefore not be judged only by whether they beat the strongest simple baseline on a single ranking metric.

7.5 ItemKNN provides substantially higher catalog coverage

Although ItemKNN does not achieve the highest Recall@20, it reaches 25.6333% Coverage@20.

This is substantially higher than Category Popularity's 8.6173%.

Therefore, ItemKNN provides a different accuracy/coverage trade-off and may be useful in a future candidate-generation or hybrid recommendation architecture.

Its broad recommendation coverage is particularly relevant when future system stages require multiple candidate sources rather than a single final recommender.

7.6 ALS is not competitive under the current configuration

ALS achieves Recall@20 of 3.0636%, which is below both Category Popularity and ItemKNN.

It also has the highest recommendation latency:

P95 = 3.6234 ms

This does not mean ALS is intrinsically unsuitable for recommendation systems.

It means that the current configuration does not provide a favorable accuracy/latency trade-off compared with the stronger baselines on this dataset.

ALS remains valuable as a latent-factor reference and as a model from which future candidate-generation experiments can be designed.

7.7 Recommendation concentration is an important consideration

The M5 analysis also examined how ItemKNN recommendations are distributed across the catalog.

Among 200,028 evaluation users:

195,237 users received recommendations.
16,168 users had no candidates from the ItemKNN recommendation path.
60,840 unique items appeared in recommendation lists.
The top 10 items accounted for approximately 3.72% of all recommendation slots.
The top 100 items accounted for approximately 18.83% of recommendation slots.
The top 1,000 items accounted for approximately 45.75% of recommendation slots.

This shows that ItemKNN provides substantially broader catalog exposure than popularity-based methods, but recommendation traffic is still concentrated among a relatively small subset of items.

This concentration should be monitored in future candidate-generation and re-ranking stages rather than assuming that high catalog coverage automatically implies uniform item exposure.

8. Baseline Ranking

Using Recall@20 as the primary ranking metric, the current models rank as follows:

Category Popularity — 8.5063%
ItemKNN — 5.8972%
ALS — 3.0636%
Global Popularity — 1.1438%
Recent Popularity — 0.9799%
Random — 0.0035%

For the core Task 4 baselines specifically:

Category Popularity
Global Popularity
Recent Popularity
Random

Category Popularity is therefore the strongest simple baseline that future personalized models should be expected to beat.

ItemKNN should be treated separately as a collaborative-filtering candidate-generation reference rather than simply as a replacement for Category Popularity.

9. Interpretation for Future Models

The benchmark establishes an important performance floor for future recommendation models.

A future model should not be considered successful merely because it improves over Random or Global Popularity.

In particular, a personalized model should demonstrate improvement over Category Popularity, which currently achieves:

Recall@5 = 3.5890%

Recall@10 = 5.6902%

Recall@20 = 8.5063%

NDCG@20 = 3.6614%

and Coverage@20 = 8.6173%.

This baseline is computationally inexpensive and therefore represents a strong practical reference point.

At the same time, future candidate-generation systems should not optimize solely for Recall@K. ItemKNN demonstrates that a model can provide a substantially broader candidate distribution even when its top-K ranking metrics are below Category Popularity.

Future collaborative filtering, neural retrieval, learning-to-rank, or sequential recommendation models should therefore be evaluated using the same evaluation harness and temporal evaluation protocol.

Any increase in recommendation quality should also be considered together with:

Ranking quality
Catalog coverage
Recommendation concentration
Cold-start behavior
Inference latency
Model fitting cost
Operational complexity

The benchmark should therefore be treated as a multi-dimensional reference point rather than as a single leaderboard.

10. Limitations

Several limitations should be considered when interpreting these results.

First, the evaluation uses one held-out target item per user. This makes Recall@K equivalent to Hit Rate@K, but it does not capture the full ranking quality that would be observed with multiple positive and negative evaluation items.

Second, the benchmark evaluates offline recommendation computation rather than complete production serving latency.

Third, the current Category Popularity model depends on category metadata. Approximately 21.2% of catalog items do not have category metadata, so category-aware recommendation cannot directly use category information for those items.

Fourth, the current benchmark uses a single Recent Popularity window of 30 days. Other temporal windows may produce different results.

Fifth, ItemKNN and ALS are evaluated with fixed configurations rather than an exhaustive hyperparameter search. Their results should therefore be interpreted as reference configurations rather than globally optimized model performance.

Sixth, the ItemKNN evaluation is warm-start at the user level but has additional item-index coverage constraints. Items below the min_item_interactions threshold are not indexed by ItemKNN, and users whose historical interactions do not map to indexed items may require fallback behavior.

Seventh, recommendation concentration remains present in ItemKNN. High catalog coverage does not imply that recommendation slots are uniformly distributed across all indexed items.

Finally, offline latency numbers should not be treated as production service latency. A production recommendation API would include additional overhead from request handling, serialization, model loading, data access, networking, caching, and other infrastructure components.

11. Reproducibility

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

The benchmark artifact stores the evaluation protocol, model configurations, and resulting metrics so that future experiments can be compared against the same reference point.

The frozen baseline_v1.json artifact should remain unchanged as the historical Task 4 benchmark snapshot. Current M5 results are documented separately through the current model configuration and experiment artifacts.

12. Conclusion

The baseline benchmark establishes reproducible reference points for the recommendation system and provides a performance floor for future model development.

The most important result is that Category Popularity remains the strongest simple baseline, achieving 8.5063% Recall@20 while maintaining very low recommendation latency.

The benchmark also demonstrates that increasing model complexity does not automatically produce better recommendation quality. Under the current configurations, both ItemKNN and ALS are outperformed by the simpler category-aware heuristic in Recall@20.

However, ItemKNN provides a substantially broader recommendation distribution and demonstrates a useful accuracy/coverage trade-off. Milestone 5 further improved ItemKNN through support-aware similarity shrinkage, with lambda 100 selected as the final representative configuration after a reproducible sweep.

The current baseline landscape can therefore be summarized as:

Category Popularity: strongest simple accuracy baseline.
ItemKNN: strongest current collaborative-filtering reference in coverage and ranking quality among the CF models.
ALS: latent-factor reference with higher inference cost and weaker current ranking performance.
Global Popularity: strong simplicity baseline but extremely concentrated.
Recent Popularity: useful recency reference but not stronger than global popularity under the current 30-day configuration.
Random: lower-bound sanity-check baseline.

Future recommendation models should be evaluated against Category Popularity rather than only against Random or Global Popularity.

Future candidate-generation work should also consider ItemKNN and ALS as candidate sources rather than requiring every individual model to outperform Category Popularity as a final recommender.

Task 4 baseline benchmarking and Milestone 5 ItemKNN experimentation are considered complete once the current benchmark report, experiment artifacts, and reproducibility results are frozen together.
