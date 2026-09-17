Current Architecture

**Project:** Production E-Commerce Recommendation Platform

**Repository:** `ecommerce-recsys`

**Architecture version:** `offline-recsys-v1`

**Last updated:** 2026-09-12

**Current milestone:** Milestone 5 — Personalized Recommendation Completed

---

## 1. Purpose of This Document

This document describes the architecture that is **currently implemented** in the repository.

It is not the target architecture.

It must not describe planned components as if they already exist.

Future components such as candidate-generation services, ranking models, APIs, caches, vector indexes, monitoring systems, and deployment infrastructure should only appear in this document after they are actually implemented and validated.

The long-term project direction is defined separately in:

```text

docs/PROJECT_CHARTER.md

```

The current project state is tracked in:

```text

docs/PROJECT_STATUS.md

```

---

## 2. Current System State

The repository currently provides an executable offline recommendation and evaluation system.

Implemented architecture:

```text

ecommerce-recsys

    |

    +-----------------------------+

    |                             |

    v                             v

Project Documentation Offline Recommendation System

                                  |

                                  +--> Processed Dataset

                                  +--> Temporal Evaluation Split

                                  +--> Recommendation Models

                                  +--> Evaluation Harness

                                  +--> Benchmark Artifacts

                                  +--> Analysis Scripts

```

The current system supports:

* processed interaction data

* temporal train / validation / test splitting

* recommendation baselines

* personalized ItemKNN recommendation

* implicit-feedback ALS / Matrix Factorization

* offline recommendation evaluation

* benchmark generation

* recommendation coverage analysis

* recommendation concentration analysis

There is currently no production online-serving runtime.

---

## 3. Repository Architecture

Current repository structure:

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

│ ├── PROJECT_CHARTER.md

│ ├── PROJECT_STATUS.md

│ ├── ARCHITECTURE_CURRENT.md

│ ├── DATA_CONTRACT.md

│ ├── DATASET_CARD.md

│ ├── DATA_QUALITY_REPORT.md

│ ├── EVALUATION_PROTOCOL.md

│ └── BASELINE_REPORT.md

├── notebooks/

├── requirements/

├── scripts/

├── src/

└── tests/

├── integration/

└── unit/

```

The repository now contains implemented data, evaluation, recommendation, benchmark, and analysis components.

Some directories remain reserved for future milestones.

---

## 4. Current Components

### 4.1 Documentation Layer

Current implemented documentation:

#### `docs/PROJECT_CHARTER.md`

Defines:

* project purpose

* recommendation-system scope

* expected recommendation surfaces

* learning principles

* production principles

* non-goals

* high-level future direction

This document describes what the project intends to become.

---

#### `docs/PROJECT_STATUS.md`

Defines:

* current milestone

* completed work

* active work

* known blockers

* next tasks

* current validation state

This document is expected to change frequently.

---

#### `docs/ARCHITECTURE_CURRENT.md`

Defines:

* architecture that exists now

* implemented system boundaries

* current runtime state

* explicit non-existent components

This document must not contain speculative implementation claims.

---

### 4.2 Data Layer

Current processed data structure:

```text

data/

├── raw/

├── interim/

└── processed/

├── interactions.parquet

├── items.parquet

├── train.parquet

├── val.parquet

└── test.parquet

```

The processed interaction dataset contains implicit user behavior.

The processed catalog contains item-level metadata.

The temporal split produces training, validation, and test datasets used by the recommendation evaluation pipeline.

#### `data/raw/`

Reserved for source-level downloaded data.

#### `data/interim/`

Reserved for intermediate processing artifacts.

#### `data/processed/`

Contains canonical datasets consumed by recommendation and evaluation components.

---

## 5. Source Code State

Current source directory:

```text

src/ecommerce_recsys/

```

The source package now contains implemented data, evaluation, and recommendation components.

Current logical structure:

```text

src/ecommerce_recsys/

├── data/

├── evaluation/

└── recommendation/

```

Implemented responsibilities include:

* data schema and processing

* temporal data splitting

* recommendation metrics

* benchmark evaluation

* recommendation models

Current recommendation models include:

* Random Recommender

* Global Popularity

* Recent Popularity

* Category Popularity

* ItemKNN

* ALS / Matrix Factorization

Neural retrieval, candidate generation, ranking, and re-ranking are not yet implemented.

---

## 6. Test Architecture

Current test directories:

```text

tests/

├── integration/

└── unit/

```

The unit test suite validates isolated recommendation, evaluation, data, and model behavior.

Current validation includes tests for:

* recommendation models

* recommendation metrics

* temporal splitting

* benchmark evaluation

* ItemKNN behavior

* Matrix Factorization behavior

* popularity models

The latest known unit-test result is:

```text

56 passed, 1 warning

```

Integration-test infrastructure exists but the project is currently primarily validated through unit tests and offline benchmark execution.

---

## 7. Benchmark Architecture

Current benchmark structure:

```text

benchmarks/

├── baseline/

│ └── baseline_v1.json

└── ...

```

The benchmark system evaluates recommendation models using the shared evaluation harness.

Current evaluation outputs include:

* Recall@K / Hit Rate@K

* MRR@K

* NDCG@K

* Coverage

* average recommendation latency

* P50 latency

* P95 latency

* P99 latency

The canonical Milestone 4 baseline artifact is:

```text

benchmarks/baseline/baseline_v1.json

```

This artifact remains frozen.

Milestone 5 introduced separate ItemKNN experiment and benchmark artifacts without modifying the frozen baseline snapshot.

---

## 8. Artifact Architecture

Current artifact directory:

```text

artifacts/

```

No production model-serving artifacts are currently required.

Offline benchmark and experiment outputs are stored under the benchmark structure.

Current ItemKNN experiment artifacts include:

```text

benchmarks/item_knn_shrinkage_sweep.csv

benchmarks/item_knn_final.csv

```

No ANN indexes or production model registry artifacts currently exist.

---

## 9. Configuration Architecture

Current directory:

```text

configs/

```

The project currently uses model defaults and explicit experiment configuration inside the implemented recommendation components and benchmark scripts.

The current ItemKNN configuration is:

```text

n_neighbors = 20

min_item_interactions = 5

shrinkage_lambda = 100

```

The ALS implementation currently uses:

```text

factors = 128

iterations = 20

regularization = 0.01

```

This is the M6 validation-selected final configuration (see `benchmarks/mf/als_final_v1.json` and `docs/MF_EXPERIMENT_REPORT.md`). The code default in `MatrixFactorizationRecommender` remains `64/20/0.01` for backward-compatible baselines; M4 baseline numbers in `benchmarks/baseline/baseline_v1.json` use factors 64.

These configurations are implementation-level model settings rather than a production configuration-management system.

A dedicated configuration architecture may be introduced later if model experimentation requires it.

---

## 10. Script Architecture

Current script directory:

```text

scripts/

```

Implemented scripts cover:

* data processing

* dataset splitting

* EDA

* baseline benchmarking

* ItemKNN shrinkage experiments

* final ItemKNN benchmarking

* ItemKNN candidate-availability analysis

* recommendation concentration analysis

Scripts provide reproducible command-line workflows for offline experimentation.

They are not production service entrypoints.

---

## 11. Notebook Architecture

Current directory:

```text

notebooks/

```

Notebooks are used for exploration and analysis only.

They are not the production execution path of the recommendation system.

The primary production-oriented logic remains in:

```text

src/

```

and reproducible experiment workflows remain in:

```text

scripts/

```

---

## 12. Deployment Architecture

Current directory:

```text

deployment/

```

Current status:

```text

NOT IMPLEMENTED

```

There is currently:

* no production recommendation API

* no Dockerized recommendation service

* no cloud recommendation deployment

* no production infrastructure manifest

Deployment work belongs to later milestones.

---

## 13. CI Architecture

Current directory:

```text

.github/

```

The repository has an established CI quality gate.

Current conceptual flow:

```text

Checkout

|

v

Install Python

|

v

Install Dependencies

|

v

Lint

|

v

Tests

```

The CI pipeline validates repository quality and test execution.

CI does not currently deploy a recommendation service.

---

## 14. Current Runtime Architecture

There is currently **no online runtime architecture**.

Specifically:

```text

HTTP Request

|

X

```

No production service is listening for recommendation requests.

No recommendation API is currently implemented.

The current system is an offline ML and evaluation system.

The implemented execution path is:

```text

Command / Script

  |

  v

Processed Dataset

  |

  v

Recommendation Model

  |

  v

Top-K Recommendations

  |

  v

Evaluation Harness

  |

  v

Benchmark / Analysis Artifact

```

---

## 15. Current Offline ML Architecture

The project now contains a functional offline ML recommendation pipeline.

Current flow:

```text

Processed Interactions

    |

    v

Temporal Train / Validation / Test Split

    |

    +----------------------------+

    |                            |

    v                            v

Recommendation Models Evaluation Harness

    |                            |

    |                            v

    |                     Recommendation Metrics

    |                            |

    +------------->--------------+

                 |

                 v

          Benchmark Artifacts

```

Current recommendation model layer:

```text

Recommendation Model

    |

    +-- Random

    +-- Global Popularity

    +-- Recent Popularity

    +-- Category Popularity

    +-- ItemKNN

    +-- ALS / Matrix Factorization

```

The system currently supports personalized recommendation through ItemKNN and ALS.

Candidate generation as a separate architectural layer has not yet been introduced.

---

## 16. Current Dependency Architecture

The project uses a Python dependency contract defined through the repository's packaging and requirement configuration.

Core development dependencies include:

* Python 3.13

* pytest

* Ruff

* NumPy

* pandas

* SciPy

* scikit-learn

* implicit

The implicit recommendation dependency currently provides the ALS implementation.

The project does not yet require production-serving dependencies such as FastAPI, Redis, Kafka, or a vector database.

---

## 17. Current Data Flow

The current functional data flow is:

```text

Processed Interaction Dataset

    |

    v

Temporal Split

    |

    +----------------------+

    |                      |

    v                      v

Training Data Validation / Test

    |                      |

    v                      |

Recommendation Model |

    |                      |

    +----------+-----------+

               |

               v

         Top-K Recommendations

               |

               v

        Evaluation Harness

               |

               v

    Metrics + Coverage + Latency

               |

               v

    Benchmark / Analysis Artifacts

```

The current pipeline is offline.

No real-time user request currently enters the recommendation system.

---

## 18. Current External Dependencies

Current ML dependencies include:

```text

NumPy

pandas

SciPy

scikit-learn

implicit

```

The current offline recommendation system does not require:

* Qdrant

* PostgreSQL

* Redis

* Kafka

* MLflow

* FastAPI

* PyTorch

* LightGBM

* Docker

* cloud services

Some of these may be introduced in future milestones if justified by the architecture.

---

## 19. Explicitly Not Implemented

The following components are part of the long-term roadmap but do not currently exist.

### Retrieval Architecture

* candidate-generator abstraction

* hybrid candidate generation

* Two-Tower model

* ANN index

* FAISS

* Qdrant

### Ranking

* ranking dataset

* ranking features

* LightGBM ranker

* XGBoost ranker

* learned re-ranking

### Advanced Modeling

* BPR production model

* neural retrieval

* sequential recommender

* GRU recommender

* SASRec

* diversity re-ranker

* novelty re-ranker

### Serving

* FastAPI

* RecommendationService

* recommendation endpoints

* item-similarity endpoint

* health endpoint

* readiness endpoint

### Reliability

* production fallback architecture

* cache

* online monitoring

* Prometheus

* Grafana

* structured production logging

### Infrastructure

* Docker

* Docker Compose

* production deployment

* cloud infrastructure

These components must not be assumed to exist by future contributors or AI assistants.

---

## 20. Planned Architecture vs Current Architecture

The project intentionally distinguishes between:

```text

PROJECT_CHARTER

"What do we eventually want to build?"

```

and:

```text

ARCHITECTURE_CURRENT

"What actually exists right now?"

```

For example:

The project charter may describe:

```text

Candidate Generation

->

Ranking

->

Re-ranking

```

but the current architecture correctly reports:

```text

Candidate Generation: NOT IMPLEMENTED

Ranking: NOT IMPLEMENTED

Re-ranking: NOT IMPLEMENTED

```

The current architecture instead contains:

```text

Temporal Evaluation

->

Recommendation Models

->

Top-K Recommendations

->

Offline Evaluation

```

This distinction must be maintained throughout the project.

---

## 21. Architecture Change Rule

Whenever a meaningful component is implemented and validated, this document should be updated.

Examples:

After data foundation:

```text

Raw Dataset

->

Validation

->

Canonical Interactions

```

may become part of the current architecture.

After evaluation foundation:

```text

Canonical Interactions

->

Temporal Split

->

Evaluator

```

may be added.

After recommendation models:

```text

User History

->

Personalized Recommender

->

Top-N Recommendations

```

may become part of the current architecture.

After candidate generation is implemented:

```text

User History

->

Candidate Generators

->

Candidate Set

->

Ranking

```

may become part of the current architecture.

Only validated components should be promoted into this document.

---

## 22. Current Architecture Summary

As of 2026-09-12:

```text

Production E-Commerce Recommendation Platform

IMPLEMENTED

--------------------------------

Repository Foundation

    |

    +--> Project Documentation

    |

    +--> Data Processing

    |

    +--> Temporal Evaluation Split

    |

    +--> Recommendation Models

    |       |

    |       +--> Random

    |       +--> Global Popularity

    |       +--> Recent Popularity

    |       +--> Category Popularity

    |       +--> ItemKNN

    |       +--> ALS / Matrix Factorization

    |

    +--> Unified Evaluation Harness

    |

    +--> Benchmark Artifacts

    |

    +--> Offline Model Analysis




NOT YET IMPLEMENTED

--------------------------------

Candidate Generation Architecture

Hybrid Retrieval

Two-Tower Retrieval

ANN

Ranking

Re-ranking

Sequential Recommendation

Online Recommendation API

Caching

Online Monitoring

Production Infrastructure

Cloud Deployment

```

The system is currently in the **offline personalized recommendation stage**.

The project has progressed beyond the initial foundation and baseline stages.

Milestones 0–5 have established:

* a reproducible data foundation

* temporal evaluation

* non-personalized baselines

* personalized ItemKNN recommendation

* implicit-feedback ALS / Matrix Factorization

* model-level benchmarking

* recommendation coverage and concentration analysis

The next architectural step is to deepen matrix-factorization modeling and then introduce an explicit candidate-generation layer.

Production serving architecture should remain deferred until the retrieval and ranking strategy has been established and validated.