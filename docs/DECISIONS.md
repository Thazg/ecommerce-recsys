# Architecture and Engineering Decisions

**Project:** Production E-Commerce Recommendation Platform
**Repository:** `ecommerce-recsys`
**Last updated:** 2026-09-05

---

## 1. Purpose

This document records important architecture, machine-learning, data, evaluation, and engineering decisions made during the project.

Its purpose is to answer questions such as:

* What did we decide?
* Why did we decide it?
* What alternatives were considered?
* What assumptions were made?
* Is the decision permanent or revisitable?

This prevents important project decisions from existing only in chat history or developer memory.

---

## 2. Decision Status

Each decision should use one of the following statuses:

### Proposed

The decision is being considered but has not been validated.

### Accepted

The project currently follows this decision.

### Superseded

A later decision replaced it.

### Rejected

The option was considered but intentionally not selected.

### Experimental

The decision is temporarily being tested and requires evidence before becoming accepted.

---

# ADR-001 — Build a Recommendation System for Implicit Feedback

**Status:** Accepted
**Date:** 2026-09-05

## Context

The project targets an e-commerce environment.

Real e-commerce systems often have behavioral events such as:

* product views
* cart actions
* purchases

rather than explicit user ratings.

The main system output is expected to be a ranked Top-K product list.

## Decision

The project will primarily model **implicit feedback**.

The recommendation problem will be framed as:

> Given the user's previous or current interactions, rank products that are likely to be relevant for future interaction.

The project will not primarily treat the task as numeric rating prediction.

## Rationale

Implicit-feedback recommendation better represents the target e-commerce scenario.

It also allows the project to study:

* sparse interaction data
* positive behavioral signals
* negative sampling
* candidate generation
* Top-K ranking
* cold-start behavior
* ranking evaluation

## Alternatives Considered

### Explicit rating prediction

Rejected as the primary task.

A rating-style dataset would simplify some experiments but would be less aligned with the intended e-commerce system.

### Pure content similarity

Rejected as the primary recommendation approach.

Product similarity can become one recommendation source, but semantic or content similarity alone does not demonstrate personalized collaborative recommendation.

## Consequences

The project will need to reason carefully about:

* what constitutes a positive interaction
* repeated interactions
* confidence or event strength
* negative examples
* ranking metrics

Exact event semantics remain intentionally undefined until the selected dataset is analyzed.

---

# ADR-002 — Do Not Assign Interaction Weights Before Data Analysis

**Status:** Accepted
**Date:** 2026-09-05

## Context

A common simple implementation assigns values such as:

```text
view = 1
cart = 3
purchase = 5
```

However, these values are arbitrary unless supported by data behavior or a model-specific interpretation.

## Decision

No fixed event weights will be selected during Milestone 0.

Interaction semantics and any weighting strategy will be decided only after:

1. a dataset is selected
2. event distributions are inspected
3. repeated behavior is understood
4. the model requirements are known

## Rationale

A purchase is intuitively stronger than a view, but that does not automatically imply that a numerical ratio such as `5:1` is correct.

Different recommendation algorithms may also require different representations of implicit feedback.

## Alternatives Considered

### Hard-code weights immediately

Rejected.

This would introduce an undocumented modeling assumption before understanding the data.

## Consequences

Future data analysis must explicitly document:

* event counts
* event relationships
* repeated views
* carts
* purchases
* any eventual weighting strategy

---

# ADR-003 — Dataset Selection Happens After Project Definition

**Status:** Accepted
**Date:** 2026-09-05

## Context

The project roadmap contains several possible public e-commerce datasets.

Selecting a dataset immediately could cause the project to adapt itself to whatever data happened to be downloaded first.

## Decision

The problem definition and project boundaries will be established before choosing the primary dataset.

Dataset comparison belongs to Milestone 1.

## Rationale

The dataset should support the intended recommendation problem rather than define the problem accidentally.

Selection will consider:

* timestamp availability
* user-item interactions
* event types
* catalog size
* number of users
* item metadata
* sparsity
* reproducibility
* license or usage constraints

## Alternatives Considered

### Download the first available dataset

Rejected.

### Start with MovieLens for convenience

Rejected for the primary portfolio system.

MovieLens can be useful educationally, but this project's target is a realistic e-commerce implicit-feedback setting.

## Consequences

There is no official dataset during Milestone 0.

No code should assume a specific input schema yet.

---

# ADR-004 — Use Temporal Evaluation Rather Than Random Interaction Splitting

**Status:** Accepted in principle
**Date:** 2026-09-05

## Context

Recommendation interactions occur over time.

A random interaction-level split can allow future information to appear in the training data while earlier interactions appear in test data.

This produces unrealistic evaluation.

## Decision

The project will use a temporal evaluation strategy.

The initial expected strategy is similar to:

```text
User history:

interaction 1
interaction 2
interaction 3
interaction 4
interaction 5

Training:
interaction 1-3

Validation:
interaction 4

Test:
interaction 5
```

The exact protocol is not yet frozen.

## Rationale

At real inference time, the system only knows interactions that happened before the recommendation request.

Evaluation should preserve this causal ordering.

## Alternatives Considered

### Random train/test split

Rejected as the default protocol.

It may only be used later for a specific experiment if explicitly justified.

### Global time split

Still under consideration.

Depending on the selected dataset, a global temporal cutoff may better represent the production scenario.

## Consequences

The final split implementation must be decided after inspecting the selected dataset.

Temporal leakage tests should eventually be created.

---

# ADR-005 — Build the Evaluation Harness Before Sophisticated Models

**Status:** Accepted
**Date:** 2026-09-05

## Context

Recommendation systems can easily produce apparently strong results because of:

* data leakage
* inconsistent candidate sets
* incorrect metric implementations
* tuning against test data
* inconsistent user eligibility

## Decision

A reusable offline evaluation harness and frozen benchmark will be created before sophisticated recommendation models.

## Rationale

All models must be evaluated under the same protocol.

The project should be able to answer:

> Did the model actually improve recommendation quality?

rather than:

> Did the model produce recommendations?

## Initial Planned Metrics

* Recall@K
* HitRate@K
* MRR@K
* NDCG@K
* Precision@K where meaningful
* Catalog Coverage@K

Likely initial K values:

```text
5
10
20
```

## Consequences

Model development is intentionally delayed until the evaluation foundation exists.

---

# ADR-006 — Popularity Must Exist Before Advanced Personalized Models

**Status:** Accepted
**Date:** 2026-09-05

## Context

A recommendation model can look sophisticated while providing little value over recommending popular products.

## Decision

The first meaningful benchmarked recommendation systems will include simple non-personalized baselines.

At minimum:

* random
* global popularity
* recent popularity

Category popularity may be added if useful metadata exists.

## Rationale

Popularity provides a strong sanity-check baseline.

A personalized model should either:

1. beat it on relevant recommendation metrics, or
2. provide another measurable and justified advantage.

## Alternatives Considered

### Start directly with matrix factorization

Rejected.

### Start directly with Two-Tower

Rejected.

### Start directly with SASRec

Rejected.

## Consequences

A neural model will not be considered successful simply because it is technically more complex.

---

# ADR-007 — Increase Model Complexity Incrementally

**Status:** Accepted
**Date:** 2026-09-05

## Decision

The expected learning progression is:

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
Ranker
   |
   v
Sequential Recommendation
```

## Rationale

Each stage introduces an important recommendation-system concept.

Skipping stages would make it harder to determine where improvements originate.

It would also weaken the owner's ability to explain the system during interviews.

## Consequences

Advanced architectures must be justified by benchmark results or identified engineering needs.

---

# ADR-008 — Candidate Generation and Ranking Will Be Separate Concepts

**Status:** Accepted at design level
**Date:** 2026-09-05

## Context

Large recommendation systems cannot accurately score an entire catalog with an expensive ranker for every request.

A common production architecture uses two stages.

## Decision

The target system will distinguish between:

### Candidate Generation

Goal:

Reduce the catalog to a few hundred plausible items.

### Ranking

Goal:

Order those candidates more accurately and return the final Top-K items.

Conceptual flow:

```text
Full Catalog
     |
     v
Candidate Generator
     |
     | 100-1000 candidates
     v
Ranker
     |
     | Top 10-20
     v
Final Recommendations
```

## Important

This is currently an architectural direction only.

Neither candidate generation nor ranking is implemented yet.

## Consequences

Future evaluation should include candidate-specific metrics such as:

```text
Candidate Recall@N
```

in addition to final ranking metrics.

---

# ADR-009 — Do Not Introduce ANN Until Exact Retrieval Is Measured

**Status:** Accepted
**Date:** 2026-09-05

## Context

The roadmap may eventually use:

* FAISS
* Qdrant

for approximate nearest-neighbor retrieval.

However, the project currently has no embeddings, no dataset, and no measured retrieval latency.

## Decision

The project will implement or measure exact retrieval before introducing ANN infrastructure.

ANN will only be added when there is a measurable reason.

## Rationale

Approximate nearest-neighbor systems introduce:

* index configuration
* quality-speed trade-offs
* additional artifacts
* additional operational complexity

Without measurement, this complexity has no demonstrated value.

## Alternatives Considered

### Start immediately with Qdrant

Rejected.

### Start immediately with FAISS ANN indexes

Rejected.

## Consequences

ANN selection remains undecided.

FAISS and Qdrant are candidate technologies, not current dependencies.

---

# ADR-010 — Do Not Select the Deep-Learning Stack Before It Is Needed

**Status:** Accepted
**Date:** 2026-09-05

## Context

The long-term roadmap includes neural recommendation models such as Two-Tower and potentially sequential models.

PyTorch is the expected deep-learning framework.

However, Milestone 0 does not contain neural modeling.

## Decision

PyTorch will not be introduced merely because it is expected later.

Dependencies will be added when the corresponding implementation requires them.

## Rationale

This keeps the project dependency surface smaller and makes milestone boundaries clearer.

## Consequences

PyTorch is a planned technology, not a current project dependency.

---

# ADR-011 — Keep Notebooks for Exploration, Not Production Pipelines

**Status:** Accepted
**Date:** 2026-09-05

## Context

Jupyter notebooks are useful for:

* EDA
* visualization
* experimentation
* educational analysis

but are poor as the only production execution path.

## Decision

Notebooks may be used for exploratory analysis.

Production operations must eventually exist as reproducible Python modules, scripts, or CLI commands.

Examples include:

* data preparation
* model training
* benchmark execution
* artifact building

## Consequences

A successful notebook experiment must eventually be converted into reusable project code when it becomes part of the system.

---

# ADR-012 — Do Not Pre-create the Full Source-Code Architecture

**Status:** Accepted
**Date:** 2026-09-05

## Context

The master roadmap includes future packages such as:

```text
features/
models/
retrieval/
ranking/
reranking/
evaluation/
serving/
monitoring/
```

None of these components currently exist.

## Decision

The project will not create every future subdirectory and placeholder module during Milestone 0.

New source-code boundaries will be introduced when the corresponding implementation begins.

## Rationale

Creating the entire future architecture immediately can make the repository look more mature than it actually is.

It can also encourage future contributors or AI assistants to assume nonexistent components have already been implemented.

## Consequences

The current `src/` directory may remain nearly empty during the foundation milestone.

`ARCHITECTURE_CURRENT.md` remains the authority on what actually exists.

---

# ADR-013 — Maintain Separate Project Charter, Status, Architecture, and Decisions Documents

**Status:** Accepted
**Date:** 2026-09-05

## Context

Different types of project information change at different rates.

Mixing everything into one README makes it difficult to distinguish:

* project goals
* current implementation
* current progress
* historical decisions

## Decision

The project will maintain separate source-of-truth files.

### `PROJECT_CHARTER.md`

Answers:

> What are we trying to build?

### `PROJECT_STATUS.md`

Answers:

> Where are we now?

### `ARCHITECTURE_CURRENT.md`

Answers:

> What actually exists?

### `DECISIONS.md`

Answers:

> Why did we choose this approach?

## Consequences

Future work should update the correct document rather than using README as the only project record.

---

# ADR-014 — Avoid Infrastructure Without Demonstrated Need

**Status:** Accepted
**Date:** 2026-09-05

## Context

Production ML projects can accumulate unnecessary infrastructure.

Potential technologies include:

* Redis
* Kafka
* Qdrant
* PostgreSQL
* MLflow
* Kubernetes
* feature stores
* microservices

## Decision

Infrastructure will be introduced only when a concrete requirement or measurement justifies it.

## Example

Bad rationale:

> Use Redis because production systems use Redis.

Better rationale:

> p95 latency is dominated by repeatedly loading the same precomputed recommendations, so an online cache may reduce response latency.

## Consequences

The architecture should remain as simple as possible while satisfying current project requirements.

---

# ADR-015 — Build a Modular Monolith Before Considering Microservices

**Status:** Accepted at project level
**Date:** 2026-09-05

## Context

The final system will contain several logical components:

* candidate retrieval
* ranking
* filtering
* re-ranking
* serving

These do not automatically require separate network services.

## Decision

The initial production application will use a modular monolithic architecture.

Logical boundaries should exist in Python code without prematurely splitting components into independent services.

## Rationale

At portfolio scale, microservices would introduce unnecessary:

* deployment complexity
* network failures
* distributed tracing requirements
* configuration overhead

## Consequences

Candidate generation and ranking may be separate modules while running inside the same recommendation service.

This decision may be revisited if future scale or deployment requirements provide evidence for decomposition.

---

# ADR-016 — Keep Recommendation Logic Outside API Routes

**Status:** Accepted at design level
**Date:** 2026-09-05

## Context

The final roadmap includes a FastAPI service.

Embedding recommendation logic directly into HTTP endpoint handlers would tightly couple serving transport with machine-learning/business logic.

## Decision

The intended application boundary is:

```text
FastAPI
   |
   v
RecommendationService
   |
   v
Candidate Generators
   |
   v
Filters
   |
   v
Ranker
   |
   v
Re-ranker
```

## Important

FastAPI and RecommendationService are not currently implemented.

This decision governs future implementation.

## Consequences

Recommendation logic should remain testable without starting an HTTP server.

---

# ADR-017 — Freeze Benchmarks Rather Than Editing Them After Model Results

**Status:** Accepted
**Date:** 2026-09-05

## Context

Changing test users or evaluation definitions after seeing model results can bias comparisons.

## Decision

Once a benchmark version is validated and frozen, it will be treated as immutable historical evaluation provenance.

If the protocol legitimately changes, a new benchmark version must be created.

Example:

```text
benchmarks/v1/
benchmarks/v2/
```

rather than modifying `v1`.

## Consequences

Future model performance must not be improved by silently changing the benchmark.

---

# ADR-018 — Use Small Coherent Git Commits

**Status:** Accepted
**Date:** 2026-09-05

## Decision

Commits should represent one understandable change whenever practical.

Examples:

```text
docs: establish project source-of-truth documents
chore: configure python project environment
test: add evaluation metric tests
feat: implement popularity recommender
```

Large architecture refactors should not be mixed with benchmark changes.

## Rationale

Small commits improve:

* reviewability
* debugging
* rollback
* project-history quality
* recruiter readability

## Consequences

Work may use feature branches where useful.

Pushes do not need to happen after every commit, but remote pushes should occur at useful milestone boundaries or when backup/review is desirable.

---

# ADR-019 — Current Windows Development Environment Is Not the Production Contract

**Status:** Accepted
**Date:** 2026-09-05

## Context

Development is currently occurring from a Windows PowerShell environment using Conda.

## Decision

The developer machine configuration is not considered the definitive production runtime contract.

Project dependencies and runtime assumptions must eventually be represented through repository-controlled configuration.

Examples:

* `pyproject.toml`
* dependency files
* Docker configuration
* environment configuration

## Rationale

The system should eventually be reproducible outside the original developer machine.

## Consequences

Local Conda state alone must not be required to reproduce the project.

---

# ADR-020 — Current Architecture Must Reflect Reality, Not the Roadmap

**Status:** Accepted
**Date:** 2026-09-05

## Context

The master roadmap contains the complete intended project architecture.

Future ChatGPT or coding-agent sessions may incorrectly assume planned components already exist.

# ADR-021 — Establish Initial Serving Performance Budgets

**Status:** Accepted  
**Date:** 2026-09-05

# ADR-022 — Select ItemKNN as the Primary Collaborative Filtering Baseline

**Status:** Accepted

**Date:** 2026-09-07

## Context

Milestone 4 evaluated several recommendation baselines under the same temporal train/test evaluation protocol.

The evaluated models were:

* Global Popularity
* Recent Popularity
* ItemKNN
* ALS Matrix Factorization

The benchmark used the training split for model fitting and the frozen test split for final evaluation.

The test set contains 200,028 warm-start users, with one held-out target item per user.

## Decision

ItemKNN is selected as the primary collaborative-filtering baseline and current candidate-generation model for the next stage of the project.

ALS will be retained as a secondary latent-factor baseline.

Global Popularity will be retained as a fallback recommendation strategy.

Recent Popularity will be retained as a temporal baseline for comparison, but it is not selected as the primary recommendation approach under the current benchmark configuration.

## Evidence

Under the current dataset, temporal split, implicit-feedback representation, and model configurations, ItemKNN achieved the strongest offline ranking performance among the evaluated baselines.

At K=20:

* ItemKNN HR@20: 5.57%
* ALS HR@20: 3.06%
* Recent Popularity HR@20: 0.98%
* Global Popularity HR@20: 1.14%

ItemKNN also achieved the strongest MRR and NDCG results.

ItemKNN MRR@20 was 2.08%, compared with 1.01% for ALS.

ItemKNN NDCG@20 was 2.86%, compared with 1.46% for ALS.

The improvement was consistent across K=5, 10, and 20.

## Catalog Coverage

ItemKNN recommended 60,840 unique items from a catalog of 235,061 items, corresponding to 25.88% catalog coverage.

This was substantially higher than:

* ALS: 1.51%
* Global Popularity: 0.0085%
* Recent Popularity: 0.0085%

The recommendation distribution is head-heavy but does not collapse onto a very small set of products.

The top 10 items account for 3.90% of recommendation slots.

The top 100 items account for 14.84%.

The top 1,000 items account for 42.24%.

This indicates that ItemKNN combines broad catalog coverage with a realistic popularity concentration rather than recommending only a small number of globally dominant items.

## Limitations

ItemKNN currently has a significant candidate-availability limitation.

16,168 of 200,028 test users received no recommendations, corresponding to approximately 8.08% of evaluation users.

This is not user-level cold start because all test users are present in the training data.

The primary issue is sparse item history.

The training data contains 228,392 unique items, of which 144,315 items have fewer than five interactions.

With `min_item_interactions=5`, only 84,077 items are included in the ItemKNN index.

Therefore, a substantial portion of the catalog is outside the current ItemKNN item space.

Some users also have indexed history but still produce no usable candidate because their indexed history items have no positive-similarity neighbors or their available neighbors have already been seen.

## Interpretation

The benchmark suggests that the current dataset contains a strong item co-occurrence signal.

ItemKNN directly models item-item relationships derived from user interaction history.

This appears to fit the current interaction structure better than the evaluated ALS configuration.

However, the result does not imply that ItemKNN is universally superior to matrix factorization.

ALS was evaluated using a fixed configuration and has not yet undergone validation-based hyperparameter tuning.

The current decision therefore applies only to the present benchmark, dataset, interaction representation, and configurations.

## Production Implications

ItemKNN should not yet be considered production-ready solely because it achieved the strongest offline benchmark result.

The current system must eventually address:

* empty recommendation sets
* cold and new-item handling
* candidate availability
* validation-based hyperparameter tuning
* serving latency
* memory usage
* fallback behavior
* integration with future ranking components

Global Popularity should remain available as a fallback when the personalized candidate generator cannot provide sufficient recommendations.

## Future Reconsideration

This decision may be revisited after:

1. ItemKNN hyperparameter experiments are evaluated on the validation split.

2. ALS is tuned using validation data.

3. Additional candidate-generation approaches are implemented.

4. New-item and cold-start strategies are introduced.

5. Candidate Recall@N is evaluated.

6. Serving performance is measured.

7. A downstream ranking model is introduced.

The final production recommendation architecture should be selected based on both recommendation quality and engineering constraints, rather than offline ranking metrics alone.


## Context

The project needs measurable engineering targets before production serving is implemented.

No recommendation service exists yet, so the targets are initial budgets rather than measured performance.

## Decision

The initial serving targets are:

- p95 end-to-end recommendation latency <= 300 ms
- p99 end-to-end recommendation latency <= 500 ms
- serving process memory <= 2 GiB RSS after required model and retrieval artifacts are loaded

Cold-start latency will be measured later but is not an initial release gate.

## Rationale

The targets are intended to provide a practical portfolio-scale production budget without prematurely forcing infrastructure choices.

The project should measure the simplest architecture first.

If measured performance violates the budget, optimization or infrastructure changes should be justified by the measurements.

## Consequences

Future performance benchmarks must report:

- p50
- p95
- p99
- memory usage

Performance optimizations such as caching or ANN retrieval should be introduced only when benchmark results justify them.

## Decision

`docs/ARCHITECTURE_CURRENT.md` will always describe the repository as it actually exists.

Planned components remain in:

* the project charter
* roadmap
* future milestone plans

until implemented and validated.

## Consequences

For example, during the current milestone:

```text
Two-Tower: NOT IMPLEMENTED
Ranker: NOT IMPLEMENTED
FastAPI: NOT IMPLEMENTED
Qdrant: NOT IMPLEMENTED
Docker: NOT IMPLEMENTED
```

even though all may appear in the long-term roadmap.

---

# Decision Log Summary

# Decision Log Summary

| ADR     | Decision                                             | Status                    |
| ------- | ---------------------------------------------------- | ------------------------- |
| ADR-001 | Implicit-feedback recommendation                     | Accepted                  |
| ADR-002 | Delay interaction weighting                          | Accepted                  |
| ADR-003 | Define project before selecting dataset              | Accepted                  |
| ADR-004 | Temporal evaluation                                  | Accepted in principle     |
| ADR-005 | Evaluation before sophisticated models               | Accepted                  |
| ADR-006 | Popularity baseline first                            | Accepted                  |
| ADR-007 | Incremental model complexity                         | Accepted                  |
| ADR-008 | Separate candidate generation and ranking            | Accepted at design level  |
| ADR-009 | Measure exact retrieval before ANN                   | Accepted                  |
| ADR-010 | Delay deep-learning dependencies                     | Accepted                  |
| ADR-011 | Notebooks for exploration only                       | Accepted                  |
| ADR-012 | Do not pre-create full architecture                  | Accepted                  |
| ADR-013 | Separate source-of-truth documents                   | Accepted                  |
| ADR-014 | Infrastructure requires justification                | Accepted                  |
| ADR-015 | Modular monolith before microservices                | Accepted at project level |
| ADR-016 | Recommendation logic outside API routes              | Accepted at design level  |
| ADR-017 | Frozen benchmark versions                            | Accepted                  |
| ADR-018 | Small coherent Git commits                           | Accepted                  |
| ADR-019 | Local Windows environment is not production contract | Accepted                  |
| ADR-020 | Current architecture must reflect reality            | Accepted                  |
| ADR-021 | Establish initial serving performance budgets        | Accepted                  |
| ADR-022 | Select ItemKNN as primary collaborative filtering baseline | Accepted |
---

# Future Decision Topics

The following decisions are intentionally unresolved.

## Dataset

Pending:

* primary dataset selection
* dataset version
* license validation

## Data Semantics

Pending:

* duplicate handling
* event weighting
* minimum user activity
* minimum item activity
* core filtering rules

## Evaluation

Pending:

* leave-last-out vs global temporal split
* exact user eligibility requirements
* exact K values
* negative/candidate evaluation strategy

## Baselines

Pending:

* recent-popularity window
* ItemKNN similarity details
* matrix-factorization implementation

## Neural Retrieval

Pending:

* Two-Tower features
* loss function
* negative sampling strategy

## ANN

Pending:

* whether ANN is required
* FAISS vs Qdrant
* ANN index configuration

## Ranking

Pending:

* LightGBM vs XGBoost
* ranking objective
* feature set

## Performance

Pending:

* validation of the initial p95 latency target
* validation of the initial p99 latency target
* validation of the serving memory target
* cold-start performance budget
* whether optimization requires caching
* whether optimization requires ANN retrieval
* whether additional architectural changes are required to satisfy the performance budget

The initial engineering targets are currently defined by ADR-021:

* p95 end-to-end recommendation latency <= 300 ms
* p99 end-to-end recommendation latency <= 500 ms
* serving process memory <= 2 GiB RSS after required model and retrieval artifacts are loaded

These are initial engineering budgets, not measured results.

They should be validated through performance benchmarking after the serving architecture has been implemented.

## Serving

Pending:

* exact API contract
* caching strategy
* artifact-loading design
* recommendation-service lifecycle
* fallback behavior

## Deployment

Pending:

* cloud provider
* resource requirements
* artifact storage
* rollout strategy
    
These decisions should remain unresolved until the relevant milestone provides enough information to make them responsibly.

