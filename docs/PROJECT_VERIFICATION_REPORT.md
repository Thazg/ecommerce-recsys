# Project verification report

## Current verification scope

The 2026-10-25 publication preflight checks the proposed public source in an
independent checkout with a fresh Windows Conda Python 3.13.15 environment.
Dependencies are installed from the hashed
[Windows development lock](../requirements/development-windows.txt), including
optional CPU model and HTTP test dependencies. The editable package is loaded
from that checkout, without raw data, fitted bundles or private scratch files.
The existing producer environment is preserved.

The source-bound [preflight record](../benchmarks/release/publication_preflight_validation_v1.json)
pins the tested code/configuration, installed wheel versions, profile counts and
scan scopes. Private logs, JUnit files and synthetic scanner canaries stay
outside the public tree.

Documentation integrity, code tests, historical quality and real-bundle runtime
qualification are separate profiles. The selected model policy and frozen
experiment JSON remain unchanged. The [evidence index](EVIDENCE_INDEX.md) maps
each result to its original scope and producer identity.

## Executed publication checks

| Profile | Command or scope | Result |
| :--- | :--- | :--- |
| Fresh dependencies | Hashed Windows wheels, editable install, `python -m pip check` | 48 pinned wheels; no broken requirements |
| Optional imports | `implicit`, `torch`, `faiss`, `fastapi`, `uvicorn`, `httpx2`, `yaml`, `psutil` | Available; no optional-model skip |
| Lint and format | `python -m ruff check .`; `python -m ruff format --check .` | Pass |
| Unit tests | `python -m pytest tests/unit -q -o xfail_strict=true` | 1,400 passed; 3 explicit Windows symlink-privilege skips |
| Fitted integration | `python -m pytest tests/integration -m "not real_bundle" -q -o xfail_strict=true` | 14 passed; 1 opt-in real-bundle case deselected |
| Static demos | `node --test --test-isolation=none tests/web/test_snapshot_demo.mjs tests/web/test_shopping_demo.mjs` | 25 passed; no skips |
| Workflow policy | `python scripts/check_release_workflows.py`; `python scripts/check_public_workflow.py` | Pass |
| Workflow syntax | Checksum-verified actionlint 1.7.12 against all three workflows | Pass |
| Documentation | `python -I -S scripts/verify_project_documentation.py` | Standard-library integrity check passes |
| Secrets | Gitleaks 8.30.1: reachable history, proposed public files and retained Actions logs/artifacts | No unresolved findings in the scanned scope |

Python tests disable user-site imports and plugin autoload, and use one
BLAS/OpenMP thread. Their
absolute temporary directories are outside the checkout, as required by the
release-controller boundary. The three permitted skips concern directory/file
symlink creation on this Windows account; none replaces model or integration
coverage. Synthetic integration actually fits, exports, reloads and serves
small fixture models. It does not load the private Retailrocket bundle.

A Windows `venv` installation was also tried. Its proxy launcher did not satisfy
the process-ownership kill test. Windows lifecycle verification therefore uses
a real Conda interpreter; the venv profile is not qualified. The lock is for
current-source development tests, not a replacement producer environment or a
claim of numerical compatibility with every fitted bundle.

## Publication boundaries

The [publication workflow](../.github/workflows/publication.yml) runs both demo
suites, the source-bound documentation receipt and pinned secret scans. The
existing hosted Python workflow enforces its policy and lints all three
workflows. These new definitions have been checked locally; GitHub execution
for this proposed source has not yet been observed. The private remote
real-qualification lane remains unconfigured.

The history scan covers all reachable refs. Scanner defaults remain enabled;
a narrowly scoped exception permits only seven reviewed provenance-map keys
with SHA-256 values in release/serving JSON and four named local-deployment
receipts. Six scanner canaries confirm that
ordinary API keys, provider-shaped tokens and out-of-scope values remain
reported. The read-only Actions review covers 54 completed run-log archives,
eight retained artifacts and 123 extracted text files. No runs or artifacts
were removed. Scanning reduces exposure risk; it does not prove that every
possible secret is absent.

Public source excludes raw/processed datasets, generated bundles, private
numerical archives, credentials, agent instructions, plans and audit helpers.
Security reporting and the local exposure contract are documented in the
[security policy](../SECURITY.md). Repository visibility and publication are
separate operator decisions.

## Model and runtime evidence

The [local release report](LOCAL_RELEASE_REPORT.md) and
[source-bound qualification](../benchmarks/deployment/local_release_maintenance_validation_v1.json)
record independent original-bundle verification of the indexed HTTP runtime
on Windows. All seven fixed local targets pass. Two fresh same-port processes
preserve all 101 sealed outputs; the 120-arrival steady sample completes with
warm HTTP p95/p99 of 209.440/233.063 ms and maximum loaded RSS of 1.499 GiB.
Burst/recovery, wrong-pin startup, startup EOF and owned stop/restart are
separate checks. This receipt is not produced by the documentation checker.

Earlier Linux measurements used the original reader and exceeded the 2 GiB
RSS target. The indexed reader has not received Linux load qualification.
The last observed hosted [Linux CI at `30e685b`](https://github.com/Thazg/ecommerce-recsys/actions/runs/39766736448)
passed 1,213 unit and 11 fitted integration cases before the current additions.
That run does not certify the proposed source or new reader on Linux.

The [RecoLens hosted record](../benchmarks/demo/static_hosting_validation_v2.json)
and [RecoMe hosted record](../benchmarks/demo/shopping_hosting_validation_v1.json)
preserve their original static releases. RecoLens displays stored actual-model
outputs; RecoMe uses a separate browser content-based policy and photographed
sample catalog. Neither website hosts model inference.

## Maintenance and historical reproduction

Input regressions reject invalid raw events before replacing Parquet output.
Processing all 2,756,101 events with the updated and original builders in the
same environment produced identical Parquet bytes. The pre-existing dataset
has a millisecond datetime unit rather than the builders' nanoseconds, with
identical instants and canonical rows; it was not replaced. Educational MF/BPR
now invalidate stale state before fit/refit. Successful deterministic fits
retain exact factor arrays and recommendation order in the comparison fixture.
These checks establish regression behavior, not new recommendation quality.

The completed model-policy provenance supplement was reverified from a separate
source-compatible checkout at `30e685babbdeec682084830f23834a6141a18f9a` with the
original data and artifacts. Its historical package-wide guard correctly
rejects later educational-source changes. Reproduce historical experiments at
their stated revisions rather than editing old SHA fields. Sixteen legacy JSON
inputs require the exact checkout rules in `.gitattributes`; see the
[reproduction guide](REPRODUCIBILITY.md).

Folds 5–9 remain **post-selection diagnostics, not blind validation**. Public
model hosting, request-time history updates, newly blind quality confirmation,
representative production traffic, power-loss recovery and a production SLO
are outside the verified release claims.

## Repeat documentation integrity

```sh
python -I -S scripts/verify_project_documentation.py --check benchmarks/release/project_documentation_readme_hero_validation_v1.json
```

The [inventory](../benchmarks/release/documentation_inventory_readme_hero_v1.json)
and completed receipt pin current documentation/source, released assets and
independent historical evidence. The checker uses no network, executes no
Markdown commands and fits or loads no model. It counts external links without
fetching them and is not a general Markdown renderer. It does not rerun the
checks in the table. Intentional source or documentation changes require a new,
non-overwriting receipt; historical evidence retains its original bytes.
