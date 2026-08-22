"""Pure upload-contract helpers shared by the GUI and regression tests."""

import re

APP_VERSION = "1.5.0"
_DEVICE_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def is_upload_ready(scm_id, privacy_agreed):
    """The desktop workflow requires both an SCM ID and explicit consent."""
    try:
        return privacy_agreed is True and bool(normalize_scm_id(scm_id))
    except ValueError:
        return False


def normalize_scm_id(value):
    """Normalize optional points metadata without treating it as identity."""
    scm_id = str(value or "").strip()
    if len(scm_id) > 100:
        raise ValueError("SCM ID 最多 100 个字符")
    if any(ord(char) < 32 or ord(char) == 127 for char in scm_id):
        raise ValueError("SCM ID 不能包含控制字符")
    return scm_id


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
    """Build an upload body with optional, self-asserted points metadata."""
    normalized_device_id = str(device_id or "").strip()
    if not is_valid_device_id(normalized_device_id):
        raise ValueError("invalid device ID")
    payload = {
        "terminal": result.get("terminal", ""),
        "items": build_snapshot_items(result),
        "deviceId": normalized_device_id,
        "version": APP_VERSION,
    }
    normalized_scm_id = normalize_scm_id(scm_id)
    if normalized_scm_id:
        payload["scmId"] = normalized_scm_id
    return payload
