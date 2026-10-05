import json

import pandas as pd
import pytest

from ecommerce_recsys.data.rolling_provenance import manifest_fingerprint, verify_fold_files
from scripts.prepare_rolling_data import main as prepare_main


def test_prepare_rejects_off_protocol_window_count(monkeypatch):
    monkeypatch.setattr("sys.argv", ["prepare_rolling_data", "--n-windows", "9"])
    with pytest.raises(ValueError, match="requires 10 windows"):
        prepare_main()


def test_prepare_resumes_and_detects_same_count_file_change(tmp_path, monkeypatch):
    source = tmp_path / "interactions.parquet"
    raw = tmp_path / "raw"
    raw.mkdir()
    output = tmp_path / "rolling"
    manifest_path = tmp_path / "manifest.json"
    pd.DataFrame(
        {"user_id": ["u1"] * 10, "item_id": [f"i{i}" for i in range(10)], "timestamp": range(1, 11)}
    ).to_parquet(source, index=False)
    for part in (1, 2):
        (raw / f"item_properties_part{part}.csv").write_text(
            "timestamp,itemid,property,value\n1,i0,categoryid,c0\n", encoding="utf-8"
        )
    monkeypatch.setattr(
        "sys.argv",
        [
            "prepare_rolling_data",
            "--input-path",
            str(source),
            "--raw-dir",
            str(raw),
            "--output-dir",
            str(output),
            "--manifest-output",
            str(manifest_path),
        ],
    )

    prepare_main()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["folds"]) == 9
    assert len(manifest_fingerprint(manifest)) == 64
    verify_fold_files(manifest, output)
    prepare_main()

    partial = dict(manifest)
    partial["folds"] = manifest["folds"][:4]
    manifest_path.write_text(json.dumps(partial), encoding="utf-8")
    prepare_main()
    resumed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert resumed == manifest

    property_path = raw / "item_properties_part1.csv"
    original_property = property_path.read_text(encoding="utf-8")
    property_path.write_text(original_property + "2,i1,categoryid,c1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="different inputs or settings"):
        prepare_main()
    property_path.write_text(original_property, encoding="utf-8")

    first = output / "fold_01" / "warm_targets.parquet"
    changed = pd.read_parquet(first)
    changed.loc[0, "item_id"] = "different"
    changed.to_parquet(first, index=False)
    with pytest.raises(ValueError, match="Fold 1 files do not match"):
        verify_fold_files(manifest, output)
    with pytest.raises(ValueError, match="Existing fold 1 differs"):
        prepare_main()
