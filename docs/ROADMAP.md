# Project roadmap

The project progresses from causal offline evaluation to retrieval, ranking and
serving. Milestones define deliverables, dependencies and evidence required for
acceptance. Implementation progress belongs in [project status](PROJECT_STATUS.md);
the [current architecture](ARCHITECTURE_CURRENT.md) describes existing components.

## Release scope

The initial release serves personalized recommendations for known snapshot
users and an explicit cold-user route through an API and public demo. Every
response identifies its model version and historical cutoff. The demo explains
stored user context and the dataset's anonymized product identifiers; it does
not imply live inventory, current product metadata or continuously updated users.

Similar-item recommendations and request-time session/history updates are
conditional extensions. Each needs its own input, eligibility, evaluation and
serving contract before becoming part of the release. ANN, neural retrieval,
sequential models, diversity rules and distributed caches are adopted only when
their measured benefit justifies their cost. A reproducible no-go decision is
a valid completion outcome for an experiment.

## Data, evaluation and model development

| Milestone | Deliverable | Acceptance evidence |
| :--- | :--- | :--- |
| M0–M2 | Repository foundation, dataset contract and interaction semantics | Reproducible preparation, input hashes, quality checks and documented filtering/event assumptions |
| M3 | Temporal evaluation | Shared rolling cohorts, global cutoff and catalog guards, warm/cold separation and provenance checks |
| M4–M6 | Baselines, ItemKNN and implicit matrix factorization | Same-protocol accuracy, availability and cost comparisons; development-only configuration selection |
| M7 | Candidate generation | Common source interface, explicit attribution, Recall@100/500/1000, pool availability and matched cost measurements |
| M8 | Two-tower retrieval experiment | Shared train/inference encoding, causal negative sampling and comparison with exact ALS on identical temporal targets/catalogs |
| M9 | Conditional ANN feasibility | Paired exact/ANN quality and speed gates on the same fitted vectors, context and budget; documented adopt/no-go decision |
| M10 | Ranking dataset and features | Causal request/candidate examples, label-feature separation, retained zero-positive requests and independent file/feature verification |
| M11 | Learned ranking | Chronological selection, locked configuration and same-pool Top-5/10/20 comparison with retrieval order |
| M12 | Optional sequential experiment | Matched order/recency ablation, causal timestamp handling and an evidence-based adopt/no-go decision |
| M13 | Category-aware re-ranking | Same-pool relevance, coverage and category trade-offs; explicit selection constraints and short-list limits |
| M14 | Complete model-policy benchmark | Frozen warm/cold routes selected on development data, complete-policy accuracy/cost evidence and disclosed selection limitations |

Published experiment artifacts remain immutable. Follow-up uncertainty estimates
and activity/head–tail slices must declare their method and use cutoff-time
definitions. Comparisons should preserve paired requests and account for repeated
users where applicable. Descriptive slices cannot change a locked policy using
inspected diagnostic folds. New model or cost-constrained selection requires a
prospective experiment with its objective fixed before scores are inspected.

## Artifacts and service engineering

M15 depends on the frozen policy and its data/source provenance. M16 depends on
a verified bundle. M17 extends that service contract. Basic validation, tests,
health checks and measurements accompany every implementation; their dedicated
milestones deepen coverage rather than postpone those controls.

| Milestone | Deliverable | Acceptance evidence |
| :--- | :--- | :--- |
| M15 | Immutable model bundles and package inference | Safe formats, complete inventory/pins, train-independent loading, reference parity, loaded-quality reconciliation and version-overwrite rejection |
| M16 | Local recommendation HTTP API | Strict request/output contract, pinned startup, live/ready probes, bounded admission, cancellation/shutdown behavior and real HTTP reference parity |
| M17 | Bounded cache and explicit degraded behavior | Version/context-safe cache identity, eviction/invalidation, measured benefit and memory cost; declared fallback triggers, eligibility, response attribution and failure tests |
| M18 | Observability | Structured logs and bounded-cardinality metrics for request outcomes, route/version, latency, admission rejection, cache, degraded responses and memory; no raw user IDs as metric labels |
| M19 | Input and exposure hardening | Tested body/rate limits, slow-client/resource protections, safe errors, log redaction, trusted configuration and access controls appropriate to the exposure |
| M20 | Integration and release test strategy | Automated request/lifecycle/failure coverage, a real-bundle integration gate, numerical/output parity policy and explicit separation of fixture tests from model evidence |
| M21 | Reproducible Linux container | Pinned runtime, safe artifact delivery, non-root execution, resource/health configuration and actual bundle load/reference parity on the target Linux environment |
| M22 | CI and controlled release workflow | Unit/lint/dependency gates, gated real-bundle/container verification, immutable image/model identities and an exercised release/rollback procedure |

### Cache and fallback contract

- Cache identity includes bundle/policy version, user context and output-budget
  semantics. Prefix reuse must preserve exact Top-K behavior and full seen-item
  filtering. Model replacement cannot reuse entries from another version.
- Set memory/entry bounds and explicit expiry/invalidation rules. Measure hit,
  miss and eviction behavior. External cache infrastructure requires workload
  evidence; a bounded local implementation or a documented no-go can suffice.
- Distinguish normal cold routing from overload, model failure and missing or
  corrupt artifacts. Define which states permit degraded results and which
  require rejection. A fallback must satisfy its declared catalog/seen policy
  and expose its route, reason and version/lineage.
- Tests must cover dependency failure, stale entries, exhausted eligibility,
  concurrent misses, readiness and shutdown. Extending error recovery requires
  an explicit service contract; it must not silently convert existing errors
  into successful personalized recommendations.

## Performance, reliability and release gates

| Milestone | Deliverable | Acceptance evidence |
| :--- | :--- | :--- |
| M23 | Workload-based performance and capacity assessment | Reproducible HTTP workload with predefined traffic mix/concurrency, latency/error/admission metrics, resource measurements and quality parity after optimization |
| M24 | Load, failure and recovery validation | Sustained/burst and resource-pressure tests, dependency/model failures, cancellation/drain behavior and recovery/rollback checks against predefined thresholds |
| M25 | Deployment design and cost decision | Hosting/resource choice justified by M21–M24 evidence, monthly cost estimate, artifact/secrets delivery, exposure controls and rollback/runbook design |
| M26 | Controlled deployment | Version-pinned image and model, health/readiness, resource limits, access controls, monitoring and verified rollback on the selected host |
| M27 | Post-deployment verification | Target-host output parity, external HTTP probes, representative smoke/load checks, telemetry and recovery verification with recorded release identities |
| M28 | Public demo | Explainable known-user/cold flows, visible snapshot/model semantics, clear busy/degraded/error behavior, bounded usage and no real user data collection requirement |
| M29 | Release documentation and reproducibility | Verified setup/run commands, architecture, evidence index, operational runbook, trade-offs, cost and limitations with working links |

### Continuous resource checks

Measure startup, loaded-process RSS and representative HTTP latency from M16
onward. Repeat the relevant checks when cache, concurrency, model restoration
or inference behavior changes. M23–M24 provide the full workload and failure
evidence; they are not the first opportunity to detect resource regressions.

The initial [charter budgets](PROJECT_CHARTER.md#9-initial-performance-targets)
are warm HTTP **p95 ≤ 300 ms**, **p99 ≤ 500 ms**, and loaded serving-process
**RSS ≤ 2 GiB**. Record startup and peak memory separately. These are targets,
not assertions that a milestone or deployment satisfies them. Cold-start time
is measured but is not an initial release gate.

Before acceptance testing, freeze the hardware/container resources, offered
request rate, concurrency, duration, warm/cold mix, K distribution, cache state,
warm-up and allowed error/admission-rejection rates. Report offered and completed
throughput, all outcomes and cache hit/miss scopes separately. Fast rejections
or cached calls must not conceal slow inference or an unacceptable rejection
rate. A small sequential smoke sample cannot establish a service objective.

Public deployment requires these resource and reliability gates to pass on the
target environment. An unmet budget needs optimization or an evidence-backed
budget/scope revision recorded in [decisions](DECISIONS.md) before release
acceptance. A larger host does not by itself revise the declared memory budget.
CI with mocked model fixtures does not establish Linux real-bundle parity.

## Evaluation and evidence rules

- Define each milestone's work and acceptance thresholds before implementation
  or new experiment scoring. Record commands, configuration, environment,
  input/model/code identities, results and unresolved limits in reviewable
  evidence. Long-running evaluations need matching checkpoints and atomic writes.
- Select model configurations on development periods only. Keep warm/cold
  denominators separate, retain protocol-required unreachable targets and report
  per-fold results alongside pooled metrics. State uncertainty and cost when
  interpreting small accuracy differences.
- Previously inspected later folds remain post-selection diagnostics. New blind
  confirmation requires an untouched later period; if unavailable, retain the
  limitation. Release parity, a public demo and deployment telemetry do not
  constitute independent recommendation-quality or business-impact evidence.
- Measure stages at their declared scope: source retrieval, complete inference
  and full HTTP requests have different timing boundaries. Distinguish serialized
  size, factor-array bytes, steady process RSS and startup/peak memory.
- Use new versioned evidence for behavior changes; preserve existing artifacts
  and their provenance. Operational optimizations require output/eligibility
  parity, or an explicit prospective quality/cost experiment if behavior changes.
