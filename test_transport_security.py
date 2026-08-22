"""Regression tests for strict desktop transport policy."""

import traceback

from transport_security import (
    TransportSecurityError,
    normalize_api_base,
    secure_get_json,
    secure_post_json,
)


class Response:
    def __init__(self, payload=None, *, status_code=200, url=None, history=None):
        self.payload = payload if payload is not None else {"ok": True}
        self.status_code = status_code
        self.url = url
        self.history = [] if history is None else history

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")

    def json(self):
        return self.payload


def _raises(callable_):
    try:
        callable_()
    except TransportSecurityError:
        return
    raise AssertionError("transport policy should reject this value")


def test_api_base_accepts_https_and_exact_loopback_http_only():
    assert normalize_api_base("https://FantianTradingHub.xyz/") == "https://fantiantradinghub.xyz"
    assert normalize_api_base("http://localhost:4000") == "http://localhost:4000"
    assert normalize_api_base("http://127.0.0.2:4000") == "http://127.0.0.2:4000"
    assert normalize_api_base("http://[::1]:4000") == "http://[::1]:4000"
    for unsafe in (
        "http://114.55.238.180:3000",
        "http://localhost.example:4000",
        "https://user:pass@example.test",
        "https://example.test/api",
        "https://example.test?redirect=x",
        "ftp://example.test",
    ):
        _raises(lambda value=unsafe: normalize_api_base(value))


def test_secure_post_enables_ca_verification_and_disables_redirects():
    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response({"ok": True}, url=url)

    assert secure_post_json("https://example.test", "/api/upload/snapshot", {"x": 1}, http_post=post) == {"ok": True}
    assert captured["url"] == "https://example.test/api/upload/snapshot"
    assert captured["verify"] is True
    assert captured["allow_redirects"] is False
    assert captured["timeout"] == 10


def test_redirect_and_cross_origin_response_are_rejected():
    def redirect(url, **_kwargs):
        return Response(status_code=302, url=url)

    _raises(lambda: secure_get_json("https://example.test", "/api/release", http_get=redirect))

    def changed_origin(_url, **_kwargs):
        return Response(url="https://attacker.test/api/release")

    _raises(lambda: secure_get_json("https://example.test", "/api/release", http_get=changed_origin))


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
    raise SystemExit(1 if failed else 0)
