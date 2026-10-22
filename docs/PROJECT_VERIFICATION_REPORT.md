# Project documentation verification

## Scope

This report separates current-checkout documentation integrity from executed
test profiles, preserved historical model evidence and observed static hosting.
The recommendation model, dataset, inference behavior and published benchmark
bytes are unchanged. Full-model cloud deployment remains unqualified.

## Verification profiles

The documentation checker uses Python's standard library and performs no
network requests, model load or fit, code-block execution or quality calculation.
Its completed receipt belongs in the [release evidence directory](../benchmarks/release/).
The machine-readable [inventory](../benchmarks/release/documentation_inventory_v1.json)
declares documentation, current source and independent historical evidence pins.

The [reproduction guide](REPRODUCIBILITY.md) distinguishes this profile from
unit tests, genuinely fitted synthetic HTTP integration and explicit private
Retailrocket bundle verification. No fresh full-model quality is inferred.

## Executed checks

Verification on 2026-10-22 used the existing Windows `ecommerce-recsys`
environment, Python 3.13.15 and implicit 0.7.3. Numerical test workers were
restricted to one BLAS/OpenMP thread. No dependency upgrade or model refit was
performed. A fresh environment installation was not exercised.

| Check | Command or profile | Observed result |
| :--- | :--- | :--- |
| Dependency integrity | `python -m pip check` | No broken requirements |
| Optional imports | `implicit`, `fastapi`, `uvicorn`, `httpx2`, `yaml`, `torch`, `faiss`, `psutil` | Imports available |
| Lint and formatting | `python -m ruff check .`; `python -m ruff format --check .` | Pass |
| Full unit profile | `python -m pytest tests/unit -q` | 1,208 passed; 3 Windows symlink-privilege skips |
| Fitted integration | `python -m pytest tests/integration -m "not real_bundle" -q` | 11 passed; 1 real-bundle case deselected |
| JavaScript | `node --test --test-isolation=none tests/web/test_snapshot_demo.mjs` | 15 passed; no skips |
| Isolated standard library | `python -I -S scripts/verify_project_documentation.py` | Pass without site packages, package/model imports or network |
| Documentation inventory | Current documentation gate | 43 documents; 65 frozen JSON files; 544 local links; 15 heading/source fragments |
| External references | Documentation gate | 34 links counted, not fetched |
| Static preview | Owned `http.server` on loopback port 8767, serving `demo/` | Seven files byte-matched; private path returned 404; child stopped and listener closed |
| CLI contract smoke | Serving launcher, bundle builder and verifier `--help` | Supported arguments confirmed; no fit or model load |

Full unit execution used an absolute temporary directory outside the checkout,
as required by release-controller tests. The three skips were the existing
bundle/demo directory-symlink tests and the new file-symlink boundary test.
No unexpected skip was accepted. The new documentation module has 50 unit cases
within that full profile: 49 pass and one explicit Windows privilege skip.

Checks include source/evidence drift, malformed/duplicate/nonfinite JSON,
incomplete inventories, escaping or ambiguous paths, symlinks, missing headings,
source-line bounds, duplicate/Unicode headings, fenced/inline-code exclusions,
stale/forged receipts and non-overwriting publication. The link check covers
the repository's inline/reference Markdown links and heading fragments; it is
not a browser or a general Markdown conformance engine.

The full suite was rerun after fixing a Windows CRLF fixture and completing
receipt/Markdown boundary hardening. Model, service and historical experiment
source were preserved. Synthetic integration trains only the small fixture
models; the explicit Retailrocket reference profile was not run in this pass.

## Interpretation

The existing [hosted static record](../benchmarks/demo/static_hosting_validation_v2.json)
binds the deployed RecoLens source and 27 UI combinations, assets/HTTP exposure
checks and a 375px viewport. It is historical hosted evidence, not a new live
probe performed by the documentation checker. The original
[presentation record](../benchmarks/demo/showcase_presentation_validation_v1.json)
retains its original broad documentation fingerprint. Intentional documentation
updates are bound by the new documentation gate; static asset pins remain exact.

No clean-room install, Docker lifecycle, public inference API, external workload,
native-host recovery, blind model confirmation or production SLO is established.
The original RSS failure and inspected-fold disclosure remain explicit. See the
[evidence index](EVIDENCE_INDEX.md) and [operations runbook](OPERATIONS_RUNBOOK.md).

## Repeat the integrity check

```sh
python scripts/verify_project_documentation.py --check benchmarks/release/project_documentation_validation_v1.json
```

This command recomputes documentation/source identity and evidence byte pins.
It does not rerun the execution table above. New intentional documentation or
source changes require a freshly verified, distinctly named receipt; original
measurements and model/deployment limitations remain unchanged.
