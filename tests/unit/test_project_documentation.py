"""Release documentation must reject stale evidence and unsafe file boundaries."""

import copy
import json
import os
import shutil
import subprocess

import pytest

from scripts import verify_project_documentation as release


def seal(path, value):
    value["content_sha256"] = release.digest(
        {key: item for key, item in value.items() if key != "content_sha256"}
    )
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    for name in [*release.ASSETS, release.PRESENTATION]:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(release.ROOT / name, target)
    documents = ["README.md", "docs/guide.md"]
    (root / "docs").mkdir()
    (root / "README.md").write_text(
        "# Release\n\n[Guide](docs/guide.md#setup)\n[Evidence](benchmarks/)\n",
        encoding="utf-8",
    )
    (root / "docs/guide.md").write_text("# Guide\n\n## Setup\n", encoding="utf-8")
    sources = sorted([release.SCRIPT, release.TEST])
    for name in sources:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Fixture source, never executed\n", encoding="utf-8")
    (root / "benchmarks/example.json").write_text('{"count":2}', encoding="utf-8")
    (root / "benchmarks/release").mkdir()
    (root / ".local").mkdir()
    evidence = sorted([release.PRESENTATION, "benchmarks/example.json"])
    policy = {
        "schema_version": 1,
        "scope": "static-demo-and-local-snapshot-api",
        "documents": documents,
        "current_sources": sources,
        "evidence": {name: release.sha(root, name) for name in evidence},
        "static_assets": {
            name: release.sha(root, name, normalize=True) for name in sorted(release.ASSETS)
        },
        "constraints": dict(release.CONSTRAINTS),
    }
    seal(root / release.INVENTORY, policy)
    return root, policy


def test_standard_library_check_needs_no_model_git_or_raw_data(checkout):
    root, _ = checkout
    result = release.inspect_project(root)
    assert result["documentation_integrity_passed"] is True
    assert result["model_loaded_or_fitted"] is False
    assert result["network_accessed"] is False
    assert result["links"] == {
        "local_links": 2,
        "fragments": 1,
        "external_links_not_fetched": 0,
    }
    assert not (root / "artifacts").exists()
    assert not (root / ".git").exists()


@pytest.mark.parametrize("bad", ["\u00e2\u20ac\u201d", "\u00c3\u00a2", "\ufffd"])
def test_legal_utf8_with_corrupted_presentation_is_rejected(checkout, bad):
    root, _ = checkout
    path = root / "docs/guide.md"
    path.write_text("# Guide\n\n## Setup\n\n" + bad, encoding="utf-8")
    with pytest.raises(ValueError, match="Corrupted UTF-8"):
        release.inspect_project(root)


def test_valid_unicode_punctuation_keeps_readable_heading_links(checkout):
    root, _ = checkout
    (root / "docs/guide.md").write_text(
        "# Guide\n\n## Setup\n\nBudget \u2264 2 GiB; folds 1\u20134.\n", encoding="utf-8"
    )
    assert release.inspect_project(root)["documentation_integrity_passed"]


@pytest.mark.parametrize("field", ["schema_version", "scope", "constraints", "foreign"])
def test_inventory_scope_and_plain_types_are_not_coerced(checkout, field):
    root, policy = checkout
    policy[field] = True
    seal(root / release.INVENTORY, policy)
    with pytest.raises(ValueError):
        release.inspect_project(root)


@pytest.mark.parametrize(
    "name",
    ["../outside", "/outside", "C:/outside", "docs\\guide.md", "a//b", "a/./b", "a/", "a\x00b"],
)
def test_inventory_rejects_ambiguous_paths(checkout, name):
    root, policy = checkout
    policy["documents"] = [name]
    seal(root / release.INVENTORY, policy)
    with pytest.raises(ValueError, match="canonical"):
        release.inspect_project(root)


@pytest.mark.parametrize(
    "fault", ["duplicate", "empty", "missing_source", "missing_asset", "bad_pin"]
)
def test_incomplete_inventory_is_rejected(checkout, fault):
    root, policy = checkout
    if fault == "duplicate":
        policy["documents"].append("docs/guide.md")
    elif fault == "empty":
        policy["documents"] = []
    elif fault == "missing_source":
        policy["current_sources"].remove(release.SCRIPT)
    elif fault == "missing_asset":
        policy["static_assets"].pop("demo/index.html")
    else:
        policy["evidence"][release.PRESENTATION] = "invalid"
    seal(root / release.INVENTORY, policy)
    with pytest.raises(ValueError):
        release.inspect_project(root)


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"value":NaN}', '{"value":1e999}', "[]", "{"])
def test_malformed_and_nonfinite_json_is_rejected(checkout, raw):
    root, _ = checkout
    (root / release.INVENTORY).write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        release.inspect_project(root)


def test_evidence_tamper_and_asset_drift_are_independent(checkout):
    root, _ = checkout
    (root / "benchmarks/example.json").write_text('{"count":3}', encoding="utf-8")
    with pytest.raises(ValueError, match="evidence fingerprint"):
        release.inspect_project(root)
    (root / "benchmarks/example.json").write_text('{"count":2}', encoding="utf-8")
    with (root / "demo/styles.css").open("a", encoding="utf-8") as stream:
        stream.write("\nbody {display:none}")
    with pytest.raises(ValueError, match="presentation changed"):
        release.inspect_project(root)


def test_repinning_assets_cannot_bypass_the_released_presentation(checkout):
    root, policy = checkout
    (root / "demo/styles.css").write_text("different", encoding="utf-8")
    policy["static_assets"]["demo/styles.css"] = release.sha(
        root, "demo/styles.css", normalize=True
    )
    seal(root / release.INVENTORY, policy)
    with pytest.raises(ValueError, match="released presentation"):
        release.inspect_project(root)


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_private_demo_inventory_cannot_expand(checkout, kind):
    root, _ = checkout
    path = root / "demo/private"
    path.mkdir() if kind == "directory" else path.write_text("private", encoding="utf-8")
    with pytest.raises(ValueError, match="static demo inventory"):
        release.inspect_project(root)


@pytest.mark.parametrize(
    "target",
    [
        "missing.md",
        "docs/guide.md#missing",
        "../outside.md",
        "javascript:alert",
        "file:///private",
        "//foreign/path",
        "docs/guide.md?override=true",
    ],
)
def test_broken_or_unsafe_links_fail(checkout, target):
    root, _ = checkout
    (root / "README.md").write_text(f"[Link]({target})\n", encoding="utf-8")
    with pytest.raises(ValueError):
        release.inspect_project(root)


def test_links_in_fences_are_not_executed_or_checked(checkout):
    root, _ = checkout
    (root / "README.md").write_text(
        "````sh\n[Not a link](missing)\n```\n````\n[Guide][g]\n[g]: docs/guide.md#setup\n",
        encoding="utf-8",
    )
    assert release.inspect_project(root)["links"]["local_links"] == 1
    (root / "README.md").write_text("```sh\nnever closed", encoding="utf-8")
    with pytest.raises(ValueError, match="Unclosed"):
        release.inspect_project(root)


def test_inline_code_comments_and_escaped_brackets_are_not_links(checkout):
    root, _ = checkout
    (root / "README.md").write_text(
        "`[Example](missing.md)`\n"
        "``[Example with ` tick](missing.md)``\n"
        "<!-- [Private note](missing.md) -->\n"
        "\\[Literal](missing.md)\n"
        "[Guide](docs/guide.md#setup)\n",
        encoding="utf-8",
    )
    assert release.inspect_project(root)["links"]["local_links"] == 1


def test_centered_html_links_and_images_are_checked_and_byte_pinned(checkout):
    root, policy = checkout
    asset = root / "docs/assets/preview.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"\x89PNG\r\n\x1a\nfixture\r\n")
    policy["documentation_assets"] = {
        "docs/assets/preview.png": release.sha(root, "docs/assets/preview.png")
    }
    seal(root / release.INVENTORY, policy)
    (root / "README.md").write_text(
        '<h1 align="center">Project</h1>\n'
        '<p align="center"><a href="docs/guide.md#setup">Guide</a> | '
        '<a href="https://example.org/?a=1&amp;b=2">Demo</a></p>\n'
        '<img src="docs/assets/preview.png" alt="Actual application preview">\n',
        encoding="utf-8",
    )
    result = release.inspect_project(root)
    assert result["links"] == {"local_links": 2, "fragments": 1, "external_links_not_fetched": 1}
    assert result["documentation_assets_sha256"] == policy["documentation_assets"]
    # Image pins use raw bytes; changing only CRLF bytes must still fail.
    asset.write_bytes(asset.read_bytes().replace(b"\r\n", b"\n"))
    with pytest.raises(ValueError, match="Documentation asset fingerprint"):
        release.inspect_project(root)


@pytest.mark.parametrize(
    "markup",
    [
        '<img src="docs/assets/missing.svg">',
        '<img src="../outside.png">',
        '<a href="docs/guide.md#missing">Guide</a>',
        '<a href="javascript:alert">Unsafe</a>',
        '<a href="docs/guide.md" href="missing.md">Ambiguous</a>',
        "<img src>",
        '<img src="">',
    ],
)
def test_html_references_cannot_hide_missing_or_unsafe_targets(checkout, markup):
    root, _ = checkout
    (root / "README.md").write_text(markup, encoding="utf-8")
    with pytest.raises(ValueError):
        release.inspect_project(root)


def test_html_examples_in_code_and_comments_are_not_followed(checkout):
    root, _ = checkout
    (root / "README.md").write_text(
        '```html\n<img src="missing.png">\n```\n'
        '`<a href="missing.md">example</a>`\n'
        '<!-- <img src="private.png"> -->\n'
        '<a href="docs/guide.md#setup">Guide</a>\n',
        encoding="utf-8",
    )
    assert release.inspect_project(root)["links"]["local_links"] == 1


@pytest.mark.parametrize("fault", ["extra_file", "empty_directory", "outside", "non_image"])
def test_documentation_image_inventory_rejects_unreviewed_entries(checkout, fault):
    root, policy = checkout
    asset = root / "docs/assets/badge.svg"
    asset.parent.mkdir(parents=True)
    asset.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    policy["documentation_assets"] = {
        "docs/assets/badge.svg": release.sha(root, "docs/assets/badge.svg")
    }
    if fault == "extra_file":
        (asset.parent / "unreviewed.svg").write_text("unreviewed", encoding="utf-8")
    elif fault == "empty_directory":
        (asset.parent / "unreviewed").mkdir()
    elif fault == "outside":
        policy["documentation_assets"] = {"demo/styles.css": release.sha(root, "demo/styles.css")}
    else:
        script = asset.parent / "private.py"
        script.write_text("private", encoding="utf-8")
        policy["documentation_assets"] = {
            "docs/assets/private.py": release.sha(root, "docs/assets/private.py")
        }
    seal(root / release.INVENTORY, policy)
    with pytest.raises(ValueError, match="Documentation assets|documentation asset inventory"):
        release.inspect_project(root)


def test_duplicate_and_unicode_heading_fragments():
    assert release.heading_ids("# Setup\n# Setup\n# Setup-1\n# Café & API\n") == {
        "setup",
        "setup-1",
        "setup-1-1",
        "café--api",
    }


def test_line_fragments_have_real_bounds(checkout):
    root, _ = checkout
    (root / "README.md").write_text(f"[Source]({release.SCRIPT}#L1)\n", encoding="utf-8")
    assert release.inspect_project(root)["links"]["fragments"] == 1
    (root / "README.md").write_text(f"[Source]({release.SCRIPT}#L100)\n", encoding="utf-8")
    with pytest.raises(ValueError, match="out of bounds"):
        release.inspect_project(root)


def test_doc_changes_create_new_identity_without_rewriting_historical_evidence(checkout):
    root, _ = checkout
    before = release.inspect_project(root)
    path = root / "docs/guide.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nReviewed setup.\n", encoding="utf-8")
    after = release.inspect_project(root)
    assert before != after
    assert before["evidence_sha256"] == after["evidence_sha256"]
    assert before["static_assets_sha256_lf"] == after["static_assets_sha256_lf"]


def test_crlf_normalization_preserves_source_identity_but_not_evidence_pins(checkout):
    root, _ = checkout
    before = release.inspect_project(root)
    path = root / "README.md"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert before == release.inspect_project(root)


@pytest.mark.parametrize("checkout_eol", ["lf", "crlf"])
def test_git_checkout_preserves_legacy_evidence_byte_pins(tmp_path, checkout_eol):
    # These published inputs have LF Git blobs and CRLF checksum identities.
    names = (
        "baseline/baseline_v1.json",
        "item_knn/item_knn_v1.json",
        "mf/als_experiments_v1.json",
        "mf/als_final_v1.json",
        "popularity/global_popularity_v1.json",
        "popularity/recent_popularity_v1.json",
        "ranking/m10_feature_audit_v1.json",
        "ranking/m10_quality_v1.json",
        "ranking/ranker_development_v1.json",
        "ranking/ranker_diagnostic_v1.json",
        "ranking/ranker_selection_lock_v1.json",
        "rolling/als_sweep.json",
        "rolling/cold.json",
        "rolling/item_knn_sweep.json",
        "rolling/manifest.json",
        "rolling/results.json",
    )
    root = tmp_path / "git-checkout"
    root.mkdir()

    def git(*args):
        subprocess.run(
            [
                "git",
                "-c",
                "core.autocrlf=false",
                "-c",
                f"core.eol={checkout_eol}",
                "-c",
                "core.safecrlf=false",
                *args,
            ],
            cwd=root,
            check=True,
            capture_output=True,
            timeout=15,
        )

    git("init", "--quiet")
    shutil.copyfile(release.ROOT / ".gitattributes", root / ".gitattributes")
    pins = release.read_json(release.ROOT, release.INVENTORY)["evidence"]
    for name in names:
        relative = f"benchmarks/{name}"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((release.ROOT / relative).read_bytes().replace(b"\r\n", b"\n"))
    git("add", "--", ".gitattributes", "benchmarks")
    for name in names:
        (root / "benchmarks" / name).unlink()
    git("checkout-index", "--all", "--force")
    for name in names:
        relative = f"benchmarks/{name}"
        assert release.sha(root, relative) == pins[relative], relative


def test_publish_is_non_overwriting_and_cleans_pending_file(checkout):
    root, _ = checkout
    result = release.inspect_project(root)
    release.write_once(root, ".local/receipt.json", result)
    first = (root / ".local/receipt.json").read_bytes()
    with pytest.raises(FileExistsError):
        release.write_once(root, ".local/receipt.json", result)
    assert (root / ".local/receipt.json").read_bytes() == first
    assert list((root / ".local").glob("*.tmp")) == []
    release.sealed(release.read_json(root, ".local/receipt.json"))


@pytest.mark.parametrize(
    "name", ["../receipt.json", ".local/../receipt.json", ".local/receipt.txt"]
)
def test_unsafe_publication_targets_are_rejected(checkout, name):
    root, _ = checkout
    with pytest.raises(ValueError):
        release.write_once(root, name, release.inspect_project(root))


def test_unsealed_publication_cannot_create_a_success_receipt(checkout):
    root, _ = checkout
    with pytest.raises(ValueError, match="digest"):
        release.write_once(root, ".local/invalid.json", {"documentation_integrity_passed": True})
    assert not (root / ".local/invalid.json").exists()


def test_sealed_inventory_tamper_is_detected(checkout):
    root, policy = checkout
    altered = copy.deepcopy(policy)
    altered["scope"] = "other"
    (root / release.INVENTORY).write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(ValueError, match="digest differs"):
        release.inspect_project(root)


def test_file_symlink_is_never_a_release_input(checkout):
    root, _ = checkout
    target = root / "README.md"
    backup = root / "original.md"
    target.rename(backup)
    try:
        target.symlink_to(backup)
    except OSError as exc:
        target.write_bytes(backup.read_bytes())
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows account lacks file-symlink privilege")
        raise
    with pytest.raises(ValueError, match="Symlink"):
        release.inspect_project(root)


def test_saved_receipt_rejects_intentional_source_drift(checkout):
    root, _ = checkout
    release.write_once(root, ".local/receipt.json", release.inspect_project(root))
    assert release.verify_receipt(root, ".local/receipt.json")["documentation_integrity_passed"]
    (root / release.TEST).write_text("# Changed tests\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        release.verify_receipt(root, ".local/receipt.json")


def test_saved_receipt_cannot_claim_unexecuted_work(checkout):
    root, _ = checkout
    result = release.inspect_project(root)
    result["model_loaded_or_fitted"] = True
    seal(root / ".local/receipt.json", result)
    with pytest.raises(ValueError, match="stale"):
        release.verify_receipt(root, ".local/receipt.json")


def test_oversized_inputs_are_rejected_before_parsing(checkout, monkeypatch):
    root, _ = checkout
    monkeypatch.setattr(release, "LIMIT", 100)
    with pytest.raises(ValueError, match="byte budget"):
        release.inspect_project(root)
