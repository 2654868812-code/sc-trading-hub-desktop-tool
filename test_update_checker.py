"""Regression tests for the desktop update notification contract."""

import sys
import traceback

from update_checker import DATA_COLLECTION_URL, check_for_update, is_newer_version


class Response:
    def __init__(self, payload, ok=True, url=None):
        self.payload = payload
        self.ok = ok
        self.url = url
        self.status_code = 200 if ok else 500
        self.history = []

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("HTTP error")

    def json(self):
        return self.payload


def test_semver_comparison_accepts_newer_stable_releases_only():
    assert is_newer_version("1.3.1", "1.3.0") is True
    assert is_newer_version("1.4.0", "1.3.9") is True
    assert is_newer_version("1.3.0", "1.3.0") is False
    assert is_newer_version("1.2.9", "1.3.0") is False
    assert is_newer_version("bad-version", "1.3.0") is False


def test_update_check_uses_public_release_endpoint_and_never_downloads():
    requested = []

    def get(url, **kwargs):
        requested.append((url, kwargs))
        return Response({"available": True, "release": {"version": "1.4.0"}}, url=url)

    assert check_for_update("https://example.test/", "1.3.0", get) == "1.4.0"
    assert requested == [(
        "https://example.test/api/desktop-release",
        {
            "headers": {"Accept": "application/json"},
            "timeout": 4,
            "allow_redirects": False,
            "verify": True,
        },
    )]
    assert DATA_COLLECTION_URL == "https://fantiantradinghub.xyz/data-collection"


def test_update_check_quietly_ignores_absent_release_and_network_errors():
    assert check_for_update("https://example.test", "1.3.0", lambda *_args, **_kwargs: Response({"available": True, "release": None})) is None

    def failing_get(*_args, **_kwargs):
        raise OSError("offline")

    assert check_for_update("https://example.test", "1.3.0", failing_get) is None


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
