Project Status

**Last updated:** 2026-09-12

**Repository:** `ecommerce-recsys`

**Branch:** `main`

**Current release:** Pre-v0.1

**Current milestone:** Milestone 6 — Ready to Start

---

## 1. Current Objective

Build a production-oriented e-commerce recommendation system based on implicit user behavior.

The project follows a staged development process:

* establish the project and engineering foundation

* select and document the dataset

* build a reproducible data pipeline

* establish temporal evaluation foundations

* establish strong non-personalized baselines

* develop personalized recommendation models

* evaluate candidate-generation and ranking approaches

* build production-oriented serving and deployment infrastructure

The current system has completed Milestones 0–5.

Milestone 4 established the non-personalized baseline performance floor.

Milestone 5 introduced personalized collaborative filtering through ItemKNN and investigated support-aware similarity shrinkage.

The current baseline floor remains:

**Category Popularity — Recall@20 ≈ 8.51%**

Future personalized and retrieval models must be evaluated using the established evaluation contract and compared against this baseline.

---

## 2. Completed

### Repository Foundation

Completed:

* Git repository initialized

* default branch set to `main`

* repository structure created

* Python development environment established

* development requirements configured

* test infrastructure configured

* lint and formatting infrastructure configured

* initial CI quality gate established

Current directory structure includes:

```text

ecommerce-recsys/

├── .github/

├── artifacts/

├── benchmarks/

├── configs/

├── data/

│ ├── interim/

│ ├── processed/

│ └── raw/

├── deployment/

├── docs/

├── notebooks/

├── requirements/

├── scripts/

├── src/

└── tests/

├── integration/

└── unit/

```

### Documentation

Completed source-of-truth documents include:

* `docs/PROJECT_CHARTER.md`

* `docs/PROJECT_STATUS.md`

* `docs/ARCHITECTURE_CURRENT.md`

* `docs/DECISIONS.md`

* `docs/DATA_CONTRACT.md`

* `docs/DATASET_CARD.md`

* `docs/DATA_QUALITY_REPORT.md`

* `docs/EVALUATION_PROTOCOL.md`

* `docs/BASELINE_REPORT.md`

These documents define the project scope, dataset contract, data-quality decisions, evaluation protocol, architecture decisions, baseline methodology, and current implementation state.

---

## 3. Current Work

Milestones 0–5 are complete.

Milestone 4 established the non-personalized recommendation baseline.

Milestone 5 established the first personalized collaborative-filtering model and completed the first model-specific analysis cycle.

The completed Milestone 5 work includes:

* ItemKNN collaborative filtering

* support-aware similarity shrinkage

* shrinkage hyperparameter sweep

* final ItemKNN configuration selection

* empty-history and candidate-availability analysis

* recommendation concentration analysis

* final ItemKNN benchmark

The final selected ItemKNN configuration uses:

```text

n_neighbors: 20

min_item_interactions: 5

shrinkage_lambda: 100

```

The project is now ready to transition to:

**Milestone 6 — Matrix Factorization for Implicit Feedback**

Milestone 6 should deepen the understanding of matrix-factorization methods and implicit-feedback recommendation rather than reimplementing the existing ALS model from scratch.

---

## 4. Validated Facts

### Repository

Repository:

```text

E:\ecommerce-recsys

```

Current branch:

```text

main

```

Remote branch status:

```text

local main contains completed Milestone 5 changes pending push

```

The Milestone 5 implementation and benchmark changes have been committed locally.

Documentation updates are being finalized before synchronizing the milestone with the remote repository.

### Dataset

Dataset selection:

```text

COMPLETED

```

Processed interaction dataset:

```text

data/processed/interactions.parquet

```

Processed catalog metadata:

```text

data/processed/items.parquet

```

Dataset statistics:

```text

Interactions: 2,756,101

Train interactions: 2,356,045

Validation users: 200,028

Test users: 200,028

Catalog items: 235,061

```

The dataset and data contract were established during Milestones 1–2.

### Interaction Semantics

Interaction data contains implicit behavioral signals including:

* view

* cart / add-to-cart

* purchase / transaction

The interaction representation and derived columns are documented in the project data contract.

Processed interaction records contain:

```text

user_id

item_id

timestamp

event_type

datetime

is_view

is_cart

is_purchase

transaction_id

```

### Evaluation Dataset

The temporal evaluation split is completed.

Generated datasets:

```text

data/processed/train.parquet

data/processed/val.parquet

data/processed/test.parquet

```

Current test contract:

```text

Test rows: 200,028

Unique test users: 200,028

Targets per user: 1

Warm-start users: 100%

Duplicate test targets: 0

```

The split follows a temporal leave-last-out strategy.

The test target represents a future interaction relative to the user's training history.

### Evaluation Benchmark

Status:

```text

CREATED AND FROZEN FOR BASELINE V1

```

Benchmark artifact:

```text

benchmarks/baseline/baseline_v1.json

```

The benchmark evaluates recommendation quality using:

* Recall@K / Hit Rate@K

* NDCG@K

* Coverage

* average recommendation latency

* P50 latency

* P95 latency

* P99 latency

Because each test user has exactly one held-out target:

```text

Recall@K = Hit Rate@K

```

for the current benchmark contract.

Coverage is measured at the maximum evaluated recommendation cutoff:

```text

Coverage@20

```

Milestone 5 introduced additional model-specific benchmark artifacts without modifying the frozen Milestone 4 baseline artifact.

### Models

Core recommendation models currently implemented:

* Random Recommender

* Global Popularity

* Recent Popularity

* Category Popularity

* ItemKNN

* ALS / Matrix Factorization

ItemKNN is the first personalized nearest-neighbor collaborative-filtering model.

ALS is an implicit-feedback matrix-factorization model implemented during Milestone 4 and retained as an extended personalized reference.

The current ItemKNN final configuration uses support-aware similarity shrinkage with:

```text

shrinkage_lambda = 100

```

The shrinkage sweep showed a clear improvement over raw cosine similarity, with performance plateauing around higher lambda values.

The selected value of 100 is retained as a representative configuration rather than because it uniquely maximizes every metric.

### Serving

Status:

```text

NOT IMPLEMENTED

```

No production recommendation API has been implemented yet.

Serving is intentionally deferred until recommendation models and candidate-generation strategies are established.

### Deployment

Status:

```text

NOT IMPLEMENTED

```

Production containerization and cloud deployment are deferred to later milestones.

---

## 5. Architecture Currently Implemented

The project now contains an implemented offline recommendation and evaluation architecture.

Current high-level flow:

```text

Raw Dataset

|

v

Data Processing

|

v

Processed Interactions + Catalog

|

v

Temporal Train / Validation / Test Split

|

v

Recommendation Models

|

+-- Random

+-- Global Popularity

+-- Recent Popularity

+-- Category Popularity

+-- ItemKNN

+-- ALS / Matrix Factorization

|

v

Unified Evaluation Harness

|

+-- Recall\@K / Hit Rate\@K

+-- NDCG\@K

+-- Coverage

+-- Latency

|

v

Benchmark Artifacts + Reports

```

Current implemented recommendation components are located under:

```text

src/ecommerce_recsys/recommendation/

```

Current evaluation components are located under:

```text

src/ecommerce_recsys/evaluation/

```

The project does not yet contain a production online-serving architecture.

The project also does not yet contain a separate candidate-generation service.

Candidate-generation abstractions will be introduced in later milestones once the available retrieval models have been established.

Planned components must not be described as implemented until they actually exist.

See:

```text

docs/ARCHITECTURE_CURRENT.md

```

for the authoritative architecture description.

---

## 6. Known Issues / Limitations

Current blockers:

```text

None

```

Known limitations:

### Warm-start evaluation

The current test benchmark contains 100% warm-start users.

Cold-start user recommendation is not yet evaluated as a dedicated benchmark.

Popularity-based fallback behavior exists for models that cannot generate personalized candidates for a user.

### ItemKNN indexed-history limitation

ItemKNN indexes only items satisfying the configured minimum interaction threshold.

In the current analysis:

```text

Test users: 200,028

No indexed history: 11,377

Has indexed history: 188,651

No candidates: 16,168

No positive-similarity neighbor: 4,675

```

This means a portion of users cannot receive personalized ItemKNN candidates from their indexed history and require fallback behavior.

### ItemKNN catalog coverage

The full catalog contains:

```text

235,061 items

```

ItemKNN indexes:

```text

84,077 items

```

Therefore ItemKNN does not operate over the complete catalog.

This is expected for an interaction-based collaborative-filtering model with a minimum interaction threshold.

### Recommendation concentration

The final ItemKNN analysis shows that recommendations are concentrated among a subset of the indexed catalog.

Current distribution:

```text

Unique recommended items: 60,840

Top 10 items: 3.72% of recommendation slots

Top 100 items: 18.83% of recommendation slots

Top 1,000 items: 45.75% of recommendation slots

```

This indicates that future retrieval and ranking stages should consider diversity and popularity concentration.

### Unseen test items

A small portion of test targets correspond to items not observed in training.

Therefore, collaborative-filtering models may be unable to recommend these items without additional item-side information or a fallback retrieval strategy.

### Missing category metadata

The catalog contains items without category metadata.

Therefore, Category Popularity cannot use category-specific signals for every catalog item and relies on fallback behavior where necessary.

### Offline latency

Reported baseline latency measures recommendation computation at the model/harness level.

It does not represent end-to-end production API latency.

---

## 7. Next Exact Tasks

Milestones 0–5 are complete.

The project is now transitioning to:

**Milestone 6 — Matrix Factorization for Implicit Feedback**

The objective is to deepen the understanding of matrix-factorization recommendation while building on the ALS implementation already completed during Milestone 4.

ALS should not be rewritten simply for the sake of implementation.

### Task 6.1 — Educational Matrix Factorization

Implement a small educational matrix-factorization model to understand the underlying mechanics.

The implementation should cover:

* user embeddings

* item embeddings

* latent dimensions

* scoring function

* regularization

* training objective

The educational implementation does not need to be production-ready.

Its purpose is to make the mathematical structure of matrix factorization explicit.

### Task 6.2 — Implicit Feedback Modeling

Study and document how implicit interaction data differs from explicit ratings.

The analysis should cover:

* positive-only observations

* missing interactions versus negative feedback

* confidence weighting

* interaction strength

* regularization

* negative sampling interpretation

### Task 6.3 — Pairwise Learning / BPR

Implement or study an educational BPR-style objective to understand pairwise recommendation learning.

The focus should be:

* positive item

* negative item

* pairwise preference

* ranking objective

* negative sampling

BPR does not need to become the production model unless experiments justify retaining it.

### Task 6.4 — Evaluate Existing ALS

Evaluate the existing ALS implementation using the established evaluation contract.

The evaluation should include:

* Recall@K

* MRR@K

* NDCG@K

* Coverage

* latency

The objective is to understand ALS rather than simply obtain another benchmark number.

### Task 6.5 — Matrix Factorization Experiments

Run controlled experiments over relevant MF parameters.

Potential dimensions include:

* number of latent factors

* regularization

* number of iterations

* interaction weighting

* model configuration

Experiments must use the existing train / validation / test protocol without test-set tuning.

### Task 6.6 — Compare Personalized Models

Compare:

```text

Category Popularity

ItemKNN

ALS / Matrix Factorization

```

The comparison should consider:

* recommendation quality

* coverage

* latency

* cold-start behavior

* model complexity

* interpretability

The goal is to determine which models should become candidate-generation sources in the next stage.

### Task 6.7 — Document MF Decision

Create a matrix-factorization experiment report documenting:

* model formulation

* training protocol

* experiment configuration

* evaluation results

* trade-offs

* limitations

* final decision

The report should explain whether ALS and/or another MF approach should be retained for future candidate generation.

---

## 8. Files Changed in Current Milestone

Milestone 5 introduced or updated the following primary artifacts:

```text

src/ecommerce_recsys/recommendation/item_knn.py

tests/unit/test_item_knn.py

scripts/benchmark_baselines.py

scripts/benchmark_item_knn_shrinkage.py

scripts/benchmark_item_knn_final.py

scripts/analyze_item_knn_empty_users.py

scripts/analyze_recommendation_concentration.py

benchmarks/item_knn_shrinkage_sweep.csv

benchmarks/item_knn_final.csv

```

Milestone 4 baseline artifact remains frozen:

```text

benchmarks/baseline/baseline_v1.json

```

Milestone 5 does not overwrite the canonical Milestone 4 benchmark snapshot.

---

## 9. Commands Used to Validate

Repository branch:

```powershell

git branch --show-current

```

Expected:

```text

main

```

Repository status:

```powershell

git status

```

Expected after intentional local files are excluded:

```text

no unexpected tracked changes

```

Ruff lint:

```powershell

ruff check .

```

Ruff formatting:

```powershell

ruff format --check .

```

Unit tests:

```powershell

pytest tests/unit -q

```

Broader test suite:

```powershell

pytest tests/ -q

```

GitHub Actions:

```text

PASS

```

---

## 10. Current Validation Results

### Git

Status:

```text

PASS

```

Branch:

```text

main

```

Milestone 5 implementation commits:

```text

COMMITTED LOCALLY

```

Remote synchronization:

```text

PENDING FINAL DOCUMENTATION UPDATE

```

### Tests

Latest full unit test result:

```text

56 passed, 1 warning

```

The warning is related to the OpenBLAS threading environment used by the implicit ALS dependency and does not currently cause test failure.

### Lint

Status:

```text

PASS

```

Ruff check completes successfully.

### Formatting

Status:

```text

PASS

```

Ruff format validation completes successfully.

### CI

Status:

```text

PASS

```

GitHub Actions quality gate is green.

### Dataset Benchmark

Status:

```text

BASELINE V1 COMPLETED

```

Benchmark artifact:

```text

benchmarks/baseline/baseline_v1.json

```

### Recommendation Quality

Core Milestone 4 baseline results at Recall@20:

```text

Category Popularity ≈ 8.51%

Global Popularity ≈ 1.14%

Recent Popularity ≈ 0.98%

Random ≈ 0.004%

```

Extended personalized references:

```text

ALS ≈ 3.06%

ItemKNN v1 ≈ 5.57%

ItemKNN λ=100 ≈ 5.90%

```

Final ItemKNN λ=100 benchmark:

```text

HR@5: 0.035735

MRR@5: 0.021286

NDCG@5: 0.024873

HR@10: 0.048078

MRR@10: 0.022939

NDCG@10: 0.028870

HR@20: 0.058972

MRR@20: 0.023698

NDCG@20: 0.031628

Coverage: 0.256333

```

ItemKNN support-aware shrinkage improved recommendation quality over the raw cosine configuration.

The improvement from lambda 0 to lambda 100 on the full benchmark was approximately:

```text

Recall@5: +14.2%

Recall@10: +12.3%

Recall@20: +5.8%

MRR@10: +15.0%

NDCG@10: +14.0%

Coverage: approximately unchanged

```

Category Popularity remains stronger in Recall@10 and Recall@20, while ItemKNN provides substantially broader recommendation coverage and user-specific personalization.

Therefore, ItemKNN is not considered a replacement for Category Popularity.

It is considered a complementary personalized candidate source for future candidate-generation experiments.

### ItemKNN Latency

Final ItemKNN λ=100 benchmark:

```text

Average: ≈ 0.0445 ms

P50: ≈ 0.0211 ms

P95: ≈ 0.1272 ms

P99: ≈ 0.3070 ms

```

These values represent model-level offline recommendation computation and should not be interpreted as production API latency.

### API Latency

Status:

```text

NOT IMPLEMENTED

```

Offline baseline recommendation latency is measured, but production API latency has not yet been established.

### Memory

Status:

```text

NOT APPLICABLE TO CURRENT MILESTONE

```

Production memory benchmarking will be introduced when serving infrastructure exists.

---

## 11. Do Not Change / Do Not Do Yet

Until the next model-development milestone:

* do not change the frozen Milestone 3 evaluation contract without an explicit architecture decision

* do not change the baseline benchmark protocol merely to improve a model's score

* do not modify the frozen Milestone 4 baseline artifact without explicitly creating a new benchmark version

* do not tune hyperparameters on the test set

* do not mix validation/test data into model fitting

* do not treat Category Popularity as a personalized model

* do not claim ItemKNN beats Category Popularity across all metrics

* do not introduce neural recommendation models before establishing the required classical personalized baselines

* do not add ANN infrastructure before there is a retrieval model that requires it

* do not add Qdrant

* do not add Redis

* do not add Kafka

* do not add Kubernetes

* do not create a production API prematurely

* do not invent benchmark results

* do not describe planned components as implemented

* do not redo ALS merely because it already exists

* do not move into candidate-generation architecture before completing the matrix-factorization analysis

The current benchmark floor should remain stable while future recommendation models are developed.

---

## 12. Milestone Progress

```text

Milestone 0 — Foundation

[x] Completed

Milestone 1 — Dataset Selection & Data Contract

[x] Completed

[x] docs/DATA\_CONTRACT.md

[x] docs/DATASET\_CARD.md

[x] data/raw/README.md & .gitignore data policy

[x] scripts/download\_data.py

[x] src/ecommerce\_recsys/data/schemas.py

[x] tests/unit/test\_schemas.py

Milestone 2 — Data Quality & EDA

[x] Completed

[x] Raw dataset verified

[x] notebooks/01\_data\_understanding.ipynb

[x] scripts/run\_eda.py

[x] Interaction semantics decisions

[x] scripts/build\_interactions.py

[x] data/processed/interactions.parquet

[x] data/processed/items.parquet

[x] docs/DATA\_QUALITY\_REPORT.md

Milestone 3 — Evaluation Foundation

[x] Completed

[x] docs/EVALUATION\_PROTOCOL.md

[x] src/ecommerce\_recsys/evaluation/metrics.py

[x] tests/unit/test\_metrics.py

[x] src/ecommerce\_recsys/data/splitting.py

[x] scripts/split\_data.py

[x] tests/unit/test\_temporal\_split.py

[x] train.parquet / val.parquet / test.parquet

[x] temporal evaluation contract

[x] one held-out target per test user

Milestone 4 — Non-Personalized Baselines

[x] Completed

[x] Random Recommender

[x] Global Popularity

[x] Recent Popularity

[x] Category Popularity

[x] Unified evaluation harness

[x] Recall\@K / NDCG\@K / Coverage

[x] recommendation latency measurement

[x] benchmarks/baseline/baseline\_v1.json

[x] docs/BASELINE\_REPORT.md

[x] benchmark unit tests

[x] Ruff lint

[x] Ruff formatting

[x] GitHub Actions CI

[x] benchmark results committed and pushed

Milestone 5 — Personalized Recommendation

[x] Completed

[x] ItemKNN collaborative filtering

[x] ItemKNN unit tests

[x] support-aware similarity shrinkage

[x] shrinkage lambda sweep

[x] final lambda selection

[x] empty-history / candidate-availability analysis

[x] recommendation concentration analysis

[x] final ItemKNN benchmark

[x] benchmark artifacts versioned

[x] full unit test validation

Milestone 6 — Matrix Factorization for Implicit Feedback

[ ] Ready to Start

[ ] Educational Matrix Factorization

[ ] Implicit-feedback modeling analysis

[ ] BPR / pairwise learning study

[ ] Existing ALS evaluation

[ ] Matrix-factorization experiments

[ ] Personalized model comparison

[ ] MF experiment report

```

---

## 13. Milestone 0 Exit Criteria

Milestone 0 is complete.

The original foundation exit criteria have been satisfied:

* project objective documented

* recommendation surfaces documented

* repository structure created

* source-of-truth documents established

* Python environment reproducible

* quality tooling configured

* tests executable

* initial CI quality gate established

* repository validation passes

* foundation state committed

Subsequent milestones have extended this foundation with dataset selection, data processing, temporal evaluation, non-personalized baselines, and personalized collaborative filtering.

Milestone 5 has established the first personalized recommendation model and demonstrated that support-aware ItemKNN similarity can improve over the raw ItemKNN configuration.

The project should now proceed from personalized collaborative filtering toward deeper matrix-factorization modeling and, subsequently, candidate-generation architecture.