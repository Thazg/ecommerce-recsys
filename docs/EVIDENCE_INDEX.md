# Evidence index

Use this index to locate the evidence supporting a claim before comparing
models or interpreting a passing operational check. The machine-readable
[inventory](../benchmarks/release/documentation_inventory_public_readiness_v1.json) pins existing
JSON files without changing their bytes. Its integrity check does not recompute
their metrics or certify that their producer environment matches today's tree.

## Quality and model decisions

| Question | Primary evidence | Interpretation |
| :--- | :--- | :--- |
| Which data and temporal boundaries apply? | [Rolling manifest](../benchmarks/rolling/manifest.json); [protocol](ROLLING_EVALUATION_PROTOCOL.md) | Train/catalog/category as-of cutoff; warm/cold remain separate |
| How do baseline rankers compare? | [Rolling results](../benchmarks/rolling/results.json), [cold](../benchmarks/rolling/cold.json); [report](ROLLING_BENCHMARK_REPORT.md) | Fractions and pooled user-windows; fold range and cohort matter |
| What was selected on development folds? | [ItemKNN sweep](../benchmarks/rolling/item_knn_sweep.json), [ALS sweep](../benchmarks/rolling/als_sweep.json) | Folds 1–4 select; the small ALS margin does not justify an unqualified cost claim |
| Does the target enter the candidate pool? | [Candidate results](../benchmarks/retrieval/candidates.json); [report](CANDIDATE_RETRIEVAL_REPORT.md) | Recall@N is pool availability, not final Top-K accuracy |
| Did neural retrieval help at the chosen budget? | [Two-Tower lock](../benchmarks/retrieval/m8_selection_lock_v1.json), [diagnostic](../benchmarks/retrieval/two_tower_diagnostic_v1.json); [report](TWO_TOWER_REPORT.md) | Budget-dependent trade-off; not the strongest hybrid or a production choice |
| Was ANN adopted? | [Exact profile](../benchmarks/retrieval/m9_profile_v1.json), [pilot](../benchmarks/retrieval/m9_ann_pilot_v1.json); [report](ANN_RETRIEVAL_REPORT.md) | No-go for four fold-1 HNSW settings; no full later-fold ANN quality claim |
| Are ranking labels/features separated? | [Dataset quality](../benchmarks/ranking/m10_quality_v1.json), [independent audit](../benchmarks/ranking/m10_feature_audit_v1.json); [report](RANKING_DATASET_REPORT.md) | Development rows; requests with zero positives stay in the denominator |
| Does learned ordering help on the same pool? | [Ranker lock](../benchmarks/ranking/ranker_selection_lock_v1.json), [diagnostic](../benchmarks/ranking/ranker_diagnostic_v1.json); [report](LEARNED_RANKING_REPORT.md) | Reorders candidates; does not increase retrieval recall |
| Was sequential order adopted? | [Sequential lock](../benchmarks/retrieval/sequential_selection_lock_v1.json), [diagnostic](../benchmarks/retrieval/sequential_diagnostic_v1.json); [report](SEQUENTIAL_RECOMMENDATION_REPORT.md) | No-go for the tested order-benefit policy |
| What does category re-ranking trade? | [Diversity diagnostic](../benchmarks/ranking/diversity_diagnostic_v1.json); [report](DIVERSITY_RERANKING_REPORT.md) | Distinct-category rank bonus; not pairwise ILD or a default route |
| Which complete policy is frozen? | [Policy lock](../benchmarks/model_policy/selection_lock_v1.json), [diagnostic](../benchmarks/model_policy/diagnostic_v1.json), [provenance supplement](../benchmarks/model_policy/provenance_v1.json); [report](MODEL_POLICY_REPORT.md) | Warm hybrid+learned, cold recent popularity; diagnostic outcomes do not revise the lock |

All inspected folds 5–9 are **post-selection diagnostics, not blind validation**.
Pooled warm and cold denominators are not interchangeable. Historical
[leave-last-out evidence](../benchmarks/baseline/baseline_v1.json) and the
[baseline report](BASELINE_REPORT.md) answer a different task; their figures
must not be presented as a before/after comparison with rolling.

## Inference and operational evidence

| Layer | Primary evidence | Boundary |
| :--- | :--- | :--- |
| Bundle | [Full fold-9 reconciliation](../benchmarks/artifacts/fold09_v1.json), [reader references](../benchmarks/artifacts/fold09_loader_v1.json); [contract](MODEL_ARTIFACTS.md) | Historical quality versus finite reader verification; model files are outside Git |
| Indexed reader | [Memory assessment](../benchmarks/deployment/snapshot_memory_validation_v1.json); [report](SNAPSHOT_MEMORY_REPORT.md) | Same-host Windows package RSS and 101 exact traces; no new Linux/HTTP memory qualification |
| Local illustration delivery | [Local HTTP record](../benchmarks/deployment/local_demonstration_validation_v1.json); [guide](LOCAL_DEMONSTRATION.md) | Indexed-reader loopback output/prefix/denial checks and owned cleanup; public site remains static |
| Current HTTP boundary | [Hardening receipt](../benchmarks/serving/hardening_boundary_validation_v1.json); [API](RECOMMENDATION_API.md), [security](API_HARDENING.md) | Local parity/denials; no public API, per-user authorization or SLA |
| Cache and telemetry | [Cache state](../benchmarks/serving/cache_state_validation_v1.json), [observability lifecycle](../benchmarks/serving/observability_lifecycle_validation_v1.json) | Finite constructed repeats and scoped counters; earlier boundary identities remain historical |
| Functional integration | [Integration receipt](../benchmarks/release/integration_boundary_validation_v1.json); [strategy](TESTING_AND_RELEASE_GATES.md) | Specific source revision; fixture, real-model and historical-quality evidence are separate |
| Linux portability | [Linux boundary receipt](../benchmarks/containers/linux_snapshot_boundary_validation_v1.json); [report](LINUX_CONTAINER.md) | Exact output/pool/evidence, `1e-12` feature/score tolerance; bitwise parity was not achieved |
| Release control | [Linux preflight](../benchmarks/release/ci_linux_preflight_validation_v1.json), [release preflight](../benchmarks/release/release_workflow_preflight_validation_v1.json); [runbook](RELEASE_WORKFLOW.md) | Isolated same-model activation/recovery/rollback; private remote qualification is unconfigured |
| Capacity | [Capacity boundary](../benchmarks/performance/http_capacity_boundary_validation_v1.json); [report](HTTP_CAPACITY_REPORT.md) | Constructed offered load, separate warm/cache/rejection timing; RSS budget fails |
| Reliability | [Resilience boundary](../benchmarks/reliability/service_resilience_boundary_validation_v1.json); [report](SERVICE_RELIABILITY_REPORT.md) | Fixed local fault matrix; not native-host/power-loss or production availability evidence |
| Full-model hosting design | [Assessment](../benchmarks/deployment/deployment_assessment_v1.json), [dated catalog](../benchmarks/deployment/hosting_options_v1.json); [design](DEPLOYMENT_DESIGN.md) | Offline free-first design; no approved inference host or memory-budget waiver |
| RecoLens static release | [Presentation](../benchmarks/demo/showcase_presentation_validation_v1.json), [hosted release](../benchmarks/demo/static_hosting_validation_v2.json); [runbook](STATIC_DEMO_DEPLOYMENT.md) | Seven frontend/data assets, 27 UI combinations and public HTTP checks; no live inference |
| Indexed local release | [Local qualification](../benchmarks/deployment/local_release_maintenance_validation_v1.json); [report](LOCAL_RELEASE_REPORT.md) | Two 101-output passes, fixed Windows workload/resources, telemetry and owned same-port stop/restart; no public API or production SLO |

## Current checks versus historical records

The documentation gate's current receipt is
`benchmarks/release/project_documentation_public_readiness_validation_v1.json`, in the
[release evidence directory](../benchmarks/release/). It binds current documents,
source, unchanged static assets and independent historical evidence pins.
The checker makes no network requests, executes no Markdown commands and loads
or fits no model. The [verification report](PROJECT_VERIFICATION_REPORT.md)
records separately executed checks and their limitations.

Historical receipts retain their exact original bytes and source identities.
A valid historical checksum does not imply that its source matches the current
checkout. Use the declared producer revision for reproduction; do not replace
old SHA fields to accommodate later code. Sixteen legacy JSON inputs require
the explicit checkout rules in `.gitattributes`, as described in the
[reproduction guide](REPRODUCIBILITY.md).

The [publication workflow](../.github/workflows/publication.yml) defines hosted
checks for both static demos, current documentation integrity and secret
scanning of reachable history and checkout contents. Its policy retains default
secret detectors and permits only reviewed, line/path-scoped provenance hashes.
Local verification and GitHub execution remain separate evidence.

The [publication preflight](../benchmarks/release/publication_preflight_validation_v1.json)
records an independent Windows source export, a hashed 48-wheel Conda test
installation, 1,400 passing unit cases, 14 fitted integration cases and 25 Node
cases. Three named Windows symlink-privilege skips remain explicit. Its source
identity excludes evolving docs/generated receipts; the documentation receipt
binds those separately. Later hosted execution is recorded independently:
[fixture CI at `f149e9c`](https://github.com/Thazg/ecommerce-recsys/actions/runs/40246851260)
and its matching [publication run](https://github.com/Thazg/ecommerce-recsys/actions/runs/40246851248)
both passed. Their success does not revise the preflight's original fields or
establish Linux full-bundle load qualification.

The [security policy](../SECURITY.md) describes reporting and the supported
loopback boundary. RecoLens uses stored snapshot outputs; RecoMe uses a separate
browser policy. Neither static release establishes a public recommendation API,
new model accuracy, representative production traffic or a serving SLA.
