"""Strict transport policy for desktop-to-site JSON requests."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

import requests


class TransportSecurityError(ValueError):
    """Raised when a URL or response violates the desktop transport policy."""


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    if "%" in hostname:
        return False
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _origin(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise TransportSecurityError("服务器端口无效") from exc
    if not parsed.scheme or not parsed.hostname:
        raise TransportSecurityError("服务器地址无效")
    scheme = parsed.scheme.lower()
    return scheme, parsed.hostname.lower(), port or (443 if scheme == "https" else 80)


def normalize_api_base(value: object) -> str:
    """Accept HTTPS origins and exact loopback HTTP origins only."""
    if not isinstance(value, str) or not value.strip():
        raise TransportSecurityError("服务器地址不能为空")
    parsed = urlsplit(value.strip())
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname
    if scheme not in {"http", "https"} or not hostname:
        raise TransportSecurityError("服务器地址必须使用 HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise TransportSecurityError("服务器地址不能包含账户信息")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise TransportSecurityError("服务器地址只能包含协议、主机和端口")
    if scheme == "http" and not _is_loopback(hostname):
        raise TransportSecurityError("外部服务器必须使用 HTTPS")
    try:
        port = parsed.port
    except ValueError as exc:
        raise TransportSecurityError("服务器端口无效") from exc
    rendered_host = f"[{hostname.lower()}]" if ":" in hostname else hostname.lower()
    rendered_port = f":{port}" if port is not None else ""
    return f"{scheme}://{rendered_host}{rendered_port}"


def _validate_endpoint(endpoint: str) -> str:
    if not isinstance(endpoint, str) or not endpoint.startswith("/") or endpoint.startswith("//"):
        raise TransportSecurityError("请求路径无效")
    parsed = urlsplit(endpoint)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise TransportSecurityError("请求路径无效")
    return endpoint


def _validate_response(response, request_url: str) -> None:
    status = int(getattr(response, "status_code", 200))
    if 300 <= status < 400 or getattr(response, "history", None):
        raise TransportSecurityError("服务器重定向已被安全策略阻止")
    final_url = getattr(response, "url", None) or request_url
    if _origin(final_url) != _origin(request_url):
        raise TransportSecurityError("服务器响应发生了跨源跳转")
    final = urlsplit(final_url)
    if final.scheme.lower() == "http" and not _is_loopback(final.hostname or ""):
        raise TransportSecurityError("服务器响应降级为不安全 HTTP")


def _json_object(response) -> dict:
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise TransportSecurityError("服务器返回的数据格式无效")
    return value


def secure_post_json(
    api_base: str,
    endpoint: str,
    payload: dict,
    *,
    timeout: float = 10,
    http_post=requests.post,
) -> dict:
    base = normalize_api_base(api_base)
    request_url = base + _validate_endpoint(endpoint)
    response = http_post(
        request_url,
        json=payload,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=timeout,
        allow_redirects=False,
        verify=True,
    )
    _validate_response(response, request_url)
    return _json_object(response)


def secure_get_json(
    api_base: str,
    endpoint: str,
    *,
    timeout: float = 4,
    http_get=requests.get,
) -> dict:
    base = normalize_api_base(api_base)
    request_url = base + _validate_endpoint(endpoint)
    response = http_get(
        request_url,
        headers={"Accept": "application/json"},
        timeout=timeout,
        allow_redirects=False,
        verify=True,
    )
    _validate_response(response, request_url)
    return _json_object(response)
