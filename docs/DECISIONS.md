Architecture and Engineering Decisions

Project: Production E-Commerce Recommendation Platform

Repository: ecommerce-recsys

Last updated: 2026-10-04

1. Purpose

This document records important architecture, machine-learning, data, evaluation, and engineering decisions made during the project.

Its purpose is to answer questions such as:

What did we decide?
Why did we decide it?
What alternatives were considered?
What assumptions were made?
Is the decision permanent or revisitable?

This prevents important project decisions from existing only in chat history or developer memory.

This document records both historical decisions and decisions that define the current system.

2. Decision Status

Each decision should use one of the following statuses:

Proposed

The decision is being considered but has not been validated.

Accepted

The project currently follows this decision.

Superseded

A later decision replaced it.

Rejected

The option was considered but intentionally not selected.

Experimental

The decision is temporarily being tested and requires evidence before becoming accepted.

ADR-001 — Build a Recommendation System for Implicit Feedback

Status: Accepted

Date: 2026-09-05

Context

The project targets an e-commerce environment.

Real e-commerce systems often have behavioral events such as:

product views
cart actions
purchases

rather than explicit user ratings.

The main system output is expected to be a ranked Top-K product list.

Decision

The project will primarily model implicit feedback.

The recommendation problem is framed as:

Given a user's previous interactions, rank products that are likely to be relevant for a future interaction.

The project does not primarily treat the task as numeric rating prediction.

Rationale

Implicit-feedback recommendation better represents the target e-commerce scenario.

It also allows the project to study:

sparse interaction data
positive behavioral signals
negative sampling
candidate generation
Top-K ranking
cold-start behavior
ranking evaluation
Alternatives Considered
Explicit rating prediction

Rejected as the primary task.

A rating-style dataset would simplify some experiments but would be less aligned with the intended e-commerce system.

Pure content similarity

Rejected as the primary recommendation approach.

Product similarity can become one recommendation source, but semantic or content similarity alone does not demonstrate personalized collaborative recommendation.

Consequences

The system uses implicit user-item interaction data and evaluates models primarily through Top-K ranking metrics rather than rating prediction metrics.

The exact representation of interaction strength remains model-dependent.

ADR-002 — Avoid Arbitrary Interaction Weights

Status: Accepted

Date: 2026-09-05

Context

A common simple implementation assigns values such as:

view = 1
cart = 3
purchase = 5

However, these values are arbitrary unless supported by data behavior or a model-specific interpretation.

Decision

The project will not introduce arbitrary event weights merely because different event types appear to have different strengths.

Interaction semantics must be analyzed before introducing a weighted representation.

Where a model requires a binary implicit-feedback matrix, an observed user-item interaction is represented as an interaction rather than assigning arbitrary numerical importance to event types.

Rationale

A purchase is intuitively stronger than a view, but that does not automatically imply that a numerical ratio such as 5:1 is correct.

Different recommendation algorithms may also require different representations of implicit feedback.

Alternatives Considered
Hard-code weights immediately

Rejected.

This would introduce an undocumented modeling assumption before understanding the data.

Treat all event types as independent rating values

Rejected as a general representation.

The project is not a rating-prediction problem.

Consequences

Future event-weighting experiments must be explicitly documented and evaluated rather than silently introduced into the data pipeline.

ADR-003 — Dataset Selection Happens After Project Definition

Status: Accepted

Date: 2026-09-05

Context

The project roadmap contained several possible public e-commerce datasets.

Selecting a dataset immediately could cause the project to adapt itself to whatever data happened to be downloaded first.

Decision

The problem definition and project boundaries were established before selecting the primary dataset.

Dataset selection was treated as an explicit milestone rather than an implementation detail.

The current project uses the selected processed e-commerce interaction dataset represented by:

interactions.parquet
items.parquet
train.parquet
val.parquet
test.parquet
Rationale

The dataset should support the intended recommendation problem rather than define the problem accidentally.

Selection considered:

timestamp availability
user-item interactions
event types
catalog size
number of users
item metadata
sparsity
reproducibility
usage constraints
Consequences

The dataset schema and processed artifacts are now part of the current project contract.

Future dataset changes should be treated as explicit decisions because they can invalidate benchmark comparability.

ADR-004 — Use Temporal Evaluation Rather Than Random Interaction Splitting

Status: Superseded by ADR-023 for current M4–M6 comparisons

Date: 2026-09-05

Context

Recommendation interactions occur over time.

A random interaction-level split can allow future information to appear in the training data while earlier interactions appear in test data.

This produces unrealistic evaluation.

Decision

The project uses a temporal leave-last-out evaluation strategy.

For users with sufficient interaction history:

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

The current evaluation contract uses:

earlier interactions for training
the second-to-last interaction for validation
the last interaction for test
one held-out target per eligible user
Rationale

At real inference time, the system only knows interactions that happened before the recommendation request.

Evaluation should preserve this temporal ordering.

Alternatives Considered
Random train/test split

Rejected as the default protocol.

It can leak temporal information and does not represent the intended production scenario.

Global time split

Not selected for the current benchmark.

A global temporal cutoff may be useful for future experiments but would represent a different evaluation question.

Consequences

The current benchmark is based on a fixed temporal protocol.

Changing the split protocol requires a new benchmark version rather than silently modifying the current baseline.

ADR-005 — Build the Evaluation Harness Before Sophisticated Models

Status: Accepted

Date: 2026-09-05

Context

Recommendation systems can easily produce apparently strong results because of:

data leakage
inconsistent candidate sets
incorrect metric implementations
tuning against test data
inconsistent user eligibility
Decision

A reusable offline evaluation harness and frozen benchmark are established before introducing more advanced recommendation architectures.

All current baseline models use the same evaluation framework and temporal evaluation contract.

Rationale

All models must be evaluated under the same protocol.

The project should be able to answer:

Did the model actually improve recommendation quality?

rather than:

Did the model produce recommendations?

Current Metrics

The benchmark evaluates:

Recall@K
MRR@K
NDCG@K
Catalog Coverage@20
Recommendation latency

Current K values are:

5
10
20

Because each test user has one positive target:

HR@K = Recall@K
Consequences

Future models must use the shared evaluation harness whenever their recommendation problem is comparable with the current benchmark.

ADR-006 — Popularity Must Exist Before Advanced Personalized Models

Status: Accepted

Date: 2026-09-05

Context

A recommendation model can look sophisticated while providing little value over recommending popular products.

Decision

The baseline system includes simple non-personalized and lightweight personalized baselines before advanced recommendation models.

The current baseline set includes:

Random
Global Popularity
Recent Popularity
Category Popularity
ItemKNN
ALS
Rationale

Popularity provides a strong sanity-check baseline.

A personalized model should either:

beat the strongest relevant baseline on recommendation metrics, or
provide another measurable and justified advantage such as coverage, latency, cold-start behavior, or candidate recall.
Alternatives Considered
Start directly with matrix factorization

Rejected.

Start directly with Two-Tower

Rejected.

Start directly with SASRec

Rejected.

Consequences

A neural model will not be considered successful simply because it is technically more complex.

The current strongest simple accuracy baseline is Category Popularity.

ADR-007 — Increase Model Complexity Incrementally

Status: Accepted

Date: 2026-09-05

Decision

The project follows an incremental recommendation-system learning and engineering progression:

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

The actual implementation order may differ when an earlier experiment already satisfies a later conceptual milestone.

For example, ALS was implemented during Milestone 4 as a collaborative-filtering reference and therefore does not need to be reimplemented from scratch during a later milestone merely to follow the original numbering.

Rationale

Each stage introduces an important recommendation-system concept.

Skipping all intermediate stages would make it harder to determine where improvements originate.

It would also weaken the project's ability to explain the system during technical interviews.

Consequences

Advanced architectures must be justified by benchmark results or identified engineering needs.

ADR-008 — Candidate Generation and Ranking Will Be Separate Concepts

Status: Accepted at design level

Date: 2026-09-05

Context

Large recommendation systems cannot efficiently apply an expensive ranker to an entire catalog for every request.

A common production architecture uses multiple stages.

Decision

The target system will distinguish between:

Candidate Generation

Goal:

Reduce the full catalog to a smaller set of plausible items.

Typical future candidate sources may include:

ItemKNN
ALS
popularity
Two-Tower retrieval
other retrieval models
Ranking

Goal:

Order candidates more accurately and return the final Top-K items.

Conceptual flow:

Full Catalog
     |
     v
Candidate Generators
     |
     | hundreds of candidates
     v
Candidate Pool
     |
     v
Ranker
     |
     | Top 10-20
     v
Final Recommendations
Important

This is currently an architectural direction.

A formal CandidateGenerator abstraction and production ranking stage are not yet implemented.

Consequences

Future evaluation should include candidate-specific metrics such as:

Candidate Recall@N

in addition to final ranking metrics.

ADR-009 — Do Not Introduce ANN Until Exact Retrieval Is Measured

Status: Accepted

Date: 2026-09-05

Context

The roadmap may eventually use:

FAISS
Qdrant

for approximate-nearest-neighbor retrieval.

However, ANN infrastructure introduces additional configuration and operational complexity.

Decision

The project will implement or measure exact retrieval before introducing ANN infrastructure.

ANN will only be added when there is a measurable reason.

Rationale

Approximate-nearest-neighbor systems introduce:

index configuration
quality-speed trade-offs
additional artifacts
additional operational complexity

Without measurement, this complexity has no demonstrated value.

Alternatives Considered
Start immediately with Qdrant

Rejected.

Start immediately with FAISS ANN indexes

Rejected.

Consequences

ANN selection remains unresolved.

FAISS and Qdrant are candidate technologies, not current project dependencies.

ADR-010 — Do Not Select the Deep-Learning Stack Before It Is Needed

Status: Accepted

Date: 2026-09-05

Context

The long-term roadmap includes neural recommendation models such as Two-Tower and potentially sequential models.

PyTorch is an expected future deep-learning framework.

However, the current baseline system does not require neural modeling.

Decision

PyTorch will not be introduced merely because it is expected later.

Dependencies will be added when the corresponding implementation requires them.

Rationale

This keeps the dependency surface smaller and makes milestone boundaries clearer.

Consequences

PyTorch is a planned technology, not a current project dependency.

ADR-011 — Keep Notebooks for Exploration, Not Production Pipelines

Status: Accepted

Date: 2026-09-05

Context

Jupyter notebooks are useful for:

EDA
visualization
experimentation
educational analysis

but are poor as the only production execution path.

Decision

Notebooks may be used for exploratory analysis.

Reproducible project operations should eventually exist as Python modules, scripts, or CLI commands.

Examples include:

data preparation
model training
benchmark execution
artifact building
analysis
Consequences

A successful notebook experiment must eventually be converted into reusable project code when it becomes part of the system.

ADR-012 — Do Not Pre-create the Full Source-Code Architecture

Status: Accepted

Date: 2026-09-05

Context

The master roadmap includes future packages such as:

features/
models/
retrieval/
ranking/
reranking/
evaluation/
serving/
monitoring/

Not all of these components currently exist.

Decision

The project will not create every future subdirectory and placeholder module before the corresponding implementation begins.

New source-code boundaries will be introduced when the relevant functionality is actually implemented.

Rationale

Creating the entire future architecture immediately can make the repository look more mature than it actually is.

It can also encourage future contributors or AI assistants to assume nonexistent components have already been implemented.

Consequences

The source tree represents implemented functionality rather than the entire long-term roadmap.

ARCHITECTURE_CURRENT.md remains the authority on what actually exists.

ADR-013 — Maintain Separate Project Charter, Status, Architecture, and Decisions Documents

Status: Accepted

Date: 2026-09-05

Context

Different types of project information change at different rates.

Mixing everything into one README makes it difficult to distinguish:

project goals
current implementation
current progress
historical decisions
Decision

The project maintains separate source-of-truth files.

PROJECT_CHARTER.md

Answers:

What are we trying to build?

PROJECT_STATUS.md

Answers:

Where are we now?

ARCHITECTURE_CURRENT.md

Answers:

What actually exists?

DECISIONS.md

Answers:

Why did we choose this approach?

BASELINE_REPORT.md

Answers:

How do the current baseline models perform?

Consequences

Future work should update the correct document rather than using README as the only project record.

ADR-014 — Avoid Infrastructure Without Demonstrated Need

Status: Accepted

Date: 2026-09-05

Context

Production ML projects can accumulate unnecessary infrastructure.

Potential technologies include:

Redis
Kafka
Qdrant
PostgreSQL
MLflow
Kubernetes
feature stores
microservices
Decision

Infrastructure will be introduced only when a concrete requirement or measurement justifies it.

Example

Bad rationale:

Use Redis because production systems use Redis.

Better rationale:

p95 latency is dominated by repeatedly loading the same precomputed recommendations, so an online cache may reduce response latency.

Consequences

The architecture should remain as simple as possible while satisfying current project requirements.

Infrastructure decisions should be driven by measured constraints rather than technology popularity.

ADR-015 — Build a Modular Monolith Before Considering Microservices

Status: Accepted at project level

Date: 2026-09-05

Context

The final system will contain several logical components:

candidate retrieval
ranking
filtering
re-ranking
serving

These do not automatically require separate network services.

Decision

The initial production application will use a modular monolithic architecture.

Logical boundaries should exist in Python code without prematurely splitting components into independent services.

Rationale

At portfolio scale, microservices would introduce unnecessary:

deployment complexity
network failures
distributed tracing requirements
configuration overhead
Consequences

Candidate generation and ranking may be separate modules while running inside the same recommendation service.

This decision may be revisited if future scale or deployment requirements provide evidence for decomposition.

ADR-016 — Keep Recommendation Logic Outside API Routes

Status: Accepted at design level

Date: 2026-09-05

Context

The final roadmap includes a recommendation API.

Embedding recommendation logic directly into HTTP endpoint handlers would tightly couple serving transport with machine-learning and business logic.

Decision

The intended application boundary is:

API Layer
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

The exact API technology remains an implementation decision for the serving milestone.

Important

The recommendation-serving layer is not currently implemented.

This decision governs future implementation.

Consequences

Recommendation logic should remain testable without starting an HTTP server.

ADR-017 — Freeze Benchmarks Rather Than Editing Them After Model Results

Status: Accepted

Date: 2026-09-05

Context

Changing test users or evaluation definitions after seeing model results can bias comparisons.

Decision

Once a benchmark version is validated and frozen, it will be treated as immutable historical evaluation provenance.

If the protocol legitimately changes, a new benchmark version must be created.

The current frozen Task 4 artifact is:

benchmarks/baseline/baseline_v1.json

Current M5 ItemKNN experiments are recorded through separate experiment artifacts and do not overwrite the frozen Task 4 baseline snapshot.

Consequences

Future model performance must not be improved by silently changing the benchmark.

Historical benchmark artifacts remain reproducible reference points.

ADR-018 — Use Small Coherent Git Commits

Status: Accepted

Date: 2026-09-05

Decision

Commits should represent one understandable change whenever practical.

Examples:

docs: establish project source-of-truth documents

chore: configure python project environment

test: add evaluation metric tests

feat: implement popularity recommender

feat(M5): add support-aware ItemKNN shrinkage

Large architecture refactors should not be mixed with unrelated benchmark changes.

Rationale

Small commits improve:

reviewability
debugging
rollback
project-history quality
recruiter readability
Consequences

Pushes do not need to happen after every commit.

Remote pushes should occur at useful milestone boundaries or when backup/review is desirable.

ADR-019 — Current Windows Development Environment Is Not the Production Contract

Status: Accepted

Date: 2026-09-05

Context

Development is currently occurring from a Windows PowerShell environment using Conda.

Decision

The developer machine configuration is not considered the definitive production runtime contract.

Project dependencies and runtime assumptions must eventually be represented through repository-controlled configuration.

Examples include:

pyproject.toml
dependency files
Docker configuration
environment configuration
Rationale

The system should eventually be reproducible outside the original developer machine.

Consequences

Local Conda state alone must not be required to reproduce the project.

ADR-020 — Current Architecture Must Reflect Reality, Not the Roadmap

Status: Accepted

Date: 2026-09-05

Context

The master roadmap contains the complete intended project architecture.

Future ChatGPT or coding-agent sessions may incorrectly assume planned components already exist.

Decision

docs/ARCHITECTURE_CURRENT.md will always describe the repository as it actually exists.

Planned components remain in:

the project charter
roadmap
future milestone plans

until they are implemented and validated.

Consequences

For example, at the current project state:

Formal CandidateGenerator abstraction: NOT IMPLEMENTED

Two-Tower: NOT IMPLEMENTED

Ranker: NOT IMPLEMENTED

Recommendation API: NOT IMPLEMENTED

ANN retrieval: NOT IMPLEMENTED

Online serving infrastructure: NOT IMPLEMENTED

The existence of a component in the long-term roadmap does not imply that it exists in the current architecture.

ADR-021 — Establish Initial Serving Performance Budgets

Status: Accepted

Date: 2026-09-05

Context

The project needs measurable engineering targets before production serving is implemented.

No production recommendation service exists yet, so these targets are initial budgets rather than measured results.

Decision

The initial serving targets are:

p95 end-to-end recommendation latency <= 300 ms
p99 end-to-end recommendation latency <= 500 ms
serving process memory <= 2 GiB RSS after required model and retrieval artifacts are loaded

Cold-start latency will be measured later but is not an initial release gate.

Rationale

The targets provide a practical portfolio-scale production budget without prematurely forcing infrastructure choices.

The project should measure the simplest architecture first.

If measured performance violates the budget, optimization or infrastructure changes should be justified by the measurements.

Consequences

Future performance benchmarks must report:

p50
p95
p99
memory usage

Performance optimizations such as caching or ANN retrieval should be introduced only when benchmark results justify them.

These targets are engineering budgets, not current benchmark results.

ADR-022 — Select ItemKNN as the Primary Collaborative Filtering Reference

Status: Historical selection; re-evaluated under ADR-023 before M7

Date: 2026-09-07

Updated: 2026-09-12

Context

Milestone 4 evaluated several recommendation baselines under the same temporal train/test evaluation protocol.

The evaluated models included:

Global Popularity
Recent Popularity
Category Popularity
ItemKNN
ALS Matrix Factorization

The benchmark uses the training split for model fitting and the frozen test split for final evaluation.

The test set contains 200,028 warm-start users, with one held-out target item per user.

Decision

ItemKNN is retained as the primary collaborative-filtering reference and as a candidate-generation candidate for future milestones.

ALS is retained as a secondary latent-factor reference.

Global Popularity is retained as a fallback recommendation strategy.

Recent Popularity is retained as a temporal baseline for comparison.

Category Popularity remains the strongest simple accuracy baseline and is not replaced by ItemKNN.

Evidence

The original M4 ItemKNN configuration achieved:

Recall@20: 5.5712%
MRR@20: 2.0843%
NDCG@20: 2.8586%
Coverage@20: 25.8826%

The M5 support-aware configuration with shrinkage_lambda=100 achieved:

Recall@20: 5.8972%
MRR@20: 2.3698%
NDCG@20: 3.1628%
Coverage@20: 25.6333%

The improvement is consistent across Recall, MRR, and NDCG.

At the same time, Category Popularity remains stronger on Recall@20:

Category Popularity: 8.5063%
ItemKNN: 5.8972%
ALS: 3.0636%

Therefore, ItemKNN is not selected as the overall best recommender.

It is selected because it provides a useful collaborative-filtering signal together with substantially broader catalog coverage than the popularity-based approaches.

Support-Aware Similarity Shrinkage

Milestone 5 introduced support-aware similarity shrinkage.

The adjusted similarity is:

adjusted_similarity
    = raw_similarity × support / (support + lambda)

The sweep evaluated:

lambda ∈ {0, 5, 10, 20, 50, 100, 200, 500}

Performance improved as lambda increased before reaching a plateau at larger values.

Lambda 100 was selected as the representative configuration because it provided strong ranking performance while avoiding unnecessary complexity from selecting a larger value with negligible additional benefit.

The decision is therefore based on the observed performance plateau rather than on lambda 100 uniquely maximizing every individual metric.

Current ItemKNN Configuration

The current configuration is:

n_neighbors = 20
min_item_interactions = 5
shrinkage_lambda = 100

The model indexes 84,077 items that satisfy the minimum interaction threshold.

Catalog Coverage

The final ItemKNN configuration recommends 60,840 unique items from a catalog of 235,061 items.

This corresponds to approximately 25.63% Coverage@20.

This is substantially higher than:

Category Popularity: 8.6173%
ALS: 1.5119%
Global Popularity: 0.0085%
Recent Popularity: 0.0085%

The broad coverage makes ItemKNN useful as a future candidate source even though it does not currently produce the strongest final ranking metrics.

Candidate Availability Limitations

ItemKNN currently has an important candidate-availability limitation.

16,168 of 200,028 evaluation users received no candidates from the ItemKNN recommendation path.

This corresponds to approximately 8.08% of evaluation users.

This is not conventional user-level cold start because all evaluation users have training history.

Instead, the limitation is primarily caused by sparse item history and the current ItemKNN item-index threshold.

The training data contains many items with insufficient interaction support for the configured index.

With:

min_item_interactions = 5

only 84,077 items are indexed.

Some users also have indexed history but still produce no usable candidate because their indexed history items have no positive-similarity neighbors or the available neighbors have already been seen.

Recommendation Concentration

M5 analysis found:

200,028 evaluation users
183,860 users receiving recommendations (200,028 - 16,168 with no candidates)
60,840 unique recommended items
3,573,113 recommendation slots (average below 20 per receiving user after seen-filtering)
Top 10 items: approximately 3.72% of slots
Top 100 items: approximately 18.83% of slots
Top 1,000 items: approximately 45.75% of slots

This shows that ItemKNN provides broad catalog exposure but still exhibits recommendation concentration.

Therefore, high coverage should not be interpreted as uniform exposure across the catalog.

Interpretation

The benchmark suggests that the current dataset contains a useful item co-occurrence signal.

ItemKNN directly models item-item relationships derived from user interaction history.

The support-aware shrinkage experiment further indicates that similarity estimates with stronger co-occurrence support are more reliable for the current dataset.

However, the result does not imply that ItemKNN is universally superior to matrix factorization.

ALS was evaluated using a fixed configuration and has not yet undergone broad validation-based hyperparameter tuning.

The current decision therefore applies to the present dataset, interaction representation, evaluation protocol, and model configurations.

Production Implications

ItemKNN should not yet be considered production-ready solely because of its offline benchmark result.

Future candidate-generation work must address:

empty recommendation sets
sparse item history
new-item handling
candidate availability
validation-based tuning
serving latency
memory usage
fallback behavior
integration with future ranking components

Global Popularity should remain available as a fallback when a personalized candidate source cannot provide sufficient recommendations.

Future Reconsideration

This decision may be revisited after:

ItemKNN validation experiments are completed.
ALS is tuned using validation data.
Additional candidate-generation approaches are implemented.
New-item and cold-start strategies are introduced.
Candidate Recall@N is evaluated.
Serving performance is measured.
A downstream ranking model is introduced.

The final recommendation architecture should be selected based on both recommendation quality and engineering constraints rather than offline ranking metrics alone.

ADR-023 — Rolling Temporal Benchmark for M4–M6

Status: Accepted

Date: 2026-10-04

Context

ADR-004 checked time order within each user, but the shared training set contained events from other users after many held-out targets. The 200,028-user cohort also included already-seen target items. A later single-cutoff evaluation covered only 3,590 returning warm users and was too narrow for cross-model selection.

Decision

Use nine globally ordered rolling folds. For each fold, all M4–M6 recommenders train only on earlier events and use the same train-time candidate catalog and first unseen-item target per returning warm user. A user needs at least one earlier interaction. Count cold users separately. Tune ItemKNN and ALS on folds 1–4, select by pooled HR@20 with NDCG@20 as tie-break, and compare selected configurations on folds 5–9. The nine-fold reference results exposed folds 5–9 before the sweep was locked, so the later comparison is not a blind holdout. Retain v1 artifacts as history; remove the single-cutoff benchmark. Full rules and limitations are in ROLLING_EVALUATION_PROTOCOL.md.

Consequences

The warm cohort is smaller than the historical 200,028-user cohort because the task and time constraint differ. Report unique users and user-window counts, and never place v1 and rolling metrics in the same performance ranking. Prior M7 model choices must be reconsidered using the rolling results.

Decision Log Summary
ADR	Decision	Status
ADR-001	Implicit-feedback recommendation	Accepted
ADR-002	Avoid arbitrary interaction weighting	Accepted
ADR-003	Dataset selection follows project definition	Accepted
ADR-004	Temporal leave-last-out evaluation	Superseded by ADR-023
ADR-005	Evaluation before sophisticated models	Accepted
ADR-006	Popularity baseline first	Accepted
ADR-007	Incremental model complexity	Accepted
ADR-008	Separate candidate generation and ranking	Accepted at design level
ADR-009	Measure exact retrieval before ANN	Accepted
ADR-010	Delay deep-learning dependencies	Accepted
ADR-011	Notebooks for exploration only	Accepted
ADR-012	Do not pre-create full architecture	Accepted
ADR-013	Separate source-of-truth documents	Accepted
ADR-014	Infrastructure requires justification	Accepted
ADR-015	Modular monolith before microservices	Accepted at project level
ADR-016	Recommendation logic outside API routes	Accepted at design level
ADR-017	Frozen benchmark versions	Accepted
ADR-018	Small coherent Git commits	Accepted
ADR-019	Local Windows environment is not production contract	Accepted
ADR-020	Current architecture must reflect reality	Accepted
ADR-021	Establish initial serving performance budgets	Accepted
ADR-022	ItemKNN as primary collaborative-filtering reference	Historical; under re-evaluation
ADR-023	Rolling temporal benchmark for M4–M6	Accepted
Future Decision Topics

The following topics remain intentionally unresolved because the relevant implementation or evidence does not yet exist.

Interaction Modeling

Pending:

whether event-type weighting should be introduced
whether different event types should receive model-specific confidence
whether repeated interactions should be aggregated differently for future models

The current baseline uses the existing processed interaction representation. Future changes must be evaluated rather than assumed to improve recommendation quality.

Candidate Generation

Pending:

formal CandidateGenerator interface
candidate pool size
multiple candidate-source architecture
candidate deduplication
candidate Recall@N evaluation
ItemKNN versus ALS as candidate sources
hybrid candidate generation
Matrix Factorization

Pending:

educational MF implementation
BPR experimentation
ALS validation-based tuning
latent-dimension experiments
regularization experiments
MF experiment report
final decision on ALS's role in candidate generation

ALS is already implemented and therefore does not need to be reimplemented simply to satisfy the original roadmap sequence.

Neural Retrieval

Pending:

Two-Tower architecture
user representation
item representation
feature design
negative sampling
loss function
training strategy
retrieval evaluation
ANN

Pending:

whether ANN is required
exact retrieval scalability limit
FAISS versus another ANN implementation
ANN index configuration
retrieval quality versus latency trade-off
Ranking

Pending:

ranking model
LightGBM versus XGBoost
ranking objective
ranking features
negative construction
validation strategy
final ranking metrics
Re-ranking

Pending:

diversity strategy
novelty
business rules
category constraints
duplicate suppression
exploration/exploitation policy
Serving

Pending:

exact API contract
recommendation-service lifecycle
artifact-loading design
caching strategy
fallback hierarchy
request validation
model reload strategy
Performance

Pending:

validation of the p95 latency budget
validation of the p99 latency budget
validation of the serving memory budget
cold-start performance budget
load-testing targets
failure-mode performance
whether caching is required
whether ANN retrieval is required
whether additional architectural changes are required to satisfy the performance budget

The current engineering budgets from ADR-021 are:

p95 end-to-end recommendation latency <= 300 ms
p99 end-to-end recommendation latency <= 500 ms
serving process memory <= 2 GiB RSS after required model and retrieval artifacts are loaded

These are initial engineering budgets, not measured results.

Deployment

Pending:

cloud provider
resource requirements
artifact storage
deployment strategy
rollout strategy
monitoring infrastructure
operational alerting

These decisions should remain unresolved until the relevant milestone provides enough information to make them responsibly.
