"""Script to download or verify the Retailrocket raw dataset.

Milestone 1 — Dataset Selection and Data Contract.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

EXPECTED_FILES = [
    "events.csv",
    "category_tree.csv",
    "item_properties_part1.csv",
    "item_properties_part2.csv",
]

DATASET_SLUG = "retailrocket/ecommerce-dataset"
KAGGLE_URL = "https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset"


def compute_file_info(file_path: Path) -> dict[str, str | int]:
    """Compute size and approximate line count for a file."""
    size_bytes = file_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)

    line_count = 0
    with file_path.open("rb") as f:
        for _ in f:
            line_count += 1

    return {
        "filename": file_path.name,
        "size_mb": round(size_mb, 2),
        "lines": line_count,
    }


def verify_dataset(raw_dir: Path) -> bool:
    """Verify that expected raw files exist and report stats."""
    print(f"\n[INFO] Verifying directory: {raw_dir.resolve()}")
    all_present = True

    for filename in EXPECTED_FILES:
        target = raw_dir / filename
        if not target.exists():
            print(f"  [MISSING] {filename}")
            all_present = False
        else:
            info = compute_file_info(target)
            print(
                f"  [OK] {filename} "
                f"({info['size_mb']} MB, {info['lines']:,} lines)"
            )

    if all_present:
        print("\n[SUCCESS] All Retailrocket raw files are present.")
        return True

    print("\n[WARNING] Some expected files are missing.")
    print(f"Please download the dataset from: {KAGGLE_URL}")
    return False


def download_via_kaggle(raw_dir: Path) -> bool:
    """Attempt to download dataset using Kaggle CLI."""
    kaggle_bin = shutil.which("kaggle")
    if not kaggle_bin:
        print("\n[INFO] Kaggle CLI not found in PATH.")
        print(f"Download manually from: {KAGGLE_URL}")
        print("and extract all CSV files into data/raw/")
        return False

    raw_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        kaggle_bin,
        "datasets",
        "download",
        "-d",
        DATASET_SLUG,
        "-p",
        str(raw_dir),
        "--unzip",
    ]
    print(f"\n[INFO] Running: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
        print("[SUCCESS] Download and extraction complete.")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"[ERROR] Download failed: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download or verify Retailrocket dataset."
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw"),
        help="Path to raw data directory (default: data/raw)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing files.",
    )

    args = parser.parse_args()
    raw_dir = args.raw_dir

    if args.verify_only:
        return 0 if verify_dataset(raw_dir) else 1

    all_exist = all((raw_dir / f).exists() for f in EXPECTED_FILES)
    if all_exist:
        print("[INFO] All raw files already exist.")
        return 0 if verify_dataset(raw_dir) else 1

    success = download_via_kaggle(raw_dir)
    if not success:
        return 1

    return 0 if verify_dataset(raw_dir) else 1


if __name__ == "__main__":
    sys.exit(main())
