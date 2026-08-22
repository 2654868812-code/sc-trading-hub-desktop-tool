"""Tests for the desktop-to-backend upload contract."""
import copy
import sys
import traceback

from upload_contract import (
    APP_VERSION,
    build_snapshot_items,
    build_snapshot_payload,
    is_upload_ready,
)


def test_release_version_matches_backend_gate():
    assert APP_VERSION == "1.3.0"


def test_upload_gate_requires_trimmed_id_and_explicit_consent():
    assert is_upload_ready("player-123", True) is True
    assert is_upload_ready("  ", True) is False
    assert is_upload_ready("player-123", False) is False
    assert is_upload_ready("player-123", 1) is False


def test_snapshot_items_use_page_transaction_and_preserve_reliable_max_signal():
    result = {
        "transactionType": "sell",
        "items": [
            {
                "commodityName": "黄金",
                "inventoryLevel": "库存已满",
                "scu": 320,
                "price": 7.5,
                "isMaxStock": True,
            },
            {"commodityName": "铁", "scu": 10, "price": 2.0},
        ],
    }
    assert build_snapshot_items(result) == [
        {
            "commodityName": "黄金",
            "transactionType": "sell",
            "inventoryLevel": "库存已满",
            "scu": 320,
            "price": 7.5,
            "isMaxStock": True,
        },
        {
            "commodityName": "铁",
            "transactionType": "sell",
            "inventoryLevel": None,
            "scu": 10,
            "price": 2.0,
            "isMaxStock": False,
        },
    ]


def test_payload_contains_identity_version_terminal_and_does_not_mutate_ocr_result():
    result = {
        "terminal": "列夫斯基",
        "transactionType": "buy",
        "items": [{"commodityName": "废料", "scu": 20, "price": 1.2}],
    }
    original = copy.deepcopy(result)
    payload = build_snapshot_payload(result, "  player-123  ")
    assert payload["terminal"] == "列夫斯基"
    assert payload["scmId"] == "player-123"
    assert payload["version"] == APP_VERSION
    assert payload["items"][0]["transactionType"] == "buy"
    assert result == original


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}:")
                traceback.print_exc()
    print(f"{failed} failed")
    sys.exit(1 if failed else 0)
