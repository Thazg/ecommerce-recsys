# Contributing

Small, focused pull requests are welcome. Describe the problem, the resulting
behavior and the checks you ran. Include a minimal synthetic reproduction for
bugs and explain any change to evaluation or runtime assumptions.

## Setup and validation

Follow the [reproduction guide](docs/REPRODUCIBILITY.md) for Python 3.13.15,
the platform-specific hashed dependencies and the Windows Conda lifecycle
baseline. The JavaScript checks use Node 24.16.0 in CI.

From the repository root:

```sh
python -m ruff check .
python -m ruff format --check .
python -m pytest tests/unit -q
python -m pytest tests/integration -m "not real_bundle" -q
node --test --test-isolation=none tests/web/test_snapshot_demo.mjs tests/web/test_shopping_demo.mjs
python -I -S scripts/verify_project_documentation.py
```

Fixture tests fit small synthetic models. Real Retailrocket verification is a
separate explicit profile with external inputs; missing real data must not be
replaced silently with fixtures. Run relevant checks while iterating and record
the completed profiles in the pull request.

## Benchmark and dependency changes

- Keep published benchmark JSON and model bundles immutable. Changed inputs,
  implementations or policies need separately verified artifacts.
- Select configurations on development folds only. Inspected folds 5–9 remain
  post-selection diagnostics, not blind validation.
- Preserve cutoff-time catalogs, full seen-item filtering and separate warm/cold
  denominators. Compare results only at matching cohorts and output budgets.
- Update dependency locks and their policy checks together. Numerical dependency
  changes require bundle compatibility verification; do not upgrade the original
  producer environment or rewrite historical hashes to make a check pass.

The documentation gate binds source, Markdown/HTML links and local image bytes.
An intentional change needs a fresh, non-overwriting receipt and updated current
references. Historical receipts retain their original source identities.

## Data and security

Keep raw/prepared data, generated bundles, credentials and local working notes
outside commits. Use synthetic examples in issues and remove private identifiers
from logs. Report vulnerabilities through the [security policy](SECURITY.md),
rather than publishing exploit details or sensitive attachments in an issue.
