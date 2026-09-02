"""Tests for the desktop-to-backend upload contract."""
import copy
import sys
import traceback

from upload_contract import (
    APP_VERSION,
    PRIVACY_POLICY_VERSION,
    build_snapshot_items,
    build_snapshot_payload,
    is_valid_device_id,
    is_upload_ready,
    normalize_scm_id,
)


DEVICE_ID = "123e4567-e89b-42d3-a456-426614174000"


def test_release_version_matches_backend_gate():
    assert APP_VERSION == "2.0.0"


def test_upload_gate_requires_scm_id_and_explicit_consent():
    assert PRIVACY_POLICY_VERSION == "2026-08-28"
    assert is_upload_ready("player-123", True, PRIVACY_POLICY_VERSION) is True
    assert is_upload_ready("player-123", True, "2026-08-23") is False
    assert is_upload_ready("player-123", True, "") is False
    assert is_upload_ready("  ", True, PRIVACY_POLICY_VERSION) is False
    assert is_upload_ready("", True, PRIVACY_POLICY_VERSION) is False
    assert is_upload_ready("player-123", False, PRIVACY_POLICY_VERSION) is False
    assert is_upload_ready("player-123", 1, PRIVACY_POLICY_VERSION) is False
    assert is_upload_ready("x" * 101, True, PRIVACY_POLICY_VERSION) is False


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


def test_payload_contains_optional_scm_points_metadata_without_mutating_result():
    result = {
        "terminal": "列夫斯基",
        "transactionType": "buy",
        "items": [{"commodityName": "废料", "scu": 20, "price": 1.2}],
    }
    original = copy.deepcopy(result)
    payload = build_snapshot_payload(result, "  player-123  ", DEVICE_ID)
    assert payload["terminal"] == "列夫斯基"
    assert payload["scmId"] == "player-123"
    assert payload["version"] == APP_VERSION
    assert payload["deviceId"] == DEVICE_ID
    assert payload["items"][0]["transactionType"] == "buy"
    assert result == original

    anonymous_payload = build_snapshot_payload(result, "  ", DEVICE_ID)
    assert "scmId" not in anonymous_payload


def test_scm_id_is_optional_bounded_points_metadata():
    assert normalize_scm_id("  player-123  ") == "player-123"
    assert normalize_scm_id("") == ""
    for invalid in ("x" * 101, "player\n123", "player\x7f123"):
        try:
            normalize_scm_id(invalid)
            raise AssertionError("invalid SCM ID should fail")
        except ValueError:
            pass


def test_device_id_is_required_and_must_be_a_random_uuid4_shape():
    assert is_valid_device_id(DEVICE_ID) is True
    assert is_valid_device_id("player-123") is False
    try:
        build_snapshot_payload({}, "player-123", "bad")
        raise AssertionError("invalid device ID should fail")
    except ValueError:
        pass


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
