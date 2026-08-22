"""Pure upload-contract helpers shared by the GUI and regression tests."""

import re

APP_VERSION = "1.4.0"
_DEVICE_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def is_upload_ready(scm_id, privacy_agreed):
    """Uploading requires consent; SCM ID is optional and only links points."""
    return privacy_agreed is True


def build_snapshot_items(result):
    """Normalize OCR output into the backend snapshot item contract."""
    tx = result.get("transactionType", "buy")
    return [
        {
            "commodityName": item.get("commodityName", ""),
            "transactionType": tx,
            "inventoryLevel": item.get("inventoryLevel") or None,
            "scu": item.get("scu"),
            "price": item.get("price"),
            "isMaxStock": item.get("isMaxStock", False),
        }
        for item in result.get("items", [])
    ]


def is_valid_device_id(device_id):
    """Device IDs support rate limiting/consensus only; they are not identity."""
    return bool(_DEVICE_ID_RE.fullmatch(str(device_id or "").strip()))


def build_snapshot_payload(result, scm_id, device_id):
    """Build the versioned request body accepted by /api/upload/snapshot."""
    normalized_device_id = str(device_id or "").strip()
    if not is_valid_device_id(normalized_device_id):
        raise ValueError("invalid device ID")
    return {
        "terminal": result.get("terminal", ""),
        "items": build_snapshot_items(result),
        "scmId": str(scm_id or "").strip(),
        "deviceId": normalized_device_id,
        "version": APP_VERSION,
    }
