"""Public desktop-release lookup helpers.

The updater never downloads or installs a package. It only determines whether
the website has published a newer version and gives the UI a safe browser URL.
"""

import re

import requests


DATA_COLLECTION_URL = "https://fantiantradinghub.xyz/data-collection"
_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def _version_key(version: str):
    """Return a comparable semantic-version key, or None for invalid input."""
    if not isinstance(version, str):
        return None
    match = _SEMVER_RE.fullmatch(version.strip())
    if not match:
        return None
    base = tuple(int(match.group(part)) for part in ("major", "minor", "patch"))
    prerelease = match.group("prerelease")
    if prerelease is None:
        return base, (1,)

    identifiers = []
    for value in prerelease.split("."):
        identifiers.append((0, int(value)) if value.isdigit() else (1, value))
    return base, (0, tuple(identifiers))


def is_newer_version(published_version: str, installed_version: str) -> bool:
    """Compare published and installed Semantic Versions without raising."""
    published = _version_key(published_version)
    installed = _version_key(installed_version)
    return bool(published and installed and published > installed)


def check_for_update(api_base: str, installed_version: str, http_get=requests.get):
    """Return a newer published version, or None when current/unavailable.

    Transport and response errors are intentionally swallowed: release checking
    is optional and must never affect desktop startup or uploads.
    """
    try:
        response = http_get(f"{api_base.rstrip('/')}/api/desktop-release", timeout=4)
        response.raise_for_status()
        data = response.json()
        release = data.get("release") if isinstance(data, dict) else None
        version = release.get("version") if data.get("available") is True and isinstance(release, dict) else None
        return version if is_newer_version(version, installed_version) else None
    except Exception:
        return None
