"""Raw event validation must finish before processed artifacts can be written."""

from pathlib import Path

import pandas as pd
import pytest

from scripts.build_interactions import process_interactions


def _write_events(path: Path, rows: str) -> None:
    path.write_text(
        "timestamp,visitorid,event,itemid,transactionid\n" + rows,
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("row", "field"),
    [
        ("1,,view,10,\n", "visitorid"),
        ("1,1,view,,\n", "itemid"),
        ("1,1,,10,\n", "event"),
        ("1,1,invalid,10,\n", "event"),
        (",1,view,10,\n", "timestamp"),
        ("1.9,1,view,10,\n", "timestamp"),
        ("NaN,1,view,10,\n", "timestamp"),
        ("inf,1,view,10,\n", "timestamp"),
        ("0,1,view,10,\n", "timestamp"),
        ("-1,1,view,10,\n", "timestamp"),
        ("9223372036854775808,1,view,10,\n", "timestamp"),
        ("1,-1,view,10,\n", "visitorid"),
        ("1,1,view,10.5,\n", "itemid"),
        ("1,9223372036854775808,view,10,\n", "visitorid"),
        ("1,1,transaction,10,1.5\n", "transactionid"),
        ("1,1,transaction,10,-1\n", "transactionid"),
    ],
)
@pytest.mark.parametrize("existing_output", [False, True])
def test_invalid_events_do_not_create_or_replace_output(tmp_path, row, field, existing_output):
    source = tmp_path / "events.csv"
    output = tmp_path / "interactions.parquet"
    _write_events(source, row)
    if existing_output:
        output.write_bytes(b"previous artifact")

    with pytest.raises(ValueError, match=field):
        process_interactions(source, output)

    if existing_output:
        assert output.read_bytes() == b"previous artifact"
    else:
        assert not output.exists()


def test_valid_events_preserve_repeats_exact_ids_and_nullable_transactions(tmp_path):
    source = tmp_path / "events.csv"
    output = tmp_path / "interactions.parquet"
    _write_events(
        source,
        "3,9007199254740993,transaction,10,9007199254740995\n"
        "1,0,view,0,\n"
        "1,0,view,0,\n"
        "2,1,addtocart,11,\n",
    )

    result = process_interactions(source, output)

    assert result["timestamp"].tolist() == [1, 1, 2, 3]
    assert result["user_id"].tolist() == ["0", "0", "1", "9007199254740993"]
    assert result["item_id"].tolist() == ["0", "0", "11", "10"]
    assert result["transaction_id"].isna().tolist() == [True, True, True, False]
    assert result["transaction_id"].iloc[-1] == 9007199254740995
    assert str(result["timestamp"].dtype) == "int64"
    assert str(result["transaction_id"].dtype) == "Int64"
    assert result[["is_view", "is_cart", "is_purchase"]].values.tolist() == [
        [True, False, False],
        [True, False, False],
        [False, True, False],
        [False, False, True],
    ]
    pd.testing.assert_frame_equal(result, pd.read_parquet(output))


@pytest.mark.parametrize(
    "contents", ["timestamp,visitorid,event,itemid,transactionid\n", "timestamp,visitorid\n1,2\n"]
)
def test_empty_or_missing_columns_reject_before_writing(tmp_path, contents):
    source = tmp_path / "events.csv"
    source.write_text(contents, encoding="utf-8")
    output = tmp_path / "interactions.parquet"
    with pytest.raises(ValueError, match="empty|Missing required"):
        process_interactions(source, output)
    assert not output.exists()
