"""Pure upload-contract helpers shared by the GUI and regression tests."""

APP_VERSION = "1.3.0"


def is_upload_ready(scm_id, privacy_agreed):
    """The desktop tool may capture/upload only after identity and consent exist."""
    return bool(str(scm_id or "").strip() and privacy_agreed is True)


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


def build_snapshot_payload(result, scm_id):
    """Build the versioned request body accepted by /api/upload/snapshot."""
    return {
        "terminal": result.get("terminal", ""),
        "items": build_snapshot_items(result),
        "scmId": str(scm_id or "").strip(),
        "version": APP_VERSION,
    }
