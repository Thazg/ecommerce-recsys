# Production E-Commerce Recommendation System

## 1. Project Identity

**Working Name:** Production E-Commerce Recommendation Platform

**Repository:** `ecommerce-recsys`

**Primary Goal:**
Build a recommendation system for e-commerce interactions that learns from implicit user behavior and ultimately serves personalized Top-K product recommendations through an API and public demo.

The project is intended to demonstrate both recommendation-system knowledge and production ML engineering skills.

---

## 2. Technical objectives

The finished project should demonstrate understanding of:

* implicit-feedback recommendation
* recommendation baselines
* collaborative filtering
* matrix factorization
* candidate generation
* neural retrieval
* learning-to-rank
* sequential recommendation where justified
* recommendation evaluation
* temporal data leakage prevention
* cold-start handling
* diversity and coverage
* offline model pipelines
* online recommendation serving
* observability
* testing
* CI/CD
* containerization
* performance testing
* production deployment

The implementation and evaluation should make each model and engineering decision inspectable and reproducible.

Every significant model or infrastructure decision should have either:

1. measurable experimental evidence, or
2. a clearly documented engineering justification.

---

## 3. Problem Statement

An e-commerce platform contains many products, while each user interacts with only a very small portion of the catalog.

The recommendation system should estimate which products are most relevant to a user based primarily on implicit behavioral signals such as product views, cart actions, and purchases.

Instead of predicting a numeric rating, the system will focus on ranking products and producing a Top-K recommendation list.

The core problem is therefore:

> Given a user's historical or current-session interactions and a catalog of products, retrieve and rank a small set of products that are likely to be relevant for the user's next interactions.

---

## 4. Recommendation Surfaces

The planned system supports the following recommendation surfaces.

### 4.1 Personalized Homepage Recommendations

Input:

* known user or user history

Output:

* personalized Top-K product recommendations

Purpose:

Provide a general recommendation feed representing the user's longer-term interests.

---

### 4.2 Similar-Item Recommendations

Example:

> Because you viewed Product A...

Input:

* an item

Output:

* related or behaviorally similar products

Purpose:

Support product-detail-page recommendation scenarios.

---

### 4.3 Next-Item / Session Recommendation

Status:

**Optional advanced component.**

Input:

* recent ordered interaction history

Output:

* products likely to be interacted with next

This component should only be added after classical and two-stage recommendation baselines have been implemented and evaluated.

---

### 4.4 Cold-Start / Anonymous Recommendations

Users without sufficient history must still receive useful recommendations.

Possible fallback sources may include:

* global popularity
* recent popularity
* category popularity
* session context when available

The exact fallback strategy will be defined after the dataset has been analyzed.

---

## 5. User Interaction Model

The project focuses on **implicit feedback** rather than explicit ratings.

The selected Retailrocket dataset uses these canonical event codes:

* `view`
* `addtocart` (cart addition)
* `transaction` (purchase)

These event types are retained as implicit positive signals. The current
benchmarks treat each event as one interaction and do not apply event-specific
weights.

This records the dataset mapping and current benchmark behavior; future weighted
models require a separately evaluated event-weighting decision.

---

## 6. High-Level Recommendation Architecture

The intended final recommendation flow is:

```text
User Request
    |
    v
User / Session Context
    |
    v
Candidate Generation
    |
    | hundreds of plausible products
    v
Eligibility Filters
    |
    v
Ranking
    |
    v
Re-ranking
    |
    | diversity / deduplication / rules
    v
Top-K Recommendations
    |
    v
Recommendation API
```

Candidate generation and ranking must remain conceptually separate.

Candidate generation answers:

> Which few hundred products are worth considering?

Ranking answers:

> In what order should those candidate products be shown?

---

## 7. Planned Offline Learning Loop

The intended offline flow is:

```text
Raw Interaction Events
        |
        v
Validation / Cleaning
        |
        v
Canonical Interaction Dataset
        |
        v
Temporal Train / Validation / Test Split
        |
        +---------------------+
        |                     |
        v                     v
Model Training          Frozen Benchmark
        |
        v
Model / Embedding / Index Artifacts
        |
        v
Offline Evaluation
        |
        v
Selected Release Candidate
```

Training pipelines must eventually run through scripts or CLI commands rather than depending on notebooks.

---

## 8. Evaluation Philosophy

Recommendation quality must be measured using Top-K ranking metrics rather than relying only on regression metrics such as RMSE.

Planned metrics include:

* Recall@K
* HitRate@K
* MRR@K
* NDCG@K
* Precision@K where meaningful
* Catalog Coverage@K

Additional diagnostics may include:

* diversity
* popularity concentration
* novelty
* candidate recall
* latency
* memory consumption

Initial values of K are expected to include:

* K = 5
* K = 10
* K = 20

The exact benchmark protocol will be formally defined and frozen during the evaluation milestone.

---

## 9. Initial Performance Targets

The project uses initial engineering budgets for production-oriented validation.

These are targets, not claims about current performance.

### Online Recommendation API

For a warm serving process:

- End-to-end recommendation latency: p95 <= 300 ms
- Tail latency: p99 <= 500 ms

The measurement should represent the full recommendation path used by the serving API.

### Serving Memory

Initial target:

- <= 2 GiB RSS for the serving process after required model and retrieval artifacts are loaded.

Memory measurements should distinguish startup, warm runtime, and loaded-model states where practical.

### Cold Start

Cold-start latency is not an initial release gate.

It will be measured later after the model and artifact-loading architecture are known.

### Target Revision Policy

These targets are initial engineering budgets.

They may be revised when benchmark evidence demonstrates that:

1. the target is unrealistic for the selected architecture or workload, or
2. a stricter target is required by measured product behavior.

Any meaningful revision must be recorded in `docs/DECISIONS.md`.

## 10. Temporal Evaluation Rule

User interactions occur over time.

Therefore, the project must avoid leaking future interactions into training data.

Random interaction-level train/test splitting must not be used without explicit justification.

Evaluation uses globally ordered training snapshots and subsequent target
windows. The temporal requirement is:

```text
All events at or before a global cutoff -> training snapshot
Events strictly after that cutoff      -> evaluation window
```

Candidate catalogs and time-varying metadata use the same declared cutoff.
Configuration selection precedes evaluation on later periods. Returning-user
discovery targets and first-time-user targets are reported separately.

The [rolling protocol](ROLLING_EVALUATION_PROTOCOL.md) defines the exact targets,
phase allocation and validity limits. Historical per-user experiments remain
archived under their own protocol.

---

## 11. Model Development Principle

Models will be introduced in increasing order of complexity.

Expected progression:

```text
Random
  |
  v
Popularity
  |
  v
Item-based Collaborative Filtering
  |
  v
Matrix Factorization / BPR
  |
  v
Candidate Generation Architecture
  |
  v
Two-Tower Retrieval
  |
  v
ANN Retrieval
  |
  v
Learning-to-Rank
  |
  v
Sequential Recommendation
```

Advanced models must not replace simpler models without benchmark evidence.

A model that cannot outperform or justify a trade-off against a simple popularity baseline should not be considered successful merely because it is more complex.

---

## 12. Dataset Scope

The project uses the public [Retailrocket interaction dataset](DATASET_CARD.md). Its timestamped views, cart additions, purchases, and item properties support temporal recommendation experiments.

Preferred dataset properties:

* user identifiers
* item identifiers
* timestamped interactions
* realistic implicit-feedback events
* enough interactions to demonstrate collaborative recommendation
* publicly accessible for reproducible research

The selected dataset is documented in the dataset card. Source and derived benchmark inputs are identified by SHA-256 hashes so experiments remain reproducible.

---

## 13. Production Scope

The target system uses infrastructure only where the data volume and measured requirements justify it. The [current architecture](ARCHITECTURE_CURRENT.md) distinguishes implemented components from planned serving work.

The final system should eventually include:

* reproducible offline pipelines
* versioned model artifacts
* recommendation API
* deterministic fallback paths
* model/index version tracking
* unit tests
* integration tests
* Docker deployment
* CI
* metrics and structured logging
* performance benchmarks
* cloud deployment
* public demo

Infrastructure should only be introduced when it solves an actual project requirement.

---

## 14. Explicit Non-Goals

This project must not become:

* a MovieLens tutorial
* a single Jupyter notebook
* a pure vector-similarity search system labeled as recommendation
* a neural model with no baseline comparison
* a UI demo with no rigorous offline evaluation
* an architecture filled with unnecessary infrastructure
* a project where model complexity is treated as success by itself

The initial version does not require:

* real payment processing
* real customer personally identifiable information
* real commercial inventory integration
* internet-scale traffic
* Kafka
* Kubernetes
* a feature store
* microservices

These technologies may only be introduced later if project requirements justify them.

---

## 15. Learning Principle

The project follows the rule:

> Implement the simplest correct system first, measure it, understand it, and only then increase complexity.

The project owner should be able to explain the design and behavior of each major component instead of relying only on generated code.

Important concepts should be understood before the corresponding architecture is introduced.

---

## 16. Engineering Principles

### Reproducibility

Important experiments should record:

* dataset version
* split version
* configuration
* random seed where applicable
* model version
* artifact checksum
* evaluation output

### Evaluation Before Optimization

No sophisticated optimization should happen before a valid baseline and benchmark exist.

### No Benchmark Manipulation

Once an evaluation benchmark is frozen, it must not be modified simply because a later model performs poorly.

A legitimately changed protocol must create a new benchmark version.

### Separation of Responsibilities

The final serving layer should separate:

```text
API
  ->
RecommendationService
  ->
Candidate Generation
  ->
Filtering
  ->
Ranking
  ->
Re-ranking
```

Model and recommendation logic should not be embedded directly in API endpoints.

### Measurement-Driven Infrastructure

Components such as ANN indexes, caches, Redis, Qdrant, or more complex deployment infrastructure must be justified by measurable requirements.

---

## 17. Git and Development Discipline

Development should use small, coherent commits.

Preferred branch naming:

```text
feature/...
test/...
refactor/...
docs/...
fix/...
```

General workflow:

1. implement one coherent task
2. add or update tests where applicable
3. validate locally
4. update relevant documentation
5. commit
6. push at meaningful milestone boundaries or when remote backup/review is useful

Benchmark modifications and large refactors should not be mixed in the same change.

---

## 18. Source-of-Truth Documents

The repository keeps project scope, implementation state, and experiment evidence in separate documents:

### [Project charter](PROJECT_CHARTER.md)

Defines what the project is trying to build and what principles it follows.

### [Project status](PROJECT_STATUS.md)

Tracks the project's current state, completed work, active milestone, blockers, and next tasks.

### [Current architecture](ARCHITECTURE_CURRENT.md)

Describes only the architecture that currently exists.

It must not describe planned components as if they were already implemented.

### [Engineering decisions](DECISIONS.md)

Records important architecture and engineering decisions along with alternatives and rationale.

### [Dataset card](DATASET_CARD.md)

Documents dataset provenance, schemas, filtering rules, and statistics.

### [Rolling evaluation protocol](ROLLING_EVALUATION_PROTOCOL.md)

Defines the current temporal benchmark, cohorts, metrics, and validity limits.

---

## 19. Current Project State

This charter is timeless and does not track implementation progress.

For implemented work and the next milestone, see [project status](PROJECT_STATUS.md) and [current architecture](ARCHITECTURE_CURRENT.md).

---

## 20. Initial project foundation

The initial foundation established:

* project objective is unambiguous
* recommendation surfaces are defined
* project/non-project boundaries are documented
* source-of-truth documents exist
* repository structure exists
* Python development environment is reproducible
* formatter/linter configuration exists
* initial test infrastructure exists
* basic CI quality gate exists
* initial repository state is committed

Model training follows an explicit evaluation design; the current protocol is documented in the [rolling evaluation specification](ROLLING_EVALUATION_PROTOCOL.md).

---

## 21. Definition of Project Success

The project is not considered successful merely because an API can return product IDs.

The completed system should demonstrate an end-to-end ML recommendation lifecycle:

```text
Interaction Data
      ->
Data Validation
      ->
Temporal Evaluation
      ->
Baselines
      ->
Personalized Models
      ->
Candidate Retrieval
      ->
Ranking
      ->
Re-ranking
      ->
Offline Benchmarking
      ->
Artifact Management
      ->
Recommendation API
      ->
Observability
      ->
Performance Validation
      ->
Production Deployment
```

The final system documentation should explain the machine-learning decisions and production-engineering trade-offs with measured evidence.
