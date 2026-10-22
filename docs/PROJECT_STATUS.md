# Project status

**Updated:** 2026-10-22

A [local static explorer](SNAPSHOT_EXPLORER.md) now presents four fixed warm
references and one cold context from the original fold-9 bundle. Exported traces
match sealed references; the UI browses precomputed Top-K, same-pool learned/RRF
order and retrieval evidence. This begins demo work locally; M26/M27 deployment
and host verification remain open, and M28 is not published. No model, API,
quality result or resource budget changed.

**Stage:** M25 completes the deployment design and free-first cost assessment.
The current execution mode remains local; OCI A1 Always Free is a conditional
Arm investigation. The offline assessor pins model/container/release/capacity/
reliability evidence and records resource arithmetic, dated cost assumptions and
deployment blockers. No cloud resources or public gateway were created, and no
host is approved. Architecture, account, exposure, target-host and 2 GiB RSS
gates remain open.

M24 completes a fixed local load, failure and recovery matrix on the
unchanged Linux snapshot: sustained/burst traffic, bounded memory occupancy,
observed disconnect/in-flight SIGTERM, three startup-file rejections and fresh
same-model release recovery/rollback. Full Windows/Linux gates and original-model
parity pass. Workload/resource targets remain separate; deployment eligibility
stays false and the 2 GiB RSS budget is not waived.
M23 completes a fixed HTTP workload assessment of the unchanged
Linux snapshot: four fresh-process 150-second cells, 2,550 measured arrivals
and 808 pre/post reference checks. Outputs and telemetry reconcile; every cell
removes its owned container gracefully. Constructed primed-cache and uncached
traffic remain distinct. Serving RSS still exceeds 2 GiB; no production
eligibility or maximum sustainable throughput is claimed.
M22 adds pinned hosted CI profiles and an exercised isolated local
release controller: immutable image/model/evidence identities, verified candidates,
atomic active state, journal recovery and rollback after an active-process crash.
The new real-qualification GitHub lane requires a protected private caller and
runner; it has not been configured or executed remotely. Operational success
does not establish deployment eligibility or waive the 2 GiB RSS budget.
M21 adds a pinned, non-root Linux/amd64 snapshot container with
read-only artifact delivery and isolated real-bundle/HTTP qualification.
Candidate/evidence/output equality remains exact; a separately approved
cross-platform feature/score tolerance preserves the original same-host gate.
It provides no public endpoint and does not waive the 2 GiB memory target.
M20 adds a functional integration gate with separate unit, fitted
HTTP-process and explicit real-bundle profiles, exact numerical/output parity,
source/input identity checks and a non-overwriting validation receipt. It does
not authorize deployment or recompute model quality. M19 adds tested local
input/access controls: connection/header/body
budgets, absolute input deadlines, bounded global/socket-peer attempt limits,
Host/Origin policy and optional shared bearer credentials. The unchanged model
passes paced real HTTP reference parity under API 1.2.0; both ready RSS samples
still exceed 2 GiB. Public deployment and per-user authorization remain absent.
M18 adds bounded local metrics and structured service events, with
separate HTTP/worker timing, cache/admission accounting and process RSS sampling.
M17 adds optional bounded snapshot caching and explicit overload-only
fallback. Cache off/miss/hit preserve reference outputs; repeated-request
latency gates pass, while the serving memory target remains unmet.
M16 exposes the frozen snapshot through a local HTTP API with strict
validation, health probes and bounded inference admission. Real HTTP output
parity passes; measured ready RSS exceeds the charter's 2 GiB target.
M15 provides immutable model artifacts and Python snapshot inference
separated from training. The fold-9 bundle passes exact reference parity and full warm/cold
quality reconciliation. M14 has completed
development comparison and locked an offline reference: full-hybrid learned
ordering for warm requests and recent popularity for cold requests. All
fixed-policy diagnostics on folds 5–9 are complete.
M13's category-novelty bonus remains an offline trade-off option.
M12's sequential and M9's ANN experiments remain no-go for
their tested settings. Evaluation remains offline; the HTTP API serves a
historical snapshot locally, without public deployment or online evaluation.
Folds 5–9 were inspected in earlier milestones and remain post-selection
diagnostics, not blind validation.

## Implemented

| Area | Current implementation |
| :--- | :--- |
| Data | Retailrocket ingestion, interaction processing, train-time item and category catalogs |
| Evaluation | Nine rolling time folds, shared warm targets, separate cold-user cohort, causal checks, HR/MRR/NDCG and coverage |
| Models | Random, global/recent/category popularity, ItemKNN, implicit ALS, educational MF/BPR |
| Retrieval | Common candidate interface, exact ALS, ItemKNN, category and popularity sources, source-aware reciprocal-rank fusion |
| M8 retrieval | Deterministic CPU two-tower retriever with shared history encoding, train-only category features, sampled-softmax training and exact catalog scoring |
| M9 feasibility | Reproducible exact-cost profile and paired fold-1 ANN pilot; no ANN source promoted to the package after the speed gate failed |
| M10 ranking data | Causal warm request/candidate Parquet for folds 1–4, as-of features, zero-positive request audit, SHA-bound checkpoints and independent file verification |
| M11 learned ranking | Deterministic pairwise linear ranker, chronological development selection, SHA-bound lock and same-pool RRF comparison on folds 5–9 |
| M12 sequential experiment | Train-time next-bucket transition retrieval and a matched ordered/equal-weight ablation; no source promoted after the primary gate failed |
| M13 re-ranking | Category-novelty re-ranking of the fixed learned Top-100 shortlist, development selection/lock and same-pool diagnostic on folds 5–9 |
| M14 model policy | Complete target-free offline policy calls, eleven warm/three cold fixed alternatives, development selection/lock and resumable matched-cost diagnostics |
| M15 artifacts | Safe-format snapshot export, SHA-bound manifest, package inference loader separated from training, snapshot-user adapter and complete fold-9 loaded-quality reconciliation |
| M16 local API | FastAPI request/response contract, pinned startup load, live/ready probes, one active inference call, explicit busy/error responses and real loopback output verification |
| M17 cache and fallback | Opt-in insertion-TTL/LRU cache with entry/count bounds, snapshot/context identity, cache-failure bypass and an explicitly attributed seen-filtered busy fallback |
| M18 observability | App-local Prometheus text export, bounded dimensions, owned JSON events, independent HTTP/worker outcomes, persistent cache events and failure-isolated RSS sampling |
| M19 input and exposure | Pinned pre-ASGI connection/header guards, absolute body deadline, reader/rate/table bounds, local Host/Origin policy, optional shared bearer mode and safe denial telemetry |
| M20 integration strategy | Unit and actually fitted child-process HTTP profiles, explicit isolated real-bundle parity, strict evidence checks and a source-pinned functional gate |
| M21 Linux container | Digest/hash-pinned image inputs, non-root read-only execution, bounded resources, real cross-platform references, HTTP denials/recovery and SIGTERM cleanup |
| M22 controlled release | Hashed CPU CI lock, immutable Action pins, strict profile evidence, private real-lane prerequisites and actual local promotion/recovery/crash-rollback checks |
| M23 HTTP capacity | Four fixed open-loop workloads, per-outcome/cohort/cache timing, sampled resources, reference parity and checkpointed owned cleanup |
| M24 local reliability | Fixed sustained/burst/pressure workloads, witnessed lifecycle and startup faults, explicit fixture cancellation/failure tests and fresh journal-recovery/rollback evidence |
| M25 deployment design | Source-pinned offline hosting/resource/cost assessment, conditional free-tier choice and proposed delivery/exposure/recovery contract; no infrastructure provisioned |
| Reproducibility | Fixed seeds, numerical thread control, resumable checkpoints, source and fold SHA-256 verification, CI |

The [architecture overview](ARCHITECTURE_CURRENT.md) describes the code paths. The [evaluation protocol](ROLLING_EVALUATION_PROTOCOL.md) defines the cohorts and eligibility rules.

## Recommendation results

The rolling benchmark includes **90,107 warm user-window targets from 71,982 distinct users** across nine folds. A separate **1,262,289 first-time users** form the cold cohort. In the warm cohort, 11.10% of targets are absent from their fold's training catalog and cannot be retrieved by train-only models.

ItemKNN and ALS were selected on folds 1–4. Their configurations and the four fixed baselines were measured on the same **59,323 warm targets** in folds 5–9:

| Model | HR@20 | MRR@20 | NDCG@20 |
| :--- | ---: | ---: | ---: |
| Random | 0.000034 | 0.000004 | 0.000010 |
| Global Popularity | 0.007855 | 0.001671 | 0.002986 |
| Recent Popularity | 0.008209 | 0.002424 | 0.003693 |
| Category Popularity | 0.041518 | 0.011722 | 0.018217 |
| ItemKNN (shrinkage 100) | 0.041889 | 0.018687 | 0.023962 |
| Implicit ALS (128 factors, 40 iterations, regularization 0.01) | 0.027291 | 0.009456 | 0.013385 |

The ItemKNN–Category HR@20 gap is 0.000371, and their fold-level ordering changes. No robust winner is claimed. Across all nine folds, the 1,262,289 first-time-user targets give global and recent popularity HR@20 of 0.011394 and 0.011649 respectively; those scores are not pooled with warm results.

**Validity limit:** Reference scores for folds 5–9 were inspected before the sweep configurations were locked. These are post-selection diagnostic results, not a blind holdout. See the [benchmark report](ROLLING_BENCHMARK_REPORT.md) and [result artifacts](../benchmarks/rolling/) for per-fold metrics, coverage, and latency.

## Candidate retrieval results

The M7 artifact contains **126 comparisons**: nine folds, two cohorts and seven
generators. The following candidate-recall figures use the same 59,323 warm
targets in folds 5–9. They retain the post-selection diagnostic validity limit.

| Generator | Recall@100 | Recall@500 | Recall@1000 |
| :--- | ---: | ---: | ---: |
| Exact ALS | 0.050705 | 0.087116 | 0.109216 |
| Hybrid without ALS | 0.081183 | 0.165180 | 0.213206 |
| Hybrid | 0.079750 | 0.163832 | 0.211537 |

Adding ALS changes pooled hybrid Recall@1000 by **-0.167 percentage points**.
This is a net ablation difference, not a statistical significance claim. The
[retrieval report](CANDIDATE_RETRIEVAL_REPORT.md) details all source results,
empty/full pool rates, cold retrieval, source contributions and cost. Regression
and artifact validation are documented with reproduction commands in that report.

## M8 two-tower results

The corrected Two-Tower v1 configuration (dimension 128, history 50) was
selected on folds 1–4. On folds 5–9 it achieved pooled Recall@100/500/1000 of
0.044485 / 0.096185 / 0.127640 over 59,323 warm user-windows. The same-window
ALS v2 comparator achieved 0.050705 / 0.087116 / 0.109216. These folds had been
inspected before configuration lock, so the results are post-selection
diagnostics, not blind validation or evidence of statistical significance.
The [two-tower report](TWO_TOWER_REPORT.md) includes per-fold results, cost,
latency scope, artifact hashes and reproduction commands.

## M9 ANN feasibility result

The M9 exact-cost profile measured selected Two-Tower retrieval on 1,000 sampled
warm requests per development fold, repeated three times. Exact p95 at budget
1,000 was 8.426, 13.806, 12.083 and 13.550 ms on folds 1–4. Since three folds
crossed the declared 10 ms cost trigger, a Faiss HNSW pilot compared four index
settings with paired exact calls on fold 1. All four ANN p95 values were slower
than exact (ANN 14.844–35.411 ms; paired exact 9.311–10.698 ms). Each failed the
gate requiring ANN p95 at most half of exact on every development fold. M9
stopped at that point: no full ANN quality sweep, folds 5–9 ANN diagnostic or
serving claim exists. The [ANN feasibility report](ANN_RETRIEVAL_REPORT.md) provides sample
hit counts, index costs, compatibility limits and the no-go decision.

## M10 ranking dataset

M10 regenerated the fixed M7 full-hybrid pool for **30,784 warm user-windows**
on development folds 1–4. It produced 30,784,000 candidate rows, including
6,717 positive rows, for pooled Candidate Recall@1000 of **0.218198** with all
warm targets in the denominator. The 5,087 targets outside their fold's
train-time catalog and 18,980 catalog-reachable targets missed by retrieval
remain in the request audit. All four folds reproduced M7's hit and pool-count
totals; an independent Parquet scan found no null or nonfinite values. The
[ranking dataset report](RANKING_DATASET_REPORT.md) explains the feature schema,
provenance, build cost and limits. These are retrieval-data measurements, not
learned-ranker Top-K results.
The ItemKNN/ALS configurations and full-hybrid candidate policy were selected
using folds 1–4. M10's fold 1–4 recall is therefore an in-sample dataset
construction diagnostic, not an independent retrieval-quality estimate.

## M11 learned ranking

M11 trained on labelled warm folds 1–4 and selected `alpha=0.01` from a fixed
three-setting grid using pooled development HR@20. On the same regenerated
full-hybrid pools for **59,323 warm user-windows** in folds 5–9, RRF ranked
**2,285** targets in the Top-20 (HR@20 **0.038518**); the locked ranker ranked
**3,237** (HR@20 **0.054566**). The difference is **952 hits** or **0.016048**
in HR. Both orders share Candidate Recall@1000 of **0.211537**
(12,549/59,323 targets in pool). All five folds had a positive hit difference.
These are post-selection diagnostics, not blind validation or a significance
claim. The [learned-ranking report](LEARNED_RANKING_REPORT.md) gives per-fold
HR/MRR/NDCG, model policy, cost scope, artifact provenance and limitations.

## M12 sequential retrieval result

The six-setting development grid selected an ordered transition source with
20 timestamp buckets and decay 0.8, paired with an equal-weight control using
the same buckets. On **59,323 warm user-windows** in folds 5–9, ordered
weighting found **3,799** targets by rank 100 (Recall@100 **0.064039**);
equal weighting found **3,824** (Recall@100 **0.064461**). Both found **4,035**
by rank 1,000. The ordered policy lost 25 hits on the predeclared primary
metric, with fewer hits@100 in every fold. The decision is **no-go** for adding
this source to the hybrid. The [sequential report](SEQUENTIAL_RECOMMENDATION_REPORT.md)
records the causal timestamp-bucket policy, per-fold numerators, cost and
limitations. These are post-selection diagnostics, not blind validation.

## M13 category-aware re-ranking

The fixed bonus grid selected `0.10` using chronological development folds
2–4 and a predeclared relevance/diversity gate. On the **59,323 warm
user-windows** in folds 5–9, the bonus raised distinct known-category
slots@20 from **0.125625** to **0.146108** on a `20 × requests` denominator.
The same-pool learned baseline had **3,237** hits@20 (HR@20 **0.054566**);
the bonus had **3,236** (HR@20 **0.054549**). Pooled NDCG@20 changed from
**0.026383** to **0.026135**, and catalog item coverage decreased slightly
in every fold. Hits@5 also fell from **1,649** to **1,638**; the locked
selection gate constrained pooled Top-20, not shorter budgets or individual
folds. Candidate Recall@1000 stayed **0.211537** because the pool
did not change. These are descriptive post-selection diagnostics, not blind
validation or a significance claim. The [re-ranking report](DIVERSITY_RERANKING_REPORT.md)
provides per-fold numerators, category-metadata handling, measured cost,
provenance and limits. The subsequent complete-policy comparison is described
below.

## M14 offline reference policy

Development folds 2–4 contain **25,438 warm** and **405,518 cold** user-windows.
The fixed accuracy-first rule selected full-hybrid learned ordering with
**1,631 warm hits@20** (HR@20 **0.064117**) and recent popularity with
**4,557 cold hits@20** (HR@20 **0.011237**). The separate routes are bound
to a selection lock. The complete folds 5–9 diagnostic contains **59,323 warm**
and **715,331 cold** targets. The locked warm route has **3,237 hits@20**
(HR@20 **0.054566**), versus **3,120** for no-ALS learned transfer. The locked
cold route has **8,416 hits@20** (HR@20 **0.011765**); popularity RRF has
**8,945** on the same later cohort. The development lock keeps recent despite
that later HR advantage. There are **112 fixed comparisons** across both
phases. The
[policy report](MODEL_POLICY_REPORT.md) defines the finite grid, transferred
no-ALS ranker, denominator, matched inference timing and validity limits.
Full-source fit estimates are 301.88–632.22 seconds/fold, versus
34.71–115.25 without ALS. These inspected later periods remain post-selection
diagnostics; the reference is selected by accuracy, without a serving latency
or resource budget.
The [provenance supplement](../benchmarks/model_policy/provenance_v1.json)
adds explicit seed and independent feature-audit bindings after the run,
preserving the original result and selection-lock bytes.

## M15 model artifacts

The [artifact contract](MODEL_ARTIFACTS.md) and
[validation receipt](../benchmarks/artifacts/fold09_v1.json) record the immutable
fold-9 snapshot, 101 exact producer/loader reference traces and loaded-policy
parity on 13,539 warm and 142,024 cold targets. This verifies packaging of the
unchanged reference; it adds no independent accuracy evidence. Generated model
bundles remain outside Git; checksummed validation receipts are tracked.
The [loader review](../benchmarks/artifacts/fold09_loader_v1.json) preserves that
manifest, verifies the current reader against 101 exact traces and records
unchanged prediction-code identity. OS/architecture differences now warn;
Python major/minor and library compatibility remain enforced. The later
[Linux qualification](LINUX_CONTAINER.md) separately checks this full snapshot;
the original loader receipt does not provide that evidence.

## M16 local HTTP API

The [API contract](RECOMMENDATION_API.md) defines strict snapshot-user requests,
Top-1–20 output, explicit cold routing, health states and sanitized errors.
One dedicated worker keeps model calls outside the event loop; process-wide
admission rejects overlap with 503 rather than queueing numerical work.
Cancellation retains admission until computation ends, and graceful shutdown
waits for accepted work. Unexpected inference errors require restart.

The [HTTP boundary receipt](../benchmarks/serving/http_boundary_v1.json) records exact
output parity for 100 warm and one cold reference, six prefix checks and seven
invalid-request checks. It preserves the original manifest and reader identity.
On Windows, launch-to-readiness was 20.61 seconds; 100 sequential warm calls
had p95 231.36 ms and p99 303.02 ms. These are smoke measurements, not an SLA.
Ready server RSS was 2.19 GiB, so the 2 GiB charter target remains unmet.
This receipt precedes the optional cache/fallback extension below. Public
deployment remains unimplemented. The later [container check](LINUX_CONTAINER.md)
provides separate finite Linux evidence, with an explicit numerical tolerance.

## M17 bounded cache and overload fallback

The [service report](SERVICE_CACHE_AND_FALLBACKS.md) defines immutable Top-20
cache entries, exact K prefixes, canonical cold context, insertion TTL, LRU and
entry-memory accounting. Cache and busy fallback remain opt-in. Default overload
still returns 503. An enabled fallback uses the verified recent Top-1,000 pool,
filters the full stored seen history and exposes degraded route/reason/lineage.
Primary or fallback context/output failure invalidates cached/prepared state
and requires restart. Admission rechecks readiness after taking the permit;
startup cancellation and shutdown share worker cleanup and cannot publish late
readiness.

The [paired HTTP receipt](../benchmarks/serving/cache_state_validation_v1.json) matches
100 warm and one cold reference in each off/miss/hit pass. Warm p95 is
236.69 / 221.35 / 1.15 ms respectively. Repeating the cached pass makes no
additional primary calls; final cache state has 101 entries and 217,152 charged
bytes within the 256-entry/1 MiB settings. Both prospective latency gates pass
on this constructed repeat sample; no production hit rate or SLA follows.
Separate off/on server ready RSS is 1.80/1.87 GiB; sampled peaks are 1.93/2.03
GiB. The cache-on process exceeds the 2 GiB charter budget, so compliance remains
unestablished. These process differences do not measure isolated cache allocation cost.

## M18 local observability

The [observability contract/report](OBSERVABILITY.md) defines bounded metrics,
owned JSON events and independent HTTP/worker accounting. The
[real HTTP receipt](../benchmarks/serving/observability_lifecycle_validation_v1.json) binds
pre-hardening 1.1.0 service/runner/requirements and the unchanged model. All reference
outputs match; off/on telemetry reconciles 106/215 HTTP invocations, 102/210
completed recommendations and 107/216 JSON records. Final scrapes contain
105/135 metric samples with no observer errors. Fault/cancellation/privacy
paths are covered separately by deterministic tests.

Warm client p95 is 241.85/231.69/1.85 ms for off/miss/hit, and both prospective
cache latency gates pass. Uncached p99 is 519.14 ms, above the initial 500 ms
target. Sampled off/on process peaks are 2.25/2.40 GiB, exceeding
the charter's 2 GiB target. No production hit-rate, workload SLO, installed
dashboard/alerting or Linux full-bundle claim follows.

## M19 local input and exposure controls

The [hardening contract/report](API_HARDENING.md) defines the prospective limits,
access policy and [source-pinned receipt](../benchmarks/serving/hardening_boundary_validation_v1.json).
The launcher stays loopback-only and ignores forwarded identity. Header/body
deadlines, socket/reader limits and atomic global/peer buckets reject unsafe
input before model/cache/fallback execution. Trailer declarations and nonempty
chunked trailers are rejected before body completion, with separate transport
and disconnected-reader accounting. A shared bearer token is optional;
it grants snapshot-wide access and does not implement per-user authorization.

All 100 warm/one cold references match across anonymous cache-off and bearer
miss/hit paths, with prefix/canonical-cold checks and healthy recovery after
denials. Off/on telemetry reconciles 136/238 HTTP invocations and 111/211
deliveries with no observer errors. Warm client p95 is 240.77/240.69/28.77 ms
for off/miss/hit, including a new TCP connection per call; these timings cannot
isolate security overhead or be compared directly with earlier persistent
connections. Ready RSS is 2.20/2.19 GiB and sampled peaks 2.42/2.40 GiB; the
2 GiB target remains unmet. No public-security, Linux full-bundle or SLO claim
follows from local fault probes and fixtures.

## M20 integration and functional gates

The [test strategy](TESTING_AND_RELEASE_GATES.md) separates synthetic fitted
process checks, real loader/reference checks and historical full-fold quality.
The functional command runs profiles sequentially and creates a new
[receipt](../benchmarks/release/integration_boundary_validation_v1.json) only when source,
input pins, test outcomes, parity and finite HTTP telemetry checks agree.
Fixture tests cover warm/cold and exhausted contexts, cache off/on, request
validation/access denials, corrupt startup and stop/restart. The real profile
compares all 100 warm/one cold producer traces without fitting a Retailrocket
model. CI configures the unit and fitted-process profiles; it does not carry
the full real bundle. Functional success remains separate from deployment
eligibility, memory budgets and previously unseen model-quality evidence.
The completed gate records **741 unit, 7 fitted-process and 1 real-bundle test
passed**, plus one allowed Windows symlink skip. Exact loader and off/miss/hit
HTTP parity pass. Fresh ready RSS is 2.19/2.23 GiB and sampled peaks are
2.41/2.44 GiB for anonymous-off/bearer-on, so deployment eligibility remains false.
Measured scope and the numerical/output policy are recorded in the strategy and receipt.

## M21 isolated Linux container

The [container report](LINUX_CONTAINER.md) and
[receipt](../benchmarks/containers/linux_snapshot_boundary_validation_v1.json) verify the
original snapshot in a pinned Linux/amd64 image on Docker Desktop. All 101
pool/evidence/route/output references match exactly. Feature/score arrays pass
the separately approved `rtol=atol=1e-12` portability policy, while bitwise warm
digests differ; M20's original exact policy and receipt remain unchanged.
The report discloses that the portability policy followed an observed bitwise
failure, rather than describing that initial gate as passing.

The runtime is non-root, uses read-only root/model mounts and explicit resource
bounds, and has no network or published ports. Real HTTP reference/prefix and
denial/recovery checks pass; invalid model startup fails and SIGTERM cleanup
completes. The runner checks actual context-export canaries, supports a missing
private scratch parent, requires confirmed container absence after cleanup and
rejects invalid memory telemetry. The report records startup, 100-reference
warm sequential client timing and serving RSS; these are not representative-load
evidence. The 2 GiB memory budget remains unmet. Regression checks pass 832
tests with one Windows symlink skip; real Linux qualification is recorded
separately from those fixture/unit results. No deployment eligibility is claimed.

## M22 CI and controlled local release

The [release runbook](RELEASE_WORKFLOW.md) separates hosted fixture CI, a gated
private real-qualification workflow and the observed local control exercise.
The [M22 Linux CI receipt](../benchmarks/release/ci_linux_preflight_validation_v1.json)
records 946 unit and 7 fitted-process tests passed without skips. Windows passed
945 unit and 7 fitted-process tests, plus one allowed symlink skip. These totals
include 120 release-boundary/transaction cases; opt-in real-bundle execution is
not counted in either fixture profile.

The [release-control receipt](../benchmarks/release/release_workflow_preflight_validation_v1.json)
uses the original image/model for two immutable release IDs. A, B and fresh
rollback A each match all 101 HTTP references. B is killed while its postcommit
retirement journal is still pending. Recovery preserves old A with explicit
retained ownership; fresh rollback then verifies and retires both prior instances.
A failed rollback candidate leaves retained instances untouched. Final success
requires one graceful cleanup event and no remaining owned containers. A new
scratch descriptor with a valid JSON checksum but the wrong manifest identity
is rejected through activation; the pointer, journal, container inventory and
active health remain unchanged. Wrong-pin and observer rejection checks remain
separate. Every verifier call requires external recovery storage; the workflow
checks physical paths before checkout and refuses unfinished prior runs. CI
policy enforces the Python version, dependency imports and manifest pin. Its
scoped inventory records build/test inputs, excluding docs and generated receipts.

This is isolated local control verification, not public traffic routing, a
model-quality comparison or host power-loss recovery. The initial and boundary
M22 receipts remain historical with their original source/bytes. The new GitHub lane remains
unconfigured and unobserved; production eligibility remains false.

## M23 HTTP workload and capacity

The [capacity report](HTTP_CAPACITY_REPORT.md) and
[receipt](../benchmarks/performance/http_capacity_boundary_validation_v1.json) record the
unchanged 2 CPU/4 GiB Linux image: cache off at 1/4 requests/s and explicitly
primed cache at 4/8 requests/s, with 150-second windows. The workload repeatedly
uses 100 known warm references and one cold context; it is not production
traffic. Success, worker 503, quota 429 and client-shed denominators remain
separate. The 4-request/s controls have identical request sequences.

Both uncached cells met successful-warm p95/p99 targets. Every cell exceeded
2 GiB RSS, so no tested point passes all gates. Uncached 4 requests/s also
exceeded the rejection budget (16/600 worker-busy responses). No model, quota, cache-default
or inference optimization was adopted. Regression profiles passed 1,011 unit + 9
fitted tests on Windows (one allowed skip) and 1,012 unit + 9 fitted tests on Linux
(no skips). Hosted CI for the published M23 source `7449414`
[passed after publication](https://github.com/Thazg/ecommerce-recsys/actions/runs/39439452790);
the private real-qualification lane remains unconfigured and unobserved.

## M24 load, failure and recovery

The [reliability report](SERVICE_RELIABILITY_REPORT.md) and
[completed receipt](../benchmarks/reliability/service_resilience_boundary_validation_v1.json)
record all nine fixed steps. Eight load windows contain 1,080 offered arrivals;
909 paced references, six post-burst recovery calls, one accepted termination
response and a fresh three-candidate release exercise retain distinct scopes.
Startup wrong-pin/missing-model/corrupt-overlay cases exit nonzero without
readiness or OOM. Client disconnect recovers, and observed in-flight SIGTERM
finishes the accepted sealed response before one graceful cleanup.

Fixture cancellation/model/executor failures are separate from real-model
observations. Full gates pass 1,072 Windows unit + 11 fitted cases (one allowed
symlink skip) and 1,073 Linux unit + 11 fitted cases (no skips). Memory and load
budgets are reported as outcomes; the 2 GiB RSS target remains unmet. No model,
quota, image, cache-default or public-exposure change was adopted.

## M25 deployment design and cost

The [design](DEPLOYMENT_DESIGN.md), [hosting catalog](../benchmarks/deployment/hosting_options_v1.json)
and [assessment](../benchmarks/deployment/deployment_assessment_v1.json) retain
local-only execution and identify OCI Arm as a conditional free investigation.
The known subtotals distinguish free allowances from paid memberships and hosts;
account entitlement, actual capacity and all-in costs remain unverified.
The planning floors are 6 GiB for one 4-GiB container plus host reserve and
10 GiB for two such reservations. These do not revise the 2-GiB process target.

Artifact/secrets delivery, TLS/gateway isolation, maintenance release/rollback
and the target-host gate checklist are documented designs. They are not installed
cloud components. The existing amd64 image, service, model and earlier evidence
remain unchanged. The assessor needs no cloud credentials, Docker or model fit.

## Next milestone

M26 in the [roadmap](ROADMAP.md) defines controlled deployment. It requires an
approved/available target, architecture and process-memory qualification,
implemented exposure/delivery controls and explicit operator authorization.
The current free-first decision does not approve provisioning or waive budgets.
M27 retains external workload, telemetry and native target-host recovery checks.
Independent confirmation of the current model choices requires a later
untouched time period; the existing post-selection results should not be used
as production model-selection claims.

The [baseline](BASELINE_REPORT.md) and [MF](MF_EXPERIMENT_REPORT.md) reports document earlier per-user leave-last-out experiments. Their metrics are retained for provenance but are not directly comparable with rolling results.
