# Project Status

**Last updated:** 2026-09-07

**Repository:** `ecommerce-recsys`

**Branch:** `main`

**Current release:** Pre-v0.1

**Current milestone:** Milestone 4 — Completed (Ready for Milestone 5)

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

The current system has completed Milestones 0–4.

Milestone 4 establishes the baseline performance floor that future personalized recommendation models must beat.

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
│   ├── interim/
│   ├── processed/
│   └── raw/
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

Milestones 0–4 are complete.

The project is now ready to transition to:

**Milestone 5 — Personalized Recommendation / Collaborative Filtering**

The primary objective of the next stage is to determine whether user-specific interaction history can outperform the strongest established non-personalized baseline.

The current benchmark floor is:

**Category Popularity — Recall@20 ≈ 8.51%**

Future personalized models must be evaluated using the established evaluation contract and compared against this baseline.

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
main is synchronized with origin/main
```

The latest Milestone 4 changes have been committed and pushed.

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
Interactions:        2,756,101
Users:               200,028 test users
Catalog items:       235,061
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
Test rows:                    200,028
Unique test users:            200,028
Targets per user:             1
Warm-start users:             100%
Duplicate test targets:       0
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

### Models

Core Milestone 4 baselines implemented:

* Random Recommender
* Global Popularity
* Recent Popularity
* Category Popularity

Extended classical references evaluated during development:

* ItemKNN
* ALS / Matrix Factorization

ItemKNN and ALS are treated as extended references and are not part of the core Milestone 4 pass/fail definition.

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
Recommendation Baselines
    |
    +-- Random
    +-- Global Popularity
    +-- Recent Popularity
    +-- Category Popularity
    |
    v
Unified Evaluation Harness
    |
    +-- Recall@K / Hit Rate@K
    +-- NDCG@K
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

Cold-start user recommendation is not yet evaluated.

### Unseen test items

A small portion of test targets correspond to items not observed in training.

Therefore, some collaborative-filtering models may be unable to recommend these items without additional item-side information.

### Missing category metadata

The catalog contains items without category metadata.

Therefore, Category Popularity cannot use category-specific signals for every catalog item and relies on fallback behavior where necessary.

### Offline latency

Reported baseline latency measures recommendation computation at the model/harness level.

It does not represent end-to-end production API latency.

---

## 7. Next Exact Tasks

Milestone 4 is complete.

The project is now transitioning to:

**Milestone 5 — Personalized Recommendation**

The next milestone should introduce personalized recommendation models while preserving the evaluation contract established in Milestone 3 and the baseline floor established in Milestone 4.

### Task 5.1 — Establish Personalized Baseline

Implement the first user-item personalized recommendation model.

The model must:

* train only on training data
* generate recommendations for warm-start users
* exclude previously interacted items where appropriate
* use the existing recommendation interface
* run through the same evaluation harness

### Task 5.2 — Evaluate Against Baseline Floor

Compare the personalized model against:

```text
Random
Global Popularity
Recent Popularity
Category Popularity
```

The primary comparison target is:

```text
Category Popularity
Recall@20 ≈ 8.51%
```

### Task 5.3 — Analyze Personalization Gain

Measure whether the personalized model provides meaningful improvement in:

* Recall@K
* NDCG@K
* Coverage
* latency

The goal is not merely to obtain a higher score, but to understand where personalization provides value.

### Task 5.4 — Document the First Personalized Benchmark

Create a benchmark artifact and report documenting:

* model configuration
* training protocol
* evaluation protocol
* quality metrics
* coverage
* latency
* comparison against Milestone 4 baselines
* limitations

No personalized model should be considered successful unless its performance is evaluated against the established baseline floor.

---

## 8. Files Changed in Current Milestone

Milestone 4 introduced or updated the following primary artifacts:

```text
benchmarks/baseline/baseline_v1.json

docs/BASELINE_REPORT.md

scripts/benchmark_baselines.py

src/ecommerce_recsys/evaluation/benchmark.py

src/ecommerce_recsys/recommendation/category_popularity.py

src/ecommerce_recsys/recommendation/random_recommender.py

tests/unit/test_benchmark.py
```

Existing recommendation components used by the benchmark include:

```text
src/ecommerce_recsys/recommendation/popularity.py

src/ecommerce_recsys/recommendation/recent_popularity.py
```

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

Expected:

```text
working tree clean
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
pytest tests/unit/test_benchmark.py -q
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

Remote synchronization:

```text
PASS
```

### Tests

Milestone 4 benchmark tests:

```text
8 passed
```

The project test suite includes unit and integration test infrastructure established in previous milestones.

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
Category Popularity    ≈ 8.51%
Global Popularity      ≈ 1.14%
Recent Popularity      ≈ 0.98%
Random                 ≈ 0.004%
```

Extended development references:

```text
ItemKNN                 ≈ 5.57%
ALS                     ≈ 3.06%
```

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
* do not treat Category Popularity as a personalized model
* do not claim ItemKNN or ALS as the official Milestone 4 core baselines
* do not introduce neural recommendation models before establishing the required classical personalized baselines
* do not add ANN infrastructure before there is a retrieval model that requires it
* do not add Qdrant
* do not add Redis
* do not add Kafka
* do not add Kubernetes
* do not create a production API prematurely
* do not invent benchmark results
* do not mix validation/test data into model fitting
* do not describe planned components as implemented
* do not modify the frozen baseline artifact without explicitly creating a new benchmark version

The current benchmark floor should remain stable while future recommendation models are developed.

---

## 12. Milestone Progress

```text
Milestone 0 — Foundation

[x] Completed

Milestone 1 — Dataset Selection & Data Contract

[x] Completed

    [x] docs/DATA_CONTRACT.md
    [x] docs/DATASET_CARD.md
    [x] data/raw/README.md & .gitignore data policy
    [x] scripts/download_data.py
    [x] src/ecommerce_recsys/data/schemas.py
    [x] tests/unit/test_schemas.py

Milestone 2 — Data Quality & EDA

[x] Completed

    [x] Raw dataset verified
    [x] notebooks/01_data_understanding.ipynb
    [x] scripts/run_eda.py
    [x] Interaction semantics decisions
    [x] scripts/build_interactions.py
    [x] data/processed/interactions.parquet
    [x] data/processed/items.parquet
    [x] docs/DATA_QUALITY_REPORT.md

Milestone 3 — Evaluation Foundation

[x] Completed

    [x] docs/EVALUATION_PROTOCOL.md
    [x] src/ecommerce_recsys/evaluation/metrics.py
    [x] tests/unit/test_metrics.py
    [x] src/ecommerce_recsys/data/splitting.py
    [x] scripts/split_data.py
    [x] tests/unit/test_temporal_split.py
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
    [x] Recall@K / NDCG@K / Coverage
    [x] recommendation latency measurement
    [x] benchmarks/baseline/baseline_v1.json
    [x] docs/BASELINE_REPORT.md
    [x] benchmark unit tests
    [x] Ruff lint
    [x] Ruff formatting
    [x] GitHub Actions CI
    [x] benchmark results committed and pushed

Milestone 5 — Personalized Recommendation

[ ] Not started
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

Subsequent milestones have extended this foundation with dataset selection, data processing, temporal evaluation, and recommendation baselines.

The project should now proceed from baseline establishment toward personalized recommendation modeling.
