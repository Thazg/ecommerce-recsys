# Matrix Factorization Experiment Report

> Historical M6 report. Its per-user leave-last-out split lacks a global training cutoff and may include already-seen targets. Use the [rolling benchmark report](ROLLING_BENCHMARK_REPORT.md) for current ALS comparisons and sweep results.

**Metric units:** Accuracy and coverage are fractions in `[0, 1]`; factor
arrays are measured in MiB. Configuration labels and protocol boundaries are
listed in [metrics and model references](METRICS_AND_PROTOCOLS.md).

## 1. Objective

This milestone evaluates matrix factorization methods for implicit-feedback recommendation and establishes whether a latent-factor model is useful for the production-oriented e-commerce recommendation system.

The milestone has three complementary objectives:

1. Understand the mechanics of latent-factor recommendation through a small educational implementation.
2. Compare pointwise matrix factorization with pairwise Bayesian Personalized Ranking (BPR).
3. Evaluate the existing production-oriented implicit ALS implementation on the project's temporal validation and test splits.

The project deliberately separates educational implementations from the library-backed recommender. The educational models prioritize readability and understanding, while the ALS implementation uses the `implicit` library for scalable model training.

This historical M6 selection uses the validation split, followed by a run of
the selected model on the historical test split. Earlier baseline experiments
had already used that test population; it is not an untouched confirmation set.

---

## 2. Dataset and Evaluation Protocol

The recommendation system uses implicit e-commerce interactions containing events such as views, cart additions, and transactions.

The archived evaluation protocol orders interactions within each user, but the shared training set is not globally earlier than every validation or test target. These results document the original experiment rather than prospective ranking performance.

### Dataset statistics

| Split / Quantity      |         Value |
| --------------------- | ------------: |
| Training interactions |     2,356,045 |
| Validation users      |       200,028 |
| Test users            |       200,028 |
| Catalog size          | 235,061 items |
| Evaluation K values   |     5, 10, 20 |
| Random seed           |            42 |

The training split is stored in:

```text
data/processed/train.parquet
```

Validation:

```text
data/processed/val.parquet
```

Test:

```text
data/processed/test.parquet
```

The evaluation harness measures:

* HR@K
* MRR@K
* NDCG@K
* catalog coverage
* average recommendation latency
* latency p50
* latency p95
* latency p99

Latency measures per-user recommendation latency and excludes model fitting/training time.

Because the evaluation protocol contains one held-out target item per evaluation user, HR@K is equivalent to hit rate / recall@K under this evaluation setup.

---

## 3. Implicit Feedback Formulation

The dataset contains behavioral observations rather than explicit ratings.

An interaction such as a view, cart addition, or transaction provides evidence that a user interacted with an item. However, the absence of an interaction does not directly imply that the user dislikes the item.

Therefore:

```text
observed interaction
        ≠
explicit positive rating
```

and:

```text
unobserved interaction
        ≠
explicit negative feedback
```

This distinction is fundamental to the matrix-factorization experiments.

For the current library-backed ALS implementation, every observed interaction is encoded with value `1.0` in the sparse user-item matrix:

```text
view        → 1.0
addtocart   → 1.0
transaction → 1.0
```

Thus the current ALS baseline does not distinguish event types through different interaction weights.

Future event-specific confidence weighting could be evaluated, but it is intentionally outside the current M6 experiment scope.

---

## 4. Educational Matrix Factorization

### 4.1 Model

The educational matrix factorization implementation is located at:

```text
src/ecommerce_recsys/recommendation/matrix_factorization_educational.py
```

It implements a small latent-factor model using NumPy and stochastic gradient descent.

Each user and item is represented by a latent vector:

```text
p_u ∈ R^f
q_i ∈ R^f
```

The predicted preference score is:

```text
s(u, i) = p_u^T q_i
```

where:

* `p_u` is the latent vector for user `u`
* `q_i` is the latent vector for item `i`
* `f` is the latent factor dimension

The dot product produces a scalar compatibility score between the user and item representations.

### 4.2 Training Objective

The educational MF implementation uses sampled pointwise observations.

The target is represented as:

```text
y ∈ {0, 1}
```

where `1` represents an observed interaction and `0` represents a sampled unobserved interaction.

The pointwise objective is:

```text
(y - p_u^T q_i)^2
+ λ (||p_u||² + ||q_i||²)
```

The first term encourages the predicted score to match the sampled target.

The regularization term discourages excessively large latent vectors.

### 4.3 Negative Sampling

Because unobserved interactions are not automatically explicit negatives, the educational implementation constructs negative examples by sampling items that the user has not interacted with.

This provides training examples for a pointwise learning objective without interpreting every missing user-item pair as a confirmed dislike.

Negative sampling is therefore a training mechanism rather than evidence that the user explicitly rejected the sampled item.

The educational implementation uses small datasets in unit tests. It is not intended to train directly on the full 2.3M+ interaction training split.

### 4.4 Role in the Project

Educational MF is intentionally separate from the library-backed ALS implementation.

Its primary value is understanding:

* user and item embeddings
* dot-product scoring
* stochastic gradient descent
* negative sampling
* regularization
* latent-factor learning

It demonstrates how a recommender can learn a low-dimensional representation rather than relying only on item popularity or explicit similarity.

The implementation is not intended to replace the optimized ALS implementation for production-scale training.

---

## 5. Educational BPR

### 5.1 Pairwise Preference Learning

The educational BPR implementation is located at:

```text
src/ecommerce_recsys/recommendation/bpr_educational.py
```

BPR uses the same latent-factor representation:

```text
s(u, i) = p_u^T q_i
```

but changes the learning objective.

Instead of asking:

```text
"What absolute score should this item receive?"
```

BPR asks:

```text
"Should this observed item be ranked above this sampled unobserved item?"
```

A training example is therefore a triplet:

```text
(u, i+, i-)
```

where:

* `u` = user
* `i+` = observed positive item
* `i-` = sampled unobserved item

The desired relationship is:

```text
s(u, i+) > s(u, i-)
```

### 5.2 BPR Objective

The pairwise score difference is:

```text
x = s(u, i+) - s(u, i-)
```

The BPR loss is based on:

```text
-log σ(x)
```

where `σ` is the sigmoid function.

With regularization, the objective encourages observed items to receive higher scores than sampled unobserved items while controlling factor magnitude.

### 5.3 Training Procedure

The educational BPR implementation:

1. Builds user and item mappings.
2. Initializes latent factors.
3. Samples positive/negative training triplets.
4. Computes the score difference between positive and negative items.
5. Applies pairwise gradients.
6. Updates user, positive-item, and negative-item factors using SGD.
7. Repeats the procedure for multiple epochs.

The implementation also exposes recommendation and prediction methods for testing the learned latent representation.

As with educational MF, educational BPR is intended for learning and experimentation rather than full-scale production training on the complete dataset.

### 5.4 Role in the Project

BPR provides a useful conceptual contrast with pointwise MF.

```text
Educational MF
    ↓
pointwise objective

Educational BPR
    ↓
pairwise ranking objective

Both
    ↓
latent user/item factors
    ↓
dot-product scoring
```

This demonstrates that the same latent representation can be trained according to different objectives depending on the recommendation task.

---

## 6. Production ALS

### 6.1 Architecture

The production-oriented implementation is located at:

```text
src/ecommerce_recsys/recommendation/matrix_factorization.py
```

It uses:

```text
implicit.als.AlternatingLeastSquares
```

The recommender converts raw user and item identifiers into integer indices and constructs a sparse user-item interaction matrix.

The high-level pipeline is:

```text
Raw interaction IDs
        ↓
User/item mappings
        ↓
Sparse CSR user-item matrix
        ↓
Implicit ALS
        ↓
User latent factors P
Item latent factors Q
        ↓
Dot-product scores
        ↓
Top-K recommendations
```

### 6.2 Latent Factors

For the selected final configuration:

```text
factors = 128
```

The learned matrices have the conceptual shapes:

```text
P ∈ R^(number_of_users × 128)

Q ∈ R^(number_of_items × 128)
```

During the latent-factor inspection experiment, the baseline 64-factor model produced:

```text
user_factors.shape = (1,407,580, 64)
item_factors.shape = (228,392, 64)
```

The corresponding factor statistics were:

```text
user factor mean = 0.000017
user factor std  = 0.004356

item factor mean = 0.002590
item factor std  = 0.018511
```

The average and 95th-percentile embedding norms were:

```text
User norm mean = 0.008299
User norm p95  = 0.035592

Item norm mean = 0.041090
Item norm p95  = 0.270883
```

These statistics describe the learned numerical representation. They should not be interpreted as evidence that individual latent dimensions have simple human-readable meanings.

### 6.3 Dot-Product Scoring

The recommendation score is based on the dot product:

```text
s(u, i) = p_u^T q_i
```

A manual score inspection confirmed that the explicit NumPy dot product and the corresponding matrix computation agree to floating-point precision.

The observed absolute difference was approximately:

```text
2.54 × 10^-21
```

This verifies the expected mathematical relationship between the learned user and item factors.

### 6.4 Alternating Optimization

ALS differs from the educational SGD implementations in its optimization procedure.

Conceptually:

```text
Initialize P and Q
       ↓
Fix Q
       ↓
Optimize P
       ↓
Fix P
       ↓
Optimize Q
       ↓
Repeat
```

The `iterations` parameter controls the number of alternating optimization rounds.

The production model uses:

```text
iterations = 20
```

for the selected configuration.

This is fundamentally different from interpreting `iterations` as the number of individual user interactions processed by the model.

### 6.5 Regularization

The ALS implementation exposes:

```text
regularization
```

as a model hyperparameter.

Regularization constrains factor magnitude and controls the effective complexity of the learned representation.

The baseline value was:

```text
regularization = 0.01
```

Experiments with:

```text
0.001
0.01
0.1
```

produced nearly indistinguishable validation ranking metrics under the tested 64-factor, 20-iteration configuration.

Therefore, the experiment did not provide strong evidence that one of these regularization values was materially better than the others.

### 6.6 Confidence Weighting

The current interaction matrix assigns a value of `1.0` to every observed interaction.

Therefore, the current model treats:

```text
view
addtocart
transaction
```

with the same raw interaction value.

Implicit ALS uses interaction values within its implicit-feedback objective, so the value is part of the preference/confidence formulation rather than simply being an explicit rating.

A future experiment could evaluate event-specific weighting, but no event-weighting configuration was selected in M6.

### 6.7 Cold-Start Behavior

For an unknown user, the standalone ALS recommender falls back to a popularity-based recommender.

This prevents the system from failing when a user has no learned latent representation.

Unknown items are different: an item introduced after model training does not automatically have a learned latent vector in the existing ALS model. Handling this form of item cold start requires an update or retraining strategy.

---

## 7. Latent Factor Inspection

The factor inspection experiment used the baseline:

```text
factors = 64
iterations = 20
regularization = 0.01
```

The learned matrices contained:

```text
1,407,580 user vectors
228,392 item vectors
64 dimensions per vector
```

The approximate combined memory footprint of the float32 user and item factor matrices was about:

```text
399.41 MiB
```

Increasing the factor dimension from 64 to 128 approximately doubles latent-factor storage:

```text
64 factors  → approximately 399.41 MiB
128 factors → approximately 798.81 MiB
```

These values follow `(user_count + item_count) * factors * 4 / 2^20` for
float32 arrays. They exclude sparse matrices and full process memory.

This illustrates a model-storage trade-off.

Increasing latent dimension can improve model capacity, but it also increases memory requirements and recommendation computation.

---

## 8. ALS Hyperparameter Experiments

Controlled validation experiments were performed using:

```text
Training split:
train.parquet

Validation split:
val.parquet

K:
5, 10, 20

Random seed:
42
```

The experiments varied one hyperparameter axis at a time.

---

### 8.1 Factors

The following configurations were tested:

```text
factors = 32, 64, 128
iterations = 20
regularization = 0.01
```

| Factors |    HR@20 |  NDCG@20 | Coverage | Avg latency |
| ------: | -------: | -------: | -------: | ----------: |
|      32 | 0.026406 | 0.012391 | 0.008508 |    1.672 ms |
|      64 | 0.037780 | 0.018524 | 0.015119 |    3.345 ms |
|     128 | 0.052838 | 0.025980 | 0.024313 |    6.286 ms |

The tested factor values showed a clear increase in validation ranking metrics as latent dimension increased.

HR@20 changed from:

```text
0.026406
    →
0.037780
    →
0.052838
```

Coverage also increased:

```text
0.008508
    →
0.015119
    →
0.024313
```

The increase in model capacity therefore coincided with improved validation ranking metrics and broader catalog coverage.

At the same time, inference latency increased substantially.

The 128-factor configuration therefore represents a capacity/latency trade-off rather than a free performance improvement.

---

### 8.2 Regularization

The following configurations were tested:

```text
factors = 64
iterations = 20
regularization = 0.001, 0.01, 0.1
```

| Regularization |    HR@20 |  NDCG@20 | Coverage |
| -------------: | -------: | -------: | -------: |
|          0.001 | 0.037805 | 0.018526 | 0.015119 |
|           0.01 | 0.037780 | 0.018524 | 0.015119 |
|            0.1 | 0.037795 | 0.018531 | 0.015115 |

The differences are extremely small.

For example, HR@20 varied only between:

```text
0.037780 and 0.037805
```

while NDCG@20 varied only between:

```text
0.018524 and 0.018531
```

Coverage was also effectively unchanged.

The experiment therefore suggests that the tested regularization range had much less impact on validation ranking performance than the tested factor dimension.

The result should not be generalized beyond the evaluated configurations.

---

### 8.3 Iterations

The following configurations were tested:

```text
factors = 64
regularization = 0.01
iterations = 10, 20, 40
```

| Iterations |    HR@20 |  NDCG@20 | Coverage | Avg latency |
| ---------: | -------: | -------: | -------: | ----------: |
|         10 | 0.037245 | 0.018257 | 0.015332 |    3.334 ms |
|         20 | 0.037780 | 0.018524 | 0.015119 |    3.303 ms |
|         40 | 0.038080 | 0.018641 | 0.014911 |    3.119 ms |

Increasing iterations from 10 to 20 improved HR@20 and NDCG@20.

Increasing iterations from 20 to 40 produced only marginal additional changes:

```text
HR@20:
0.037780 → 0.038080

NDCG@20:
0.018524 → 0.018641
```

At the same time, coverage decreased slightly.

The results therefore indicate diminishing returns from additional iterations within the tested range.

The reported inference-latency differences should not be interpreted as evidence that more iterations make inference faster. Training iterations do not change the latent vector dimensionality, and the evaluation excludes fitting time. Small differences in measured inference latency can result from runtime variability.

---

### 8.4 Candidate Configuration

After the one-axis experiments, the following configurations were considered:

| Configuration   |    HR@20 |  NDCG@20 | Coverage |
| --------------- | -------: | -------: | -------: |
| 64 / 20 / 0.01  | 0.037780 | 0.018524 | 0.015119 |
| 64 / 40 / 0.01  | 0.038080 | 0.018641 | 0.014911 |
| 128 / 20 / 0.01 | 0.052838 | 0.025980 | 0.024313 |
| 128 / 40 / 0.01 | 0.052963 | 0.025842 | 0.024117 |

Configuration format:

```text
factors / iterations / regularization
```

The `128 / 40 / 0.01` candidate produced a slightly higher HR@20 than `128 / 20 / 0.01`, but the difference was small:

```text
0.052838 → 0.052963
```

At the same time, NDCG@20 and coverage were slightly lower.

Therefore, the selected configuration was:

```text
factors = 128
iterations = 20
regularization = 0.01
```

The selection was based on validation results and the trade-off between ranking quality, coverage, model capacity, and additional optimization cost.

---

## 9. Validation-Based Model Selection

The validation experiments established the final ALS configuration before the test set was evaluated.

Selected configuration:

```text
factors = 128
iterations = 20
regularization = 0.01
random_seed = 42
```

The selection process was:

```text
Train
  ↓
Controlled validation experiments
  ↓
Compare factor capacity
  ↓
Compare regularization
  ↓
Compare optimization iterations
  ↓
Evaluate targeted candidate
  ↓
Select 128 / 20 / 0.01
  ↓
Final held-out test evaluation
```

The test set was not used for hyperparameter selection.

This separation prevents the final test results from becoming part of the tuning process.

---

## 10. Final Test Evaluation

The selected configuration was evaluated once on the held-out test split.

### Final configuration

```text
factors = 128
iterations = 20
regularization = 0.01
random_seed = 42
```

### Final test metrics

| Metric          |    Result |
| --------------- | --------: |
| HR@5            |  0.020947 |
| HR@10           |  0.030291 |
| HR@20           |  0.042394 |
| MRR@5           |  0.011797 |
| MRR@10          |  0.013029 |
| MRR@20          |  0.013864 |
| NDCG@5          |  0.014056 |
| NDCG@10         |  0.017063 |
| NDCG@20         |  0.020117 |
| Coverage        |  0.024313 |
| Average latency |  7.324 ms |
| p50 latency     |  6.831 ms |
| p95 latency     | 10.192 ms |
| p99 latency     | 12.641 ms |

The final evaluation uses:

```text
training split = train.parquet
evaluation split = test.parquet
```

and contains 200,028 evaluation users.

The final test artifact is:

```text
benchmarks/mf/als_final_v1.json
```

---

## 11. Findings

### 11.1 Latent factor capacity had the largest observed effect

Among the tested ALS hyperparameters, factor dimension produced the clearest validation effect.

Increasing factors from 32 to 128 improved both ranking metrics and coverage:

```text
HR@20:
0.026406 → 0.052838

Coverage:
0.008508 → 0.024313
```

This indicates that the tested dataset benefited from increased latent representation capacity.

However, the larger representation also increased inference cost and latent-factor memory.

---

### 11.2 Regularization was relatively insensitive in the tested range

The tested values:

```text
0.001
0.01
0.1
```

produced nearly identical validation results.

This means that, for the evaluated factor and iteration configuration, regularization was not a dominant source of performance variation.

The result does not imply that regularization is unimportant in general. It only describes the behavior observed in this experiment.

---

### 11.3 Additional ALS iterations showed diminishing returns

Increasing iterations from 10 to 20 improved ranking metrics.

Increasing them from 20 to 40 produced only marginal changes.

Therefore, increasing optimization iterations beyond 20 was not justified by a substantial validation improvement in this experiment.

---

### 11.4 ALS provides personalized latent-factor recommendations

Unlike global or category-level popularity recommenders, ALS learns user-specific and item-specific latent representations.

The model therefore provides a mechanism for personalized ranking:

```text
user history
     ↓
user latent representation
     ↓
interaction with item latent representations
     ↓
personalized scores
     ↓
Top-K recommendations
```

This makes ALS structurally suitable for a candidate-generation or retrieval stage in a larger recommendation architecture.

Whether it should ultimately serve as the production candidate generator requires separate system-level evaluation.

---

### 11.5 Coverage remains an important trade-off

The final ALS configuration achieved:

```text
Coverage = 0.024313
```

This means the recommendations cover a fraction 0.024313 of the catalog under the project's coverage definition and evaluation population.

Higher factor dimensions increased coverage in the controlled factor experiment.

Coverage should therefore be considered alongside ranking metrics rather than treated as a secondary implementation detail.

---

## 12. Production Trade-offs

| Dimension            | Observation                                                             |
| -------------------- | ----------------------------------------------------------------------- |
| Model representation | 128-dimensional user/item latent factors                                |
| Ranking              | Personalized latent-factor scoring                                      |
| Training method      | Implicit ALS                                                            |
| Optimization         | Alternating least squares                                               |
| User cold start      | Popularity fallback                                                     |
| Item cold start      | Requires model update/retraining                                        |
| Interpretability     | Latent dimensions are not directly human-interpretable                  |
| Memory               | Latent-factor storage grows approximately linearly with factor count    |
| Inference            | Higher factor count increases recommendation computation                |
| Training cost        | Larger factor dimensions and more iterations increase training workload |
| Event weighting      | Current implementation uses equal raw interaction values                |
| Evaluation           | Temporal validation and held-out test                                   |
| Production role      | Potential retrieval/candidate-generation component                      |

The final 128-factor model is substantially more expensive than the 64-factor model in inference and latent-factor storage.

The factor experiment therefore illustrates an important production principle:

> Better ranking quality is not automatically equivalent to a better production configuration.

A production choice must consider ranking quality, coverage, latency, memory, retraining cost, and downstream architecture.

---

## 13. Limitations

### 13.1 Single per-user chronological split

The historical experiments use one per-user chronological train/validation/test split, without a global training cutoff.

Results may vary across different time periods or traffic distributions.

The [rolling benchmark](ROLLING_BENCHMARK_REPORT.md) uses global time boundaries and repeated future windows; its inspected periods still have a diagnostic validity limit.

### 13.2 Limited hyperparameter search

The experiments intentionally evaluate a small set of configurations:

```text
factors:
32, 64, 128

regularization:
0.001, 0.01, 0.1

iterations:
10, 20, 40
```

This is a controlled engineering experiment rather than an exhaustive hyperparameter optimization procedure.

### 13.3 No statistical significance analysis

The reported differences are descriptive.

No confidence intervals, bootstrap analysis, or statistical significance tests were performed.

Very small differences between configurations should therefore not be interpreted as statistically meaningful improvements.

### 13.4 Equal interaction weighting

The current ALS implementation maps all observed event types to the same raw value.

The dataset contains different behavioral strengths such as views, cart additions, and transactions, but these are not distinguished by the current ALS configuration.

### 13.5 Top-K scope

The historical M6 experiment evaluates final Top-K recommendations. It does not
measure candidate availability for a downstream ranker. The
[candidate retrieval report](CANDIDATE_RETRIEVAL_REPORT.md) measures that separate
stage using the rolling targets and catalog.

### 13.6 Cold-start item handling remains limited

Unknown users receive a popularity fallback.

New items introduced after model training do not automatically receive latent representations.

A production system would require a strategy for item onboarding and model refresh.

---

## 14. Final Decision

The library-backed ALS implementation is the matrix-factorization reference in this historical M6 experiment.

The educational MF and BPR implementations are retained as learning-oriented implementations because they expose the mechanics of latent-factor learning, negative sampling, SGD, pairwise ranking, and regularization.

The selected historical ALS reference configuration is:

```text
factors = 128
iterations = 20
regularization = 0.01
random_seed = 42
```

Selection used the historical validation split, followed by one historical test evaluation. Earlier baseline experiments had already used that test population.

The final test result is:

```text
HR@20   = 0.042394
NDCG@20 = 0.020117
Coverage = 0.024313
```

with:

```text
average recommendation latency = 7.324 ms
p95 recommendation latency     = 10.192 ms
```

The main experimental conclusion is that latent factor dimension had the clearest observed impact among the tested ALS hyperparameters, while regularization was relatively insensitive and additional iterations showed diminishing returns.

These measurements retain ALS as a historical matrix-factorization reference; the rolling-selected configuration is recorded separately in the [configuration mapping](METRICS_AND_PROTOCOLS.md#als-configuration-mapping).

Historical Top-20 results do not establish candidate-retrieval quality or a production architecture choice. The [candidate retrieval report](CANDIDATE_RETRIEVAL_REPORT.md) measures that separate task under the rolling protocol.

---

## Experiment Artifacts

Relevant M6 artifacts:

```text
src/ecommerce_recsys/recommendation/matrix_factorization_educational.py
tests/unit/test_matrix_factorization_educational.py

src/ecommerce_recsys/recommendation/bpr_educational.py
tests/unit/test_bpr_educational.py

scripts/inspect_als_factors.py
scripts/inspect_als_score.py

scripts/benchmark_als_experiments.py
scripts/benchmark_als_final.py

benchmarks/mf/als_experiments_v1.json
benchmarks/mf/als_final_v1.json
```

Historical baseline benchmark artifacts are preserved separately and are not modified by the M6 experiments.
