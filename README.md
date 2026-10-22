# E-commerce recommendation system

A recommendation project built on the Retailrocket interaction dataset, with temporal offline evaluation and a local HTTP snapshot API. The repository contains data preparation, popularity baselines, ItemKNN, educational MF/BPR, implicit ALS, source-aware candidate retrieval, learned ranking and versioned inference snapshots with locked warm/cold routes. Public deployment and online evaluation are not implemented.

## Recommendation evaluation

Benchmark accuracy and coverage use fractions in `[0, 1]`. The
[metric and protocol glossary](docs/METRICS_AND_PROTOCOLS.md) defines units,
evaluation populations, ALS configurations, fallback behavior and timing scopes.

The current benchmark uses nine chronological folds. Every model in a fold trains on the same earlier interactions and recommends from the same training-time catalog. The primary task predicts each returning user's first previously unseen item in the next window; first-time users are evaluated separately. The benchmark contains **90,107 warm user-window targets from 71,982 distinct users** and **1,262,289 first-time user targets**.

| Model | HR@20 on folds 5–9 |
| :--- | ---: |
| Random | 0.000034 |
| Global Popularity | 0.007855 |
| Recent Popularity | 0.008209 |
| Category Popularity | 0.041518 |
| ItemKNN (selected shrinkage) | 0.041889 |
| Implicit ALS (selected configuration) | 0.027291 |

ItemKNN and ALS configurations were selected using folds 1–4. The five-fold figures above are **exploratory post-selection results**, because reference scores for folds 5–9 had already been inspected before the sweep configurations were locked. The ItemKNN–Category Popularity difference is too small to establish a reliable winner. See the [benchmark report](docs/ROLLING_BENCHMARK_REPORT.md) for MRR, NDCG, coverage, latency, cold-user results, and limitations.

## Candidate retrieval

The candidate-retrieval benchmark evaluates retrieval separately from final
Top-K ranking. Each source is asked
for up to 1,000 eligible, unseen products; this is a request budget, not a
guarantee that every source can fill it. In folds 5–9, ItemKNN returned a mean
of 40.07 products and an empty pool for 14.61% of warm requests. Reciprocal rank
fusion combines available source lists while retaining source scores and ranks.
The same **59,323 warm targets**
in folds 5–9 give the following post-selection diagnostic results:

| Generator | Recall@100 | Recall@500 | Recall@1000 |
| :--- | ---: | ---: | ---: |
| Exact ALS | 0.050705 | 0.087116 | 0.109216 |
| Hybrid without ALS | 0.081183 | 0.165180 | 0.213206 |
| Hybrid | 0.079750 | 0.163832 | 0.211537 |

These figures measure target availability within the candidate pool, not final
Top-20 accuracy. The [retrieval report](docs/CANDIDATE_RETRIEVAL_REPORT.md) covers
all seven generators, cold users, availability, ALS ablation and fitting/retrieval
cost. The [design](docs/CANDIDATE_GENERATION.md) specifies the candidate contract.

## Two-tower retrieval

A deterministic CPU two-tower retriever compares its exact catalog
scores with ALS on the same rolling warm targets. The model uses recent distinct
item history on the user side and item ID plus train-time category on the item
side. Negative sampling excludes the full prior user history, including items
outside the truncated feature history. The selected Two-Tower configuration
(dimension 128, history 50) achieved pooled Recall@100/500/1000 of
0.044485 / 0.096185 / 0.127640 on 59,323 warm user-windows in folds 5–9. ALS
achieved 0.050705 / 0.087116 / 0.109216 on the same targets. The period had
been inspected before configuration lock, so these are post-selection
diagnostics, not blind validation. See the [two-tower report](docs/TWO_TOWER_REPORT.md)
for per-fold metrics, cost, latency scope and provenance.

## ANN feasibility

The ANN feasibility study screened approximate search against exact Two-Tower
retrieval before adding an index to the candidate pipeline. Exact p95 exceeded
the predeclared cost trigger on three of four development folds. In a paired
fold-1 Faiss HNSW pilot, all four
index configurations were slower than exact at the 1,000-candidate budget, so
none met the predeclared speed gate. No ANN index was adopted, and no folds 5–9
ANN results are reported. The [ANN feasibility report](docs/ANN_RETRIEVAL_REPORT.md)
shows the timing, sample-hit and index-build evidence with its limitations.

## Causal ranking dataset

The ranking pipeline builds candidate-level training data for the warm rolling
task on development folds 1–4. The fixed full hybrid generated
**30,784,000 candidate rows** for **30,784 warm user-windows**. Of those
requests, 6,717 have their future target
in the 1,000-item pool (Candidate Recall@1000 **0.218198**). Requests with an
unreachable or unretrieved target remain in the denominator. Features use only
the fold's training snapshot and as-of catalog; an independent Parquet audit
found no null or nonfinite values. The dataset build itself stops before
learned Top-K evaluation. The [ranking dataset report](docs/RANKING_DATASET_REPORT.md)
records the feature contract, per-fold counts, build cost and reproduction steps.

## Learned ranking

A deterministic pairwise linear ranker uses the labelled development rows and
reorders the same fixed 1,000-candidate full-hybrid pool as RRF. Its L2 setting
was selected on chronological folds 2–4, then locked before scoring folds
5–9. On **59,323 warm user-windows** in those later folds, RRF had **2,285**
hits@20 (HR@20 **0.038518**) and the ranker had **3,237** (HR@20
**0.054566**). The pool itself reached **12,549** targets (Candidate
Recall@1000 **0.211537**); the ranker changes ordering, not retrieval.
All five later folds improved in hit count. These are **post-selection
diagnostics, not blind validation**, and the offline experiment does not
select a production retrieval or serving policy. The
[learned-ranking report](docs/LEARNED_RANKING_REPORT.md) covers per-fold
HR/MRR/NDCG, selection, cost and limitations.

## Category-aware re-ranking

A fixed category-novelty bonus reorders the learned ranker's Top-100 shortlist
without changing its candidate pool or scores. The bonus was selected on
chronological folds 2–4 and locked before the folds 5–9 diagnostic. On the
same **59,323 warm user-windows**, distinct known-category slots@20 increased
from **0.125625** to **0.146108**, while Top-20 hits changed from **3,237** to
**3,236** and NDCG@20 from **0.026383** to **0.026135**. Item catalog coverage
fell slightly in every fold; Top-5 hits fell from **1,649** to **1,638**.
The rule uses learned rank and category counts, without item-distance or
aspect-probability modeling. This is an offline relevance/diversity trade-off,
not a deployed ranking policy. The later folds are **post-selection
diagnostics, not blind validation**. The [re-ranking report](docs/DIVERSITY_RERANKING_REPORT.md)
gives the denominator, per-fold metrics, cost and limitations.

## Sequential retrieval experiment

A train-time next-bucket transition source tested whether giving more weight
to recent interaction buckets improves candidate order. On the same **59,323
warm user-windows** in folds 5–9, the locked ordered policy found **3,799**
targets at 100 candidates (Recall@100 **0.064039**); its equal-weight control
using the same 20 buckets found **3,824** (Recall@100 **0.064461**). Both found
**4,035** by 1,000 candidates. The predeclared order-benefit gate failed, so
the source was not added to the hybrid. These are post-selection diagnostics,
not blind validation. The [sequential report](docs/SEQUENTIAL_RECOMMENDATION_REPORT.md)
documents the temporal contract, ablation, per-fold results and cost scope.

## Offline reference policy

The complete-policy comparison locks separate routes on development folds 2–4:
full-hybrid learned ordering for returning users and recent popularity for
first-time users. Eleven warm and three cold alternatives share their cutoff
snapshots, cohorts and output budgets. The complete folds 5–9 diagnostic has
3,237/59,323 warm hits@20 for the locked route (HR@20 0.054566) and
8,416/715,331 cold hits@20 (HR@20 0.011765). Cold popularity RRF has more
later hits than the locked recent route; the development choice remains fixed.
These are post-selection diagnostics on previously inspected periods. The
[policy report](docs/MODEL_POLICY_REPORT.md) records selection,
no-ALS model transfer, availability and matched inference-cost scope. This is
an offline reference, now exposed unchanged through the local snapshot API.

## Model artifacts

The locked reference can be exported as an immutable, checksum-verified model
bundle. The installed Python package loads its source state, as-of feature
aggregates and ranker without training data, benchmark scripts or refitting.
Inference still requires compatible package implementations and numerical
dependencies; the bundle is independent of the training pipeline.
Known snapshot users take the full-hybrid learned route; unknown users take
explicit recent popularity. Recommendations include the bundle version and
cutoff. The [artifact contract](docs/MODEL_ARTIFACTS.md) explains safe formats,
atomic publication, integrity checks, save/load parity and snapshot limits.
Generated bundles stay outside Git; validation receipts preserve their identity
and reconciliation evidence.

## Local recommendation API

A FastAPI application loads one digest-pinned snapshot at startup and exposes
`POST /v1/recommendations`, liveness and readiness probes, and OpenAPI docs.
Strict request validation, full seen-item filtering and one active inference
call preserve the snapshot contract. With the default cache-off/reject settings,
overlapping requests receive 503 busy. Operators can enable bounded result
caching and an explicitly attributed recent-popularity fallback for overload;
backend failures still make the model unready and require restart.

The [API contract](docs/RECOMMENDATION_API.md) includes installation, launch and
request examples. [Current HTTP verification](benchmarks/serving/hardening_boundary_validation_v1.json)
matches 100 warm and one cold reference output with cache off, on-miss and on-hit.
The [input and exposure controls](docs/API_HARDENING.md) add absolute header/body
deadlines, bounded connections/readers, global/socket-peer request budgets,
local Host/Origin checks and optional shared bearer credentials. The launcher
ignores forwarded identity and remains loopback-only. The
[cache and fallback report](docs/SERVICE_CACHE_AND_FALLBACKS.md) explains identity,
limits and measured scope. Process-memory and workload-latency targets remain
independent release gates. Local timings are smoke evidence, not an SLA;
public deployment and online confirmation remain outside this implementation.

The [observability contract](docs/OBSERVABILITY.md) documents local `GET /metrics`
and owned JSON events. Bounded labels separate HTTP outcomes, model-worker cost,
admission, cache and degraded delivery; process RSS and model identity remain
visible without exporting user IDs. External collection, dashboards and alert
delivery are separate operational work.

## Integration verification

The functional gate runs unit regressions, HTTP process tests with genuinely
fitted synthetic models, explicit real-bundle numerical references and fresh
HTTP parity checks. Its [test strategy](docs/TESTING_AND_RELEASE_GATES.md)
distinguishes fixture coverage, current model parity and historical full-fold
quality. A successful functional check does not establish Linux compatibility,
representative-load performance or deployment eligibility.

## Isolated Linux container

The unchanged snapshot can run in a pinned Linux/amd64 container with a
non-root user, read-only model/root mounts, bounded resources and internal
health checks. Qualification compares 101 real references and HTTP outputs;
pool, evidence and output order remain exact, with a separately declared
`1e-12` feature/score tolerance across operating systems. The original
same-host bitwise checks remain unchanged.

The [container report](docs/LINUX_CONTAINER.md) records the build, numerical
policy revision and measured limits. This isolated configuration has no
published ports. It does not establish deployment eligibility, representative
load capacity or compliance with the outstanding 2 GiB serving RSS target.

## Controlled local release

Hosted CI uses immutable Action pins, hashed CPU test dependencies and separate
unit/fitted-process gates. A separate reusable workflow defines manual real-model
qualification on a protected private runner; that remote lane is not configured
or claimed as executed.

The local release controller verifies an immutable candidate before replacing
its active pointer, records incomplete operations and supports explicit recovery
and rollback. The [release runbook](docs/RELEASE_WORKFLOW.md) records actual
Linux tests and original-bundle release/crash/rollback evidence. This remains
network-isolated qualification, with no public traffic switch or deployment
eligibility; the 2 GiB memory target remains unmet.

## HTTP workload and capacity

The unchanged Linux snapshot has a [fixed HTTP capacity assessment](docs/HTTP_CAPACITY_REPORT.md):
four 150-second open-loop workloads and 2,550 measured arrivals. It separates
warm/cold success latency, primed cache hits, worker busy rejection, quota
rejection and dispatch cost. Successful responses preserve sealed outputs.
Serving RSS remains above 2 GiB, so deployment eligibility stays false. This is
constructed repeated-reference traffic on Docker Desktop, not production load
or a maximum-throughput claim.

## Load, failure and recovery

The [local reliability assessment](docs/SERVICE_RELIABILITY_REPORT.md) adds a
10-minute sustained workload, fixed burst/recovery cycles, bounded memory
occupancy and original-model disconnect/termination/startup checks. A fresh
release exercise verifies dead-target recovery and rollback. Event-controlled
fixture tests separately cover cancelled waiters and model/executor failures.
The unchanged model/image remain isolated; operational completion does not
waive the 2 GiB RSS target or establish production readiness.

## Deployment design

The [deployment design](docs/DEPLOYMENT_DESIGN.md) evaluates hosting against the
measured memory, workload and recovery limits. It retains local execution and
identifies a conditional OCI Arm free-tier investigation. No cloud host is
approved: architecture/target-host qualification, exposure and delivery controls,
account eligibility and the unmet 2 GiB RSS target remain release gates.
A source-pinned offline assessor reproduces the resource and dated cost decision
without provisioning infrastructure or changing the recommendation service.

## Repository guide

- [Rolling evaluation protocol](docs/ROLLING_EVALUATION_PROTOCOL.md): cohorts, time boundaries, selection rule, and validity limits.
- [Benchmark report](docs/ROLLING_BENCHMARK_REPORT.md) and [result artifacts](benchmarks/rolling/): measured outcomes and per-fold data.
- [Current architecture](docs/ARCHITECTURE_CURRENT.md) and [project status](docs/PROJECT_STATUS.md): implemented components and next steps.
- [Roadmap](docs/ROADMAP.md) and [candidate-generation design](docs/CANDIDATE_GENERATION.md): milestone scope, retrieval contracts and validation gates.
- [Dataset card](docs/DATASET_CARD.md) and [data contract](docs/DATA_CONTRACT.md): source, schema, and processing assumptions.
- [Engineering decisions](docs/DECISIONS.md): design rationale, including the transition from per-user leave-last-out to global temporal folds.
- [Metric and protocol glossary](docs/METRICS_AND_PROTOCOLS.md): comparison boundaries, units, model references and latency workloads.
- [ANN feasibility report](docs/ANN_RETRIEVAL_REPORT.md): conditional index decision and measured no-go result.
- [Ranking dataset report](docs/RANKING_DATASET_REPORT.md): causal ranking rows, feature contract and development-fold audit.
- [Learned-ranking report](docs/LEARNED_RANKING_REPORT.md): same-pool Top-K comparison, model selection and diagnostic limits.
- [Category-aware re-ranking report](docs/DIVERSITY_RERANKING_REPORT.md): locked same-pool diversity trade-off, relevance and cost.
- [Sequential retrieval report](docs/SEQUENTIAL_RECOMMENDATION_REPORT.md): matched order ablation and measured no-go decision.
- [Offline policy report](docs/MODEL_POLICY_REPORT.md): complete fixed-policy comparison, warm/cold route lock and matched cost scope.
- [Model artifacts](docs/MODEL_ARTIFACTS.md): immutable bundle contract, independent Python inference and loaded-policy verification.
- [Recommendation API](docs/RECOMMENDATION_API.md): local HTTP contract, lifecycle, bounded admission, reference parity and measured resource limits.
- [Cache and overload fallback](docs/SERVICE_CACHE_AND_FALLBACKS.md): optional bounded reuse, explicit degraded responses, failure semantics and paired HTTP evidence.
- [API hardening](docs/API_HARDENING.md): local access policy, connection/input budgets, request limits and source-pinned verification.
- [Testing and functional gates](docs/TESTING_AND_RELEASE_GATES.md): unit and fitted-process profiles, explicit real-bundle parity and deployment boundaries.
- [Linux snapshot container](docs/LINUX_CONTAINER.md): pinned build, read-only artifact delivery, isolated runtime and real cross-platform qualification.
- [HTTP capacity assessment](docs/HTTP_CAPACITY_REPORT.md): fixed offered-load controls, latency/rejection/resource scopes, parity and remaining budget gates.
- [Local reliability assessment](docs/SERVICE_RELIABILITY_REPORT.md): sustained/burst load, resource occupancy, lifecycle faults and fresh recovery with explicit scope limits.
- [Controlled release runbook](docs/RELEASE_WORKFLOW.md): CI profiles, private-runner prerequisites, immutable local release identities and verified recovery/rollback.
- [Deployment design and cost](docs/DEPLOYMENT_DESIGN.md): conditional free-host options, resource arithmetic, artifact/secrets delivery, exposure and remaining qualification gates.

Earlier leave-last-out experiments remain in the [baseline](docs/BASELINE_REPORT.md) and [MF](docs/MF_EXPERIMENT_REPORT.md) reports as historical evidence. Their scores answer a different evaluation question and should not be compared directly with the rolling results.

## Reproduce

Use Python 3.13 from the repository root. Download the
[Retailrocket dataset](https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset)
and extract `events.csv`, `category_tree.csv`, `item_properties_part1.csv` and
`item_properties_part2.csv` into `data/raw/`. Alternatively, with an authenticated
Kaggle CLI, run `python scripts/download_data.py`. Verify the files with
`python scripts/download_data.py --verify-only`. The [dataset card](docs/DATASET_CARD.md)
describes the source, schema and recorded input hashes. In a fresh checkout,
prepare the shared rolling inputs and candidate reference with:

```sh
python -m pip install -e ".[dev]" -r requirements/serving-test.txt -r requirements/release-test.txt
python scripts/build_interactions.py
python scripts/prepare_rolling_data.py
python scripts/sweep_rolling.py --model item_knn
python scripts/sweep_rolling.py --model als
python scripts/benchmark_rolling.py
python scripts/benchmark_rolling_cold.py
python scripts/benchmark_candidates.py
pytest
ruff check .
ruff format --check .
```

The raw CSVs and generated Parquet files are not committed. If they reside
elsewhere, pass `--input-path` and `--raw-dir` to the preparation command, and
`--input-path` to the sweep and benchmark commands. The manifest records
SHA-256 hashes for the processed interactions, raw item properties, and each
generated fold file; runners verify those hashes before resuming.

The published M10/M11 artifacts bind an earlier source tree. Later package
additions changed their broad source fingerprints without changing their
original implementation. To regenerate the frozen ranking Parquet inputs, use a
separate full-history checkout at Git revision
`c80cebee3378ea9af7c9757802fa40e2c8594ae2` with the matching processed
interactions and rolling fold files. Copy the matching frozen benchmark JSON
from the current checkout as well: their byte serialization is part of the
checksum chain. Then run:

```sh
python -m pip install -e ".[dev]"
python scripts/build_ranking_dataset.py --artifact .local/ranking_rebuild_v1.json
python scripts/verify_ranking_dataset.py --quality benchmarks/ranking/m10_quality_v1.json --output .local/ranking_rebuild_audit_v1.json
```

Use a fresh scratch checkpoint for a rebuild; the published checkpoint resumes
only when its generated files already exist and match their hashes. The verifier
above checks rebuilt Parquet against the frozen file hashes. Preserve published
JSON, whose checksums also bind the original measured costs. A different runtime
or serialization may require a separately named experiment rather than a
byte-identical reproduction.

With those verified M10 Parquet files and published M10/M11 JSON artifacts
available, return to the current checkout and reinstall its editable package
before running the category-aware experiment:

```sh
python -m pip install -e ".[dev]"
python scripts/benchmark_diversity.py development
python scripts/benchmark_diversity.py lock
python scripts/benchmark_diversity.py diagnostic
python scripts/benchmark_model_policy.py development
python scripts/benchmark_model_policy.py lock
python scripts/benchmark_model_policy.py diagnostic
python scripts/verify_model_policy.py
```

The runner verifies the historical source revision and upstream hashes; it
does not rewrite frozen artifacts. The [ranking dataset](docs/RANKING_DATASET_REPORT.md),
[learned ranking](docs/LEARNED_RANKING_REPORT.md), [re-ranking](docs/DIVERSITY_RERANKING_REPORT.md),
[offline policy](docs/MODEL_POLICY_REPORT.md)
and [sequential](docs/SEQUENTIAL_RECOMMENDATION_REPORT.md) reports give each
experiment's commands, artifact paths and scope.
