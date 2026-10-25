"""Check release documentation and pinned evidence without model or network access."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = "benchmarks/release/documentation_inventory_publication_v1.json"
PRESENTATION = "benchmarks/demo/showcase_presentation_validation_v1.json"
SCRIPT = "scripts/verify_project_documentation.py"
TEST = "tests/unit/test_project_documentation.py"
ASSETS = frozenset(
    f"demo/{name}"
    for name in (
        "index.html",
        "styles.css",
        "app.js",
        "schema.mjs",
        "transport.mjs",
        "favicon.svg",
        "data/showcase_v1.json",
    )
)
LIMIT = 16 * 1024**2
CONSTRAINTS = {
    "full_model_public": False,
    "later_folds_blind": False,
    "static_demo_live_inference": False,
}
LINK = re.compile(r"(?<!\\)!?\[[^\]\n]*\]\((<[^>\n]+>|[^\s)]+)(?:\s+[^)\n]*)?\)")
REFERENCE = re.compile(r"^ {0,3}\[[^\]\n]+\]:\s*(<[^>\n]+>|\S+)", re.M)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def canonical_path(name: object) -> str:
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or any(ord(char) < 32 for char in name)
        or PurePosixPath(name).is_absolute()
        or any(part in (".", "..") for part in name.split("/"))
        or ":" in name
        or PurePosixPath(name).as_posix() != name
    ):
        raise ValueError("Expected a canonical checkout-relative path.")
    return name


def safe_path(root: Path, name: str, *, directory: bool = False) -> Path:
    canonical_path(name)
    target = root / name
    if not target.resolve().is_relative_to(root):
        raise ValueError(f"Path escapes the checkout: {name}")
    for part in (target, *target.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError(f"Symlink is not a release input: {name}")
    if not (target.is_dir() if directory else target.is_file()):
        raise ValueError(f"Missing release {'directory' if directory else 'file'}: {name}")
    return target


def read_bytes(root: Path, name: str) -> bytes:
    path = safe_path(root, name)
    if path.stat().st_size > LIMIT:
        raise ValueError(f"Release file exceeds byte budget: {name}")
    with path.open("rb") as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError(f"Release file exceeds byte budget: {name}")
    return raw


def sha(root: Path, name: str, *, normalize: bool = False) -> str:
    raw = read_bytes(root, name)
    return hashlib.sha256(raw.replace(b"\r\n", b"\n") if normalize else raw).hexdigest()


def read_json(root: Path, name: str) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field.")
            result[key] = value
        return result

    def finite(text):
        number = float(text)
        if not math.isfinite(number):
            raise ValueError("Nonfinite JSON number.")
        return number

    def invalid(_):
        raise ValueError("Nonfinite JSON constant.")

    try:
        result = json.loads(
            read_bytes(root, name).decode("utf-8"),
            object_pairs_hook=unique,
            parse_float=finite,
            parse_constant=invalid,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, OverflowError) as exc:
        raise ValueError(f"Invalid release JSON: {name}") from exc
    if not isinstance(result, dict):
        raise ValueError("Release JSON must be an object.")
    return result


def sealed(value: dict) -> None:
    pin = value.get("content_sha256")
    if not isinstance(pin, str) or not re.fullmatch("[a-f0-9]{64}", pin):
        raise ValueError("Missing release content digest.")
    if digest({key: item for key, item in value.items() if key != "content_sha256"}) != pin:
        raise ValueError("Release content digest differs.")


def path_list(value: object, suffix: str | None = None) -> list[str]:
    if not isinstance(value, list) or not 0 < len(value) <= 256:
        raise ValueError("Expected a bounded nonempty release path list.")
    names = [canonical_path(name) for name in value]
    if len(set(names)) != len(names) or names != sorted(names):
        raise ValueError("Release path list must be sorted and unique.")
    if suffix and any(not name.endswith(suffix) for name in names):
        raise ValueError("Unexpected release file extension.")
    return names


def pin_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not 0 < len(value) <= 256:
        raise ValueError("Expected a bounded nonempty pin map.")
    for name, pin in value.items():
        canonical_path(name)
        if not isinstance(pin, str) or not re.fullmatch("[a-f0-9]{64}", pin):
            raise ValueError("Invalid release file digest.")
    return value


def markdown_body(text: str) -> str:
    """Exclude fenced code; command examples are never treated as links or executed."""
    output = []
    fence = None
    for line in text.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if match and fence is None:
            fence = match[1]
            output.append("")
        elif fence and re.fullmatch(rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}\s*", line):
            fence = None
            output.append("")
        else:
            output.append("" if fence else line)
    if fence:
        raise ValueError("Unclosed Markdown code fence.")
    return "\n".join(output)


def heading_ids(text: str) -> set[str]:
    body = markdown_body(text)
    ids = set(re.findall(r"\bid=[\"']([^\"']+)[\"']", body))
    used: dict[str, int] = {}
    lines = body.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        heading = match[1] if match else None
        if not heading and index and re.fullmatch(r" {0,3}(?:=+|-+)\s*", line):
            heading = lines[index - 1].strip()
        if not heading:
            continue
        heading = LINK.sub(lambda found: found[0].split("](", 1)[0].lstrip("!["), heading)
        heading = html.unescape(re.sub(r"<[^>]+>", "", heading)).lower()
        slug = "".join(
            char for char in heading if char in " _-" or unicodedata.category(char)[0] in "LN"
        ).replace(" ", "-")
        duplicate = used.get(slug, 0)
        candidate = f"{slug}-{duplicate}" if duplicate else slug
        while candidate in ids:
            duplicate += 1
            candidate = f"{slug}-{duplicate}"
        used[slug] = duplicate + 1
        ids.add(candidate)
    return ids


def check_links(root: Path, documents: list[str]) -> dict:
    links = fragments = external = 0
    cache: dict[str, set[str]] = {}
    for name in documents:
        try:
            body = markdown_body(document_text(root, name))
            body = re.sub(r"<!--[\s\S]*?-->", "", body)
            body = re.sub(r"(?<!`)(`+)(?!`)[\s\S]*?(?<!`)\1(?!`)", "", body)
        except UnicodeError as exc:
            raise ValueError(f"Invalid UTF-8 document: {name}") from exc
        targets = [match[1] for match in LINK.finditer(body)]
        targets += [match[1] for match in REFERENCE.finditer(body)]
        for target in targets:
            target = html.unescape(target.strip("<>"))
            parsed = urlsplit(target)
            if parsed.scheme in ("https", "http", "mailto"):
                external += 1
                continue
            if parsed.scheme or parsed.netloc or "\\" in target or parsed.query:
                raise ValueError(f"Unsupported local documentation URL in {name}")
            destination = (
                root / name if not parsed.path else ((root / name).parent / unquote(parsed.path))
            )
            # Reject aliases before resolution; links may legitimately contain '..'.
            for part in (destination, *destination.parents):
                if part == root:
                    break
                if part.is_symlink():
                    raise ValueError(f"Symlink documentation link in {name}")
            destination = destination.resolve()
            if not destination.is_relative_to(root):
                raise ValueError(f"Documentation link escapes checkout in {name}")
            relative = destination.relative_to(root).as_posix()
            if relative == ".":
                if parsed.fragment:
                    raise ValueError("A directory link cannot have a fragment.")
            else:
                safe_path(root, relative, directory=destination.is_dir())
            links += 1
            if not parsed.fragment:
                continue
            fragment = unquote(parsed.fragment)
            if destination.suffix.lower() == ".md":
                if relative not in cache:
                    cache[relative] = heading_ids(document_text(root, relative))
                if fragment not in cache[relative]:
                    raise ValueError(f"Broken heading fragment: {name} -> {target}")
            elif destination.is_file() and re.fullmatch(r"L[1-9]\d*(?:-L[1-9]\d*)?", fragment):
                bounds = [int(value) for value in re.findall(r"\d+", fragment)]
                length = len(read_bytes(root, relative).splitlines())
                if bounds != sorted(bounds) or max(bounds) > length:
                    raise ValueError(f"Source line fragment out of bounds in {name}")
            else:
                raise ValueError(f"Unsupported documentation fragment in {name}")
            fragments += 1
    return {"local_links": links, "fragments": fragments, "external_links_not_fetched": external}


def document_text(root: Path, name: str) -> str:
    text = read_bytes(root, name).decode("utf-8")
    if any(
        marker in text
        for marker in ("\ufffd", "\u00e2\u20ac", "\u00e2\u2030", "\u00e2\u2020", "\u00c3\u00a2")
    ):
        raise ValueError(f"Corrupted UTF-8 presentation in document: {name}")
    return text


def inspect_project(root: Path = ROOT, inventory: str = INVENTORY) -> dict:
    root = root.resolve()
    policy = read_json(root, inventory)
    sealed(policy)
    if (
        set(policy)
        != {
            "schema_version",
            "scope",
            "documents",
            "current_sources",
            "evidence",
            "static_assets",
            "constraints",
            "content_sha256",
        }
        or type(policy["schema_version"]) is not int
        or policy["schema_version"] != 1
    ):
        raise ValueError("Unsupported documentation inventory schema.")
    if policy["scope"] != "static-demo-and-local-snapshot-api":
        raise ValueError("Unsupported documentation release scope.")
    if policy["constraints"] != CONSTRAINTS or any(
        policy["constraints"].get(key) is not False for key in CONSTRAINTS
    ):
        raise ValueError("Documentation constraints changed.")
    documents = path_list(policy["documents"], ".md")
    sources = path_list(policy["current_sources"])
    if SCRIPT not in sources or TEST not in sources:
        raise ValueError("Documentation verifier and tests must be source-bound.")
    evidence, assets = pin_map(policy["evidence"]), pin_map(policy["static_assets"])
    if PRESENTATION not in evidence or set(assets) != ASSETS:
        raise ValueError("Incomplete presentation evidence or static asset inventory.")
    for name, pin in evidence.items():
        if not name.startswith("benchmarks/") or not name.endswith(".json"):
            raise ValueError("Evidence must be a benchmark JSON file.")
        if sha(root, name) != pin:
            raise ValueError(f"Frozen evidence fingerprint differs: {name}")
        read_json(root, name)
    presentation = read_json(root, PRESENTATION)
    sealed(presentation)
    pins = presentation.get("files_sha256_lf")
    if not isinstance(pins, dict) or any(pins.get(name) != pin for name, pin in assets.items()):
        raise ValueError("Static asset pins differ from released presentation.")
    for name, pin in assets.items():
        if sha(root, name, normalize=True) != pin:
            raise ValueError(f"Static presentation changed: {name}")
    allowed_dirs = {str(PurePosixPath(name).parent) for name in assets}
    for path in safe_path(root, "demo", directory=True).rglob("*"):
        name = path.relative_to(root).as_posix()
        if path.is_symlink() or name not in (allowed_dirs if path.is_dir() else assets):
            raise ValueError("Unexpected static demo inventory entry.")
    result = {
        "schema_version": 1,
        "verification": "project-documentation-v1",
        "documentation_integrity_passed": True,
        "scope": policy["scope"],
        "inventory_sha256": sha(root, inventory),
        "documents_sha256_lf": {name: sha(root, name, normalize=True) for name in documents},
        "sources_sha256_lf": {name: sha(root, name, normalize=True) for name in sources},
        "evidence_sha256": evidence,
        "static_assets_sha256_lf": assets,
        "links": check_links(root, documents),
        "network_accessed": False,
        "markdown_commands_executed": False,
        "model_loaded_or_fitted": False,
        "quality_recomputed": False,
        "full_model_deployment_eligible": False,
    }
    return {**result, "content_sha256": digest(result)}


def write_once(root: Path, name: str, result: dict) -> None:
    root = root.resolve()
    if not isinstance(result, dict):
        raise ValueError("Documentation receipt must be an object.")
    sealed(result)
    if (
        result.get("verification") != "project-documentation-v1"
        or result.get("documentation_integrity_passed") is not True
    ):
        raise ValueError("Unsupported documentation receipt.")
    canonical_path(name)
    path = root / name
    if path.suffix != ".json":
        raise ValueError("Documentation receipts must be JSON files.")
    parent_name = path.parent.relative_to(root).as_posix()
    if parent_name != ".":
        safe_path(root, parent_name, directory=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".documentation-", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def verify_receipt(root: Path, name: str) -> dict:
    result = inspect_project(root)
    previous = read_json(root.resolve(), name)
    sealed(previous)
    if previous != result:
        raise ValueError("Documentation receipt is stale for this checkout.")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", help="Compare this checkout with an existing relative receipt path"
    )
    mode.add_argument("--output", help="Publish a new receipt to an existing relative directory")
    args = parser.parse_args()
    try:
        result = verify_receipt(ROOT, args.check) if args.check else inspect_project()
        if args.output:
            write_once(ROOT, args.output, result)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Documentation verification failed: {exc}\n")
    print(
        json.dumps(
            {
                "documentation_integrity_passed": True,
                "documents": len(result["documents_sha256_lf"]),
                "evidence_files": len(result["evidence_sha256"]),
                **result["links"],
                "model_loaded_or_fitted": False,
                "full_model_deployment_eligible": False,
            }
        )
    )


if __name__ == "__main__":
    main()
