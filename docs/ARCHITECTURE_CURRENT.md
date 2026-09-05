# Current Architecture

**Project:** Production E-Commerce Recommendation Platform
**Repository:** `ecommerce-recsys`
**Architecture version:** `foundation-v0`
**Last updated:** 2026-09-05
**Current milestone:** Milestone 0 — Project Charter and Repository Foundation

---

## 1. Purpose of This Document

This document describes the architecture that is **currently implemented** in the repository.

It is not the target architecture.

It must not describe planned components as if they already exist.

Future components such as recommendation models, retrieval systems, ranking models, APIs, caches, vector indexes, monitoring systems, and deployment infrastructure should only appear in this document after they are actually implemented and validated.

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

At the current milestone, there is no executable recommendation system.

The repository currently provides only the project foundation.

Implemented architecture:

```text
ecommerce-recsys
        |
        +-----------------------------+
        |                             |
        v                             v
Project Documentation          Project Directory Skeleton
        |                             |
        |                             |
        +--> PROJECT_CHARTER.md       +--> data/
        +--> PROJECT_STATUS.md        +--> src/
        +--> ARCHITECTURE_CURRENT.md  +--> tests/
                                      +--> benchmarks/
                                      +--> configs/
                                      +--> scripts/
                                      +--> artifacts/
                                      +--> deployment/
```

No data-processing pipeline, recommendation model, API, or deployed runtime currently exists.

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
│   ├── interim/
│   ├── processed/
│   └── raw/
├── deployment/
├── docs/
│   ├── PROJECT_CHARTER.md
│   ├── PROJECT_STATUS.md
│   └── ARCHITECTURE_CURRENT.md
├── notebooks/
├── requirements/
├── scripts/
├── src/
└── tests/
    ├── integration/
    └── unit/
```

Most directories are intentionally empty.

They reserve logical project boundaries but do not imply that those components have already been implemented.

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

### 4.2 Data Directories

Current data structure:

```text
data/
├── raw/
├── interim/
└── processed/
```

Current status:

```text
No dataset has been downloaded.
No data files exist.
No data transformation pipeline exists.
```

Intended responsibilities:

#### `data/raw/`

Reserved for immutable or source-level downloaded data.

No raw data is currently present.

#### `data/interim/`

Reserved for intermediate processing artifacts.

No interim artifacts currently exist.

#### `data/processed/`

Reserved for canonical processed datasets used by later pipelines.

No processed datasets currently exist.

---

## 5. Source Code State

Current source directory:

```text
src/
```

Current status:

```text
EMPTY
```

There is currently no production Python package or application code.

Not yet implemented:

* data ingestion
* schema validation
* preprocessing
* feature engineering
* recommendation baselines
* collaborative filtering
* matrix factorization
* neural retrieval
* candidate generation
* ranking
* re-ranking
* evaluation
* serving
* monitoring

Source-code subpackages will be introduced only when their corresponding milestone begins.

---

## 6. Test Architecture

Current test directories:

```text
tests/
├── integration/
└── unit/
```

Current status:

```text
No tests implemented.
pytest not configured yet.
```

The directories currently represent only intended test boundaries.

### Planned responsibility

`tests/unit/`

Will contain isolated tests for functions and components.

`tests/integration/`

Will contain tests that validate interactions between multiple project components.

These are planned roles, not currently implemented test suites.

---

## 7. Benchmark Architecture

Current directory:

```text
benchmarks/
```

Current status:

```text
EMPTY
```

No benchmark has been created.

No test-user split exists.

No recommendation metric has been implemented.

No benchmark version is frozen.

A benchmark must not be claimed as authoritative until the evaluation milestone creates and validates it.

---

## 8. Artifact Architecture

Current directory:

```text
artifacts/
```

Current status:

```text
EMPTY
```

No model artifacts exist.

No embedding matrices exist.

No ANN indexes exist.

No model manifests exist.

The directory is reserved for future versioned model and serving artifacts.

---

## 9. Configuration Architecture

Current directory:

```text
configs/
```

Current status:

```text
EMPTY
```

There are currently no model, training, evaluation, or serving configurations.

Configuration conventions will be introduced when implementation requirements become concrete.

---

## 10. Script Architecture

Current directory:

```text
scripts/
```

Current status:

```text
EMPTY
```

No executable data, training, evaluation, or artifact-building scripts currently exist.

Scripts will be added as milestones require reproducible command-line workflows.

---

## 11. Notebook Architecture

Current directory:

```text
notebooks/
```

Current status:

```text
EMPTY
```

Notebooks will be used for exploration and analysis only.

They must not become the production execution path of the recommendation system.

The first expected notebook is associated with data understanding and EDA after a dataset is selected.

---

## 12. Deployment Architecture

Current directory:

```text
deployment/
```

Current status:

```text
EMPTY
```

There is currently:

* no Dockerfile
* no Docker Compose configuration
* no cloud deployment
* no infrastructure manifest
* no production environment

Deployment work belongs to later milestones.

---

## 13. CI Architecture

Current directory:

```text
.github/
```

Current status:

```text
No GitHub Actions workflow exists yet.
```

The initial CI quality gate is expected to be introduced during Milestone 0.

The initial expected flow is:

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

This is a planned Milestone 0 component and must not be described as active until the workflow file exists and passes.

---

## 14. Current Runtime Architecture

There is currently **no runtime architecture**.

Specifically:

```text
HTTP Request
    |
    X
```

No service is listening for recommendation requests.

No application process exists.

No model is loaded into memory.

No external service is required.

No database is required.

No vector database exists.

No cache exists.

---

## 15. Current Offline ML Architecture

There is currently **no offline ML pipeline**.

Current state:

```text
Raw Dataset
    |
    X
```

Missing components include:

```text
Dataset
   ->
Validation
   ->
Cleaning
   ->
Canonical Interactions
   ->
Temporal Split
   ->
Model Training
   ->
Evaluation
   ->
Artifacts
```

All of these are future milestones.

---

## 16. Current Dependency Architecture

No Python dependency contract has been frozen yet.

Current state:

```text
Python environment configuration: pending
pyproject.toml: pending
runtime dependencies: pending
development dependencies: pending
```

The project is currently being operated from a Conda shell, but that does not yet represent the project's official reproducible dependency specification.

---

## 17. Current Data Flow

No functional data flow exists yet.

The current project flow is organizational:

```text
Master Roadmap
      |
      v
PROJECT_CHARTER.md
      |
      v
PROJECT_STATUS.md
      |
      v
ARCHITECTURE_CURRENT.md
      |
      v
Future Implementation
```

No user interaction data currently enters the system.

No recommendation output is currently produced.

---

## 18. Current External Dependencies

Runtime external dependencies:

```text
None
```

The repository does not currently require:

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

Some of these may be introduced in future milestones if justified.

---

## 19. Explicitly Not Implemented

The following components are part of the long-term roadmap but do not currently exist.

### Data

* dataset downloader
* canonical event schema
* item schema
* cleaning pipeline
* interaction dataset
* temporal split

### Baselines

* random recommender
* global popularity
* recent popularity
* category popularity

### Collaborative Recommendation

* ItemKNN
* UserKNN
* matrix factorization
* BPR

### Retrieval

* candidate-generator abstraction
* matrix-factorization retrieval
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

### Advanced Modeling

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

* fallback implementation
* cache
* monitoring
* Prometheus
* Grafana
* structured logging

### Infrastructure

* Docker
* Docker Compose
* GitHub Actions
* production deployment

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
Candidate Generator
    ->
Top-N Candidates
```

may become real architecture.

Only validated components should be promoted into this document.

---

## 22. Current Architecture Summary

As of 2026-09-05:

```text
Production E-Commerce Recommendation Platform

IMPLEMENTED
--------------------------------

Git Repository
      |
      +--> Base Directory Structure
      |
      +--> Project Documentation
             |
             +--> PROJECT_CHARTER.md
             +--> PROJECT_STATUS.md
             +--> ARCHITECTURE_CURRENT.md


NOT YET IMPLEMENTED
--------------------------------

Data Pipeline
Evaluation
Baselines
Collaborative Filtering
Matrix Factorization
Candidate Generation
Two-Tower
ANN
Ranking
Re-ranking
Sequential Recommendation
FastAPI
Monitoring
Docker
CI
Cloud Deployment
```

The system is currently in the **project-foundation stage**.

No recommendation behavior exists yet.
