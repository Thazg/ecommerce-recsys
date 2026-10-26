# Current architecture

**Updated:** 2026-10-26
**State:** offline pipeline, recommendation evaluation, hybrid candidate generation,
exact Two-Tower retrieval, an ANN feasibility no-go and causal ranking
data for development folds 1–4. A learned ranker, category-aware re-ranker
and separate sequential transition source have been evaluated offline. The
sequential order ablation failed its primary gate, so no source was adopted.
A complete-policy runner has locked separate warm/cold offline routes from
development folds 2–4 and completed all fixed diagnostics on folds 5–9.
No ANN source has been adopted. The locked routes now have a local HTTP
snapshot interface. Backend execution is local; public model hosting is outside
the release scope and evaluation remains offline.
The artifact layer now separates fitted offline snapshots from package-only
inference. A separate service layer preserves that frozen inference code and
provides optional bounded result caching and an explicit busy fallback.
Separate host tooling now manages immutable isolated release descriptors,
verified candidates, journal recovery and rollback. Hosted CI and a reusable
private qualification lane remain separate from the model/service layers;
the latter has not been configured or executed remotely. Separate hosted
publication checks cover both static demos, documentation identity and secret
scanning; they do not modify model qualification or expose inference. Separate local
[load and recovery verification](SERVICE_RELIABILITY_REPORT.md) exercises the
unchanged snapshot under fixed sustained/burst traffic, resource occupancy and
lifecycle faults; it does not establish deployment eligibility. A separate
[deployment assessment](DEPLOYMENT_DESIGN.md) now records the conditional hosting
and cost decision; its proposed cloud/gateway components are historical design
options outside the current local release scope. [ADR-40](DECISIONS.md#adr-40--define-a-local-backend-release-with-public-static-demonstrations)
records this scope decision without changing earlier measurements.

A separate [RecoLens explorer](SNAPSHOT_EXPLORER.md) projects five verified fold-9
references into public JSON plus HTML/CSS/JavaScript. The offline exporter loads
the original bundle, verifies sealed traces and removes user IDs. A loopback
preview serves only `demo/`; Vercel hosts the same static output at
[ecommerce-recsys.vercel.app](https://ecommerce-recsys.vercel.app/).
The browser checks schema/content identity and switches stored outputs without
calling the API. Root deployment configuration supplies security headers and
disables automatic Git deployment. A CLI upload allowlist excludes all model,
data and source files outside the seven static assets. See the
[hosting runbook](STATIC_DEMO_DEPLOYMENT.md). This is not a model server or a
full-model cloud deployment adapter.

The current [local demonstration](LOCAL_DEMONSTRATION.md) adds an explicit
`scripts.serve_local_snapshot` entry point. Its indexed reader stores aggregate
features in read-only columns and sparse affinity rows, reusing the original
context/retrieval/ranking methods. The original default loader, model files and
service code are preserved. A separate source-pinned HTTP probe checks complete
finite-reference output parity and owned process cleanup. The public RecoLens
assets remain unchanged and do not communicate with the local API.

The [local release verifier](LOCAL_RELEASE_REPORT.md) exercises that explicit
indexed-reader launcher with an inherited, parent-owned control pipe. It requests
the existing application drain without adding an HTTP control endpoint. Fresh
same-port processes verify 101 sealed outputs, fixed sustained/burst traffic,
external RSS samples and telemetry; wrong manifest startup is rejected. The
completed Windows profile meets all declared local targets. Historical Linux
container/load evidence remains separate and is not updated by this result.
Control EOF reaches the service stop transition during startup. The verifier
tracks child reaping separately from log state, enforces absolute socket
deadlines and rejects contradictory resource/time summaries before acceptance.

A separate [shopping illustration](SHOPPING_DEMONSTRATION.md) lives under
`shop-demo/`. It serves a 100-product photographed sample catalog, captures
view/heart/rating signals in tab session storage and calculates an explained
content-based list in JavaScript. It has no model/API dependency. All pictures
are bundled with source and hash records. A separate Vercel Hobby project serves
these 108 static assets at [shoprecome.vercel.app](https://shoprecome.vercel.app/),
with no build step, backend or Git deployment connection. It is separate from
the original seven-asset snapshot explorer and Retailrocket quality evidence.

The standard-library `scripts/verify_project_documentation.py` checks the
explicit release inventory, local Markdown targets/fragments and immutable
evidence bytes without package/model imports or network access. It separately
checks all seven assets against the released presentation and fingerprints
current documentation/source. Historical receipts retain their original
documentation identities. [Reproducibility](REPRODUCIBILITY.md), the
[evidence index](EVIDENCE_INDEX.md) and [operations runbook](OPERATIONS_RUNBOOK.md)
describe input tiers, producer revisions and operational limits.

```text
Retailrocket raw CSV
    -> build_interactions.py
    -> interactions.parquet
    -> prepare_rolling_data.py (nine future windows)
    -> data/rolling/fold_XX (warm/cold targets and train-time catalogs)
       + benchmarks/rolling/manifest.json (boundaries and input hashes)

Prepared folds + manifest
    -> sweep_rolling.py -> selected ItemKNN and ALS sweep artifacts
    -> benchmark_rolling.py -> benchmarks/rolling/results.json
    -> benchmark_rolling_cold.py -> benchmarks/rolling/cold.json

Prepared folds + manifest + completed sweeps
    -> benchmark_candidates.py -> benchmarks/retrieval/candidates.json

Prepared folds + manifest
    -> benchmark_two_tower.py (Two-Tower development folds 1–4)
    -> lock_two_tower_configs.py (binds unchanged ALS v2 evidence)
       -> benchmarks/retrieval/m8_selection_lock_v1.json
    -> benchmark_two_tower.py (Two-Tower diagnostic folds 5–9)
    -> benchmarks/retrieval/two_tower_diagnostic_v1.json

Prepared folds + published Two-Tower selection lock
    -> profile_exact_retrieval.py (development exact-cost profile)
    -> benchmark_ann_feasibility.py (paired fold-1 Faiss HNSW speed screen)
    -> benchmarks/retrieval/m9_profile_v1.json
       + benchmarks/retrieval/m9_ann_pilot_v1.json (no-go)

Prepared folds + selected hybrid source policy and sweeps
    -> build_ranking_dataset.py (warm development folds 1–4)
    -> data/ranking/m10_v1/fold_XX (request and candidate Parquet, ignored by Git)
       + benchmarks/ranking/m10_quality_v1.json (hash-bound checkpoint)
    -> verify_ranking_dataset.py
       + benchmarks/ranking/m10_feature_audit_v1.json

Verified development ranking rows
    -> benchmark_ranker.py development (train earlier folds, score folds 2–4)
    -> ranker_development_v1.json -> benchmark_ranker.py lock
    -> ranker_selection_lock_v1.json
    -> benchmark_ranker.py diagnostic (fit ranker on folds 1–4;
       regenerate each fold's full-hybrid pool at its cutoff, score folds 5–9)
    -> ranker_diagnostic_v1.json (post-selection, not blind)

Prepared rolling folds + processed train interactions
    -> benchmark_sequential.py development (six transition policies, folds 1–4)
    -> sequential_development_v1.json -> benchmark_sequential.py lock
    -> sequential_selection_lock_v1.json
    -> benchmark_sequential.py diagnostic (matched ordered/equal control, folds 5–9)
    -> sequential_diagnostic_v1.json (order-benefit gate failed; no source adopted)

Fixed learned-ranker scores + fold cutoff category snapshots
    -> benchmark_diversity.py development (category-novelty grid, folds 2–4)
    -> diversity_development_v1.json -> benchmark_diversity.py lock
    -> diversity_selection_lock_v1.json
    -> benchmark_diversity.py diagnostic (fixed Top-100 shortlist, folds 5–9)
    -> diversity_diagnostic_v1.json (same-pool learned-order control)

Verified source snapshots + locked ranker/category settings
    -> benchmark_model_policy.py development (eleven warm/three cold policies)
    -> benchmarks/model_policy/development_v1.json
    -> benchmark_model_policy.py lock -> selection_lock_v1.json
    -> benchmark_model_policy.py diagnostic (folds 5–9, atomic checkpoints)
    -> diagnostic_v1.json (complete flag records finished fold coverage)
    -> verify_model_policy.py -> provenance_v1.json (retrospective seed/audit verification)
```

`src/ecommerce_recsys/data/splitting.py` contains rolling time windows and global causality guards. `src/ecommerce_recsys/data/catalog.py` constructs train-time item and category snapshots. Cohort and metric rules are in the [rolling evaluation protocol](ROLLING_EVALUATION_PROTOCOL.md).

`src/ecommerce_recsys/recommendation/` contains Random, Global Popularity, Recent Popularity, Category Popularity, ItemKNN, ALS, and educational MF/BPR implementations. ItemKNN indexes eligible interaction items and uses popularity fallback for unknown history. ALS uses the `implicit` library. The snapshot service restores the locked source states through package adapters; it does not expose arbitrary model selection.

`src/ecommerce_recsys/evaluation/` computes HR@K, MRR@K, NDCG@K, catalog coverage, and recommendation-call latency. Its rolling benchmark harness rejects training data that overlaps evaluation time globally, checks unseen targets, and removes previously seen items from global popularity recommendations. Latency excludes training, data loading, network time, and API overhead.

## Candidate retrieval

```text
Fitted train-time snapshot + user/history context
    -> ItemKNN / exact ALS / category / recent / global sources
    -> catalog and seen-item filtering
    -> source candidate pools (requested budget up to 1,000; sources may return fewer)
    -> reciprocal-rank fusion and deduplication
    -> candidates with per-source scores and ranks
```

`src/ecommerce_recsys/retrieval/` defines the common candidate interface and its
adapters. ALS retrieves by exact user/item dot product. The hybrid retains source
evidence and includes explicit popularity sources for cold or sparse context.
Candidates feed the offline learned-ranker experiment described below. Its
frozen scorer is also used by the snapshot adapter and local HTTP interface.

`evaluation/candidates.py` measures Recall@100/500/1000, reachable-target recall,
empty/full pool rates, candidate counts, coverage and source contribution. The
rolling candidate runner also records source fitting time, ALS factor-array
bytes and retrieval latency. Hybrid latency includes constituent source calls
and fusion, excluding downstream ranking and API overhead. The runner verifies
the complete rolling manifest and selected sweeps, then writes atomic fold
checkpoints bound to code, runtime and retrieval policy.

The [candidate-generation design](CANDIDATE_GENERATION.md) defines source behavior
and benchmark limitations. The
[retrieval report](CANDIDATE_RETRIEVAL_REPORT.md) contains the complete nine-fold
source comparison and cost measurements. Category candidates pool training counts across the
history's categories; this differs from the historical category recommender's
category-order traversal and implicit global backfill.

## Two-tower retrieval

`src/ecommerce_recsys/retrieval/two_tower.py` implements a CPU two-tower model.
The user tower mean-pools shared item-ID embeddings for recent distinct history
items; the item tower combines its item-ID embedding with its category embedding
from the fold's train-time catalog. Both towers project to L2-normalized vectors,
scored by dot product. Training examples use each user's first occurrence of a
novel item after strictly earlier history; all events at the positive timestamp
are excluded from that history. Five uniform negatives are sampled from items
that were in the train catalog strictly before the positive event.

The same latest-occurrence history encoder is used for training and Two-Tower
inference. `RetrievalContext.ordered_history` preserves the event order needed
by that encoder; its existing deduplicated `history` view stays unchanged for
hybrid and ALS sources. Unknown categories use a reserved bucket. Training is
deterministic on CPU with seed 42, one Torch thread, three epochs and fixed
batches; no future fold events enter training.
The benchmark compares exact catalog scoring at candidate budgets 100, 500 and
1,000 against exact ALS on the same warm targets and cutoff catalogs. Folds 1–4
select configurations; folds 5–9 are post-selection diagnostics, not blind
validation. Cold users have no personalized history representation and are not
pooled into the Two-Tower warm results. See the [two-tower report](TWO_TOWER_REPORT.md) and
[two-tower artifacts](../benchmarks/retrieval/).

## ANN feasibility

The experimental `scripts/faiss_ann_adapter.py` queries a Faiss HNSW index built
from the fitted Two-Tower item vectors, then re-scores its shortlist with exact
Two-Tower dot products and applies the shared candidate contract. This adapter
was used only for a local paired fold-1 pilot. The exact-cost profiler covers
development folds 1–4. All four predeclared ANN settings failed the paired p95
speed gate on fold 1, so the pipeline still uses exact retrieval references; no
ANN source is exposed through `src/ecommerce_recsys/retrieval/` or the hybrid
candidate generator.
Faiss remains outside the core project and serving dependencies. The dedicated
CPU test lock now includes it; local Linux CI reproduction runs the existing
Faiss smoke tests. This does not change the feasibility no-go or establish a
new GitHub-hosted compatibility run.
The [ANN feasibility report](ANN_RETRIEVAL_REPORT.md) describes the evidence and limits.

Published two-tower and ANN artifacts bind the source at commit
`7b27f141f8d1a331bc4ebe0e924db59eeeef9e42`. The current semantic script
names produce new runner fingerprints. Reproduce the frozen artifacts from
that commit; write future runs to distinct artifact paths.

## Ranking dataset

`src/ecommerce_recsys/ranking/dataset.py` derives cutoff-time user, item,
event-type and category-affinity features and keeps hybrid source evidence
as separate score, rank and presence fields. The builder refits the fixed hybrid
sources on each fold's verified training snapshot, writes one request row per
warm target and streams up to 1,000 candidate rows per request. Future target
fields are labels/audit metadata and are excluded from the predictor contract.
Unreachable and retrieved-miss targets remain in the request table.

The development builder permits folds 1–4 only and checks its hit, candidate
count and empty-pool totals against the frozen candidate-retrieval artifact.
It writes Parquet files outside Git and atomically checkpoints their SHA-256
hashes. A separate verifier reopens every file and checks counts, ranks,
source evidence and finite features. The
[ranking dataset report](RANKING_DATASET_REPORT.md) records 30,784 warm
requests, 30,784,000 candidate rows, build cost and limitations. The dataset
builder itself never writes folds 5–9; the ranker runner generates their rows
in memory after its configuration is locked.

## Learned ranking

`scripts/learned_ranker.py` implements a deterministic linear pairwise logistic
ranker using cutoff-time candidate features. Positive targets are compared
with deterministic hard and sampled negatives from their own request pools.
The model uses training-only RMS scales, L2 regularization and score/item-ID
tie-breaking. Fold 2 scores use fold 1 training rows; fold 3 uses folds 1–2;
fold 4 uses folds 1–3. `scripts/benchmark_ranker.py` selects regularization
from those development scores and requires a SHA-bound lock before scoring
folds 5–9. The final model fits labelled folds 1–4 once; retrieval sources
are refit separately for each diagnostic fold's cutoff. The RRF and learned
orders are measured on each request's identical candidate list, retaining
zero-positive requests in the denominator.

The [learned-ranking report](LEARNED_RANKING_REPORT.md) documents pooled and
per-fold Top-K metrics, cost scope, and validity limits. The five later folds
are post-selection diagnostics because those periods were inspected in earlier
experiments. The local snapshot API uses its frozen weights through the
package-native inference scorer, without importing the experiment runner.

## Category-aware re-ranking

`ranking/diversity.py` greedily reorders the first 100 learned-ranked
candidates for a Top-20 output. It uses only a candidate's category from the
fold's train-time catalog. Known categories not yet in the output receive a
fixed novelty bonus; missing categories receive none. Utility ties preserve
the learned-score and item-ID order. The utility uses learned rank rather
than score magnitude or pairwise item distance. The zero-bonus control
reproduces the learned Top-5/10/20 on each request.

`scripts/benchmark_diversity.py` evaluates a fixed bonus grid on chronological
development folds 2–4, locks one choice, and measures that choice against
zero bonus on the same regenerated pools in folds 5–9. It verifies the
published M10/M11 source revision and input hashes because later additions
to the package changed those earlier runners' broad source fingerprints.
The [re-ranking report](DIVERSITY_RERANKING_REPORT.md) defines the category,
denominator, selection and cost contracts. On folds 5–9, the locked bonus
increased distinct known-category slots@20 from 0.125625 to 0.146108 while
Top-20 hits changed from 3,237 to 3,236 on the same 59,323 warm requests.
This offline comparison does not deploy a re-ranker or select a complete
retrieval policy.

## Sequential transition experiment

`retrieval/sequential.py` builds directed transitions between adjacent,
distinct user/timestamp buckets in each fold's training snapshot. Same-time
items form one unordered bucket. The experimental source scores catalog items
from the user's recent training buckets and filters their complete train-time
history. `scripts/benchmark_sequential.py` compares recency-weighted and
equal-weight bucket scores on the same transition table and lookback. A
development artifact and SHA-bound lock precede the folds 5–9 diagnostic.

The ordered policy had 3,799 hits@100 versus 3,824 for its matched control on
59,323 warm user-windows, so this source was not added to the M7 hybrid. The
[sequential report](SEQUENTIAL_RECOMMENDATION_REPORT.md) gives the fold-level
metrics, measured cost and validity limits. This experiment is a direct
candidate source, separate from M11's fixed-pool ranker.

## Offline reference policy

`scripts/benchmark_model_policy.py` compares complete target-free policy calls
from candidate generation through Top-20 ordering. Development scores use
rankers trained on earlier labelled folds; diagnostics reuse the frozen ranker
trained on folds 1–4. The warm route is full-hybrid learned ordering with no
category bonus. The cold route is explicit recent popularity. These choices
come from the complete development comparison, before this runner's later-fold
scoring, and remain unchanged on resume.

The runner includes direct sources, full/no-ALS RRF, learned ordering and the
fixed category option. No-ALS learned variants transfer the same full-pool
model rather than retrain it. Quality can share source outputs and immutable
features; independent calls on matched request samples measure inference cost.
`evaluation/model_policy.py` validates all-request quality numerators, pools
them separately by cohort and applies the frozen selection rule. The
[policy report](MODEL_POLICY_REPORT.md) records scope and limitations. This is
an offline reference. Its model state is packaged as described below and
exposed through the local snapshot service without retuning.

`scripts/verify_model_policy.py` checks the completed source/data/lock chain and
the earlier independent feature audit, then records explicit seeds and hashes
in a separate provenance supplement. It performs no model fit and preserves the
original benchmark JSON. The supplement is an evaluation record, without a
serialized model bundle or service loader.

## Versioned model snapshot

`scripts/build_model_artifacts.py` verifies the complete policy provenance and
fits its fixed retrieval sources at one declared cutoff. It persists ALS
factors, mappings, full sparse seen sets, ItemKNN neighbors, category/popularity
state, feature aggregates and frozen ranker weights/scales. A sealed manifest
binds eleven safe-format components to their hashes, shapes/schemas, numerical
environment, code identity and upstream evidence. Generated versions live
outside Git under `artifacts/`; the builder publishes a completed staging
directory with an atomic rename and refuses version overwrites.

`ecommerce_recsys.artifacts.load_bundle` verifies inventory, hashes and semantic
consistency before restoring direct-source adapters. A small package-native
inference scorer implements the published feature transforms. The runtime
imports no benchmark scripts and reads no training data. Known snapshot users
use their full stored seen set and cutoff-time features; unknown users use
explicit recent popularity. The response carries item IDs, route, bundle
version and cutoff. It supports deterministic prefixes from 1 to 20 items.
It still depends on compatible package implementations and numerical libraries.
Python major/minor and library checks are strict; OS/architecture differences
warn. Each component is hashed once before loading. Compatibility with the
original reader is restricted to unchanged prediction code and dependencies.

The [artifact contract](MODEL_ARTIFACTS.md) defines the supported snapshot lookup,
round-trip and loaded-quality checks, resume behavior and limitations. Dynamic
user history, HTTP serving, concurrency, cache and live fallback orchestration
are outside the artifact layer. The separate HTTP boundary below controls
admission to its process-wide numerical calls.

## Local snapshot HTTP interface

`serving/contracts.py` defines strict input/output schemas and mandatory model
settings. `serving/app.py` supplies async FastAPI routes and lifespan ownership;
constructing/importing the application performs no model load.
`serving/boundary.py` bounds JSON bodies before parsing, rejects duplicate keys
and nonfinite numbers, and assigns server-generated request IDs.

`serving/service.py` restores the digest-pinned bundle once in a dedicated
worker and checks warm/cold startup predictions. One process-wide permit
serializes numerical work. Recommendations run outside the ASGI event loop;
uncached overlap receives 503 busy under the default policy while health probes
remain responsive. The worker
retains its permit after HTTP cancellation. Shutdown drains accepted work;
unexpected inference/output errors mark the service failed until restart.

The supported `python -m ecommerce_recsys.serving` launcher uses one Uvicorn
worker and accepts only loopback bindings. Optional HTTP requirements are isolated from
the historically fingerprinted `pyproject.toml`. The
[API contract](RECOMMENDATION_API.md) documents routes, snapshot semantics,
validation, lifecycle and limits. A separate HTTP process matches the 101
sealed reference outputs. Its 2.19 GiB ready RSS exceeds the charter target;
sequential local timings do not establish concurrent-load service objectives.
The historical HTTP receipt records the pre-cache interface; current schema
1.2.0 retains the 1.1.0 cache fields and adds the input/access boundary described
below. Public hosting remains absent.

## Optional cache and overload fallback

`serving/cache.py` stores immutable Top-20 results in a lock-protected LRU with
insertion-based monotonic TTL and entry/count bounds. Namespace and context
identity bind the manifest/policy, known-user snapshot or canonical cold route.
Cache hits reconstruct fresh request metadata and recheck eligibility. Cache
failure disables this optimization and bypasses to the healthy primary.

`serving/service.py` checks readiness before cache lookup and after acquiring
numerical admission. A hit
can answer during another model call. An optional overload policy filters the
full seen history against a startup-prepared recent Top-1,000 pool and returns
`recent_popularity_fallback` with explicit degraded reason and manifest lineage.
It does not call a model, refill the truncated pool or populate the primary
cache. Primary or fallback context/output failures invalidate cache/pool state
and make the service unready until restart. Only the owning primary worker
releases its permit. Startup cancellation and shutdown share one cleanup task;
startup cannot become ready after shutdown starts. Shutdown drains work and
drops both states.

Defaults keep caching disabled and overload rejected. The
[service report](SERVICE_CACHE_AND_FALLBACKS.md) and
[pre-observability HTTP receipt](../benchmarks/serving/cache_state_validation_v1.json) separate
uncached/miss/hit costs and declare byte accounting and RSS scope. Normal output
parity holds on the 101-reference sample; cache-on sampled peak exceeds 2 GiB RSS.
No deployed cache dependency, hot replacement or automatic model recovery exists.

## Local observability

`serving/observability.py` owns a lock-protected, fixed-schema registry per app.
`serving/observation_boundary.py` observes ASGI completion and early/cancelled
paths outside the JSON validation boundary. Service/cache hooks retain worker,
admission and cumulative cache events independently of HTTP waiter cancellation.
The dedicated owned event logger emits allowlisted JSON; the supported launcher
configures its stderr handler without changing root logging on package import.

`GET /metrics` exports Prometheus text 0.0.4 on the existing loopback listener.
Scrapes do not run models, take numerical admission, expire entries or disable
cache state. Current state/cache inventory and RSS are point samples; sampler
failures have explicit flags. User/item/request IDs and raw URLs/errors are
excluded from metric labels. One model information gauge binds the loaded
version/manifest. HTTP and worker histograms use distinct timing boundaries.
Owned cleanup records one startup outcome/duration across stop or repeated
cancellation. Invalid cache samples are omitted without mutating the source.

The [observability contract](OBSERVABILITY.md) defines metric dimensions, owned
event privacy, event-sink failure isolation, cancellation accounting and operational
queries. External collectors, dashboards and alert delivery remain unimplemented.
Synchronous local logging can block, and third-party logs are outside the owned
JSON redaction guarantee. Instrumentation adds no new accuracy or SLA claim.

## Local input and exposure boundary

`serving/security.py` validates immutable nonsecret limits, explicit local
authorities and optional secret-safe operator credentials. The supported
launcher disables proxy headers, restricts loopback binding and installs the
pinned `serving/http_protocol.py` adapter. It closes excess connections, enforces
complete-header/target limits before scope creation and uses absolute,
generation-checked header timers across keep-alive cycles.
It also rejects trailer declarations before dispatch and nonempty chunked
trailers before body completion, including after an ASGI reader starts.

`serving/security_boundary.py` checks Host/Origin, request attempts, credentials
and framing before body work. `serving/rate_limit.py` owns atomic global/peer
buckets, bounded expiring peer state and reader slots. `serving/boundary.py`
adds the absolute body deadline to its existing pre-copy byte/strict-JSON guards.
Slots release before model execution and on timeout/disconnect/cancellation.
Unsupported body routes close immediately; redirects cannot bypass the boundary.

These app-local resources remain separate from the unchanged numerical permit,
cache and failure transitions. Security denials preserve readiness and never
become degraded successes. Fixed telemetry distinguishes pre-ASGI transport
events from application HTTP outcomes. The [hardening contract](API_HARDENING.md)
defines default budgets, bearer limitations, error behavior, pinned verification
and the absence of public security or workload-SLO certification.

## Functional integration boundary

```text
Unit regressions + fitted synthetic snapshot
    -> actual child launcher and loopback HTTP checks
Sealed real bundle + trusted manifest/quality pins
    -> isolated package loader -> exact producer-reference parity
    -> unchanged hardened HTTP verifier -> fresh paired reference evidence
All checks + source/input/runtime identities
    -> verify_release.py -> non-overwriting functional validation receipt
```

`tests/integration/` uses an actual fitted synthetic bundle for portable process
tests; its separately enabled real-bundle case never substitutes that fixture
for Retailrocket evidence. `scripts/release_validation.py` checks completeness,
pins, test outcomes and numerical/output policy before `verify_release.py`
publishes a successful record. Profiles execute sequentially, with bounded
child-process ownership and ignored private logs. Current model and HTTP code
remain unchanged. The [test strategy](TESTING_AND_RELEASE_GATES.md) defines
exact parity, explicit skip rules, platform/lifecycle scope and why functional
success does not establish deployment eligibility or new quality results.

## Isolated Linux runtime

```text
Allowlisted package/container source + exact hashed dependency wheels
    -> pinned two-stage Linux/amd64 image (model stays outside the image)
Original sealed bundle -> read-only /model mount + trusted external SHA
    -> original package HTTP launcher, non-root, read-only root, network=none
Producer-exact private arrays + sealed references
    -> isolated model/HTTP probes -> non-overwriting container receipt
```

`containers/` supplies the build recipe, complete wheel locks, bounded internal
readiness check and operator-only probes. `verify_linux_container.py` validates
installed source/dependency identity, resource/isolation settings, all 101
references, startup rejection and graceful cleanup. The runner also checks
actual context-export canaries, creates missing private scratch storage,
confirms owned container absence and validates memory telemetry. The source
package and original bundle are unchanged. Candidate pools, evidence, routes and ordered
outputs compare exactly; only feature/score portability uses the separately
approved tolerance. The [container report](LINUX_CONTAINER.md) records the
initial bitwise failure, numerical policy and measured scope. This Docker
Desktop Linux configuration has no published endpoint; its 4 GiB resource cap
does not revise the 2 GiB serving RSS target or establish release/load readiness.

## Controlled local release

Hosted CI checks pinned wheels/actions, workflow policy/schema, lint, unit and
fitted-process profiles. The separately gated real lane requires a same-owner
private manual caller, protected environment, trusted runner, exact current
source SHA and a successful matching main CI attempt. These external settings
have not been configured here.

`snapshot_release.py` keeps immutable source/image/model/evidence-bound
descriptors and an OS-owned store lock. It journals a reserved candidate before
Docker create, verifies actual HTTP references before atomically publishing the
active pointer, then retires the former active. Failed postcommit cleanup keeps
an explicit recovery journal. If the target dies before that journal is
recovered, recovery atomically retains former-instance ownership without
removing it. Rollback verifies a fresh previous instance, then retires the dead
target and retained instances. Abnormal retirement is not called graceful cleanup.
Every release-verifier invocation requires external recovery storage. The
workflow validates physical bundle/interpreter/recovery paths before checkout
and blocks unfinished prior
attempts. Semantic rejection of a checksum-valid descriptor with the wrong
manifest leaves active state and container ownership unchanged. The CI policy
also pins Python, dependency imports and the manifest value; its inventory
covers build/test inputs rather than docs or generated gate receipts.
Final success publication requires exactly one graceful cleanup event. The [release runbook](RELEASE_WORKFLOW.md) records the actual
control exercise, strict CI profiles and their limits. Model/package sources and
all upstream receipts remain unchanged. Network-isolated local pointers are not
public traffic routing, distributed coordination or production deployment.

## HTTP workload assessment

The [capacity runner](../scripts/benchmark_http_capacity.py) owns separate
instances of the unchanged qualified image. A
[bounded driver](../scripts/http_capacity_workload.py) executes via stdin in each
container, without adding scripts to the image or changing the package/service.
It offers open-loop requests over internal loopback, validates sealed output
prefixes and reconciles telemetry. Checkpoints advance only after verified
graceful removal; source, policy, model and machine identity prevent mixed resumes.
Live and resumed measurements share telemetry, throughput, sampling-coverage and
traffic-denominator checks. The fixed scheduler rejects unsupported mix metadata.

Driver and service share a 2 CPU/4 GiB cgroup. Serving PID 1 RSS/CPU, client
resource cost, cgroup peak, success/rejection latency and dispatch timing have
distinct scopes. All four cells preserve reference parity; the 2 GiB RSS gate
remains unmet. Primed cache is an explicit repeat-traffic control. Defaults,
security quotas and model behavior stay unchanged. The
[report](HTTP_CAPACITY_REPORT.md) records results and finite-sample/host limits.

## Load and failure verification

The [resilience verifier](../scripts/verify_service_resilience.py) orchestrates
fresh owned instances of the unchanged image. Its
[driver](../scripts/service_resilience_workload.py) uses pinned capacity helpers
in a private namespace via stdin; no probe code or fault hook is installed in
the model/service image. Fixed load phases share live/resume semantic checks.
Source/policy/model/machine and full test evidence bind the external checkpoint.
Windows JUnit must match exact collected test identities; Linux evidence binds
the complete test/configuration source and full profile counts.

Separate scenarios exercise wire disconnect, observed in-flight SIGTERM and
readonly startup-file faults. Event-controlled tests prove cancelled-waiter and
model/executor failure ownership. The frozen release controller runs a fresh
same-model journal recovery/rollback exercise, with independently pinned child
evidence. Each completed step requires exact owned cleanup. The
[report](SERVICE_RELIABILITY_REPORT.md) separates measured targets from functional
completion and retains the unmet 2 GiB RSS and target-host limitations.

## Deployment decision boundary

The [offline assessor](../scripts/assess_deployment.py) uses only bounded JSON
inputs and standard-library arithmetic. Five immutable model/operational receipts,
new source, a dated hosting catalog and policy bind a deterministic, non-overwriting
assessment. It derives process RSS, component storage and container/host
reservation floors, distinguishes known cost subtotals from unknown bills and
retains explicit deployment blockers. It performs no networking, model loading,
cloud-account action or service configuration change.

Local execution remains current. A conditional free Arm host requires separate
image/numerical and native-host qualification. The [design](DEPLOYMENT_DESIGN.md)
specifies future private delivery, a gateway sharing the loopback API namespace,
maintenance stop/start and off-host recovery requirements. None is a deployed
adapter, public router or memory-budget waiver. The frozen M21-M24 qualification
paths and their receipts remain unchanged.

## Model engineering and trade-offs

| Area | Current finding | Detail |
| :--- | :--- | :--- |
| ItemKNN neighbors | Binary user-item cosine, top 20 neighbors, minimum five interactions, support-aware shrinkage | [Rolling report](ROLLING_BENCHMARK_REPORT.md) |
| ItemKNN shrinkage | Lambda 100 selected on folds 1–4; 100, 200, and 500 tie on pooled HR@20, with NDCG breaking the tie | [ItemKNN sweep](../benchmarks/rolling/item_knn_sweep.json) |
| ALS capacity | 128 factors and 40 iterations selected; its one-hit selection advantage over 20 iterations is weak relative to extra fitting cost | [Rolling report](ROLLING_BENCHMARK_REPORT.md) |
| Factor memory | Earlier estimate: 399.41 MiB at 64 factors and 798.81 MiB at 128 factors for factor arrays, excluding full process memory | [MF report](MF_EXPERIMENT_REPORT.md) |
| Latency | Local per-call measurement only; see fold-level coverage and p95 latency in rolling artifacts | [Reference results](../benchmarks/rolling/results.json) |

The rolling scripts can resume after interruption. The manifest hashes the interactions source, raw item properties, and each fold Parquet file; the runners verify these hashes before using cached results. ALS training and rolling benchmark calls use one numerical worker thread for repeatability. The result artifacts disclose that folds 5–9 are post-selection diagnostics, not blind validation.

The benchmark uses identical folds and target users for every warm-user model. See [project status](PROJECT_STATUS.md) for current results and the next milestone. The [baseline](BASELINE_REPORT.md) and [MF](MF_EXPERIMENT_REPORT.md) reports document earlier model experiments.
