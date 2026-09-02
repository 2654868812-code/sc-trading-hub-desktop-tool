"""Download and verify the exact LGPL upstream source archives retained per release."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import urllib.request
from pathlib import Path

from build_release import ROOT, sha256_file, write_text_lf

MANIFEST = ROOT / "UPSTREAM-SOURCES.json"


def fetch_upstream_sources(output_dir: Path) -> list[Path]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    verified: list[Path] = []
    for artifact in manifest["archives"]:
        destination = output_dir / artifact["fileName"]
        if not (destination.is_file()
                and destination.stat().st_size == artifact["sizeBytes"]
                and sha256_file(destination) == artifact["sha256"]):
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.name}.", suffix=".part", dir=output_dir, delete=False,
            ) as stream:
                temporary = Path(stream.name)
            try:
                request = urllib.request.Request(
                    artifact["url"], headers={"User-Agent": "FT-DataUpload-release-builder/2.0"},
                )
                last_error: Exception | None = None
                for attempt in range(3):
                    try:
                        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as stream:
                            while chunk := response.read(1024 * 1024):
                                stream.write(chunk)
                        last_error = None
                        break
                    except (OSError, TimeoutError) as exc:
                        last_error = exc
                        temporary.unlink(missing_ok=True)
                        if attempt < 2:
                            time.sleep(2 ** attempt)
                if last_error is not None:
                    raise last_error
                if temporary.stat().st_size != artifact["sizeBytes"]:
                    raise ValueError(f"Unexpected upstream source size: {artifact['fileName']}")
                if sha256_file(temporary) != artifact["sha256"]:
                    raise ValueError(f"Unexpected upstream source SHA-256: {artifact['fileName']}")
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        verified.append(destination)

    checksum = output_dir / "UPSTREAM-SOURCES.sha256.txt"
    write_text_lf(
        checksum,
        "".join(f"{artifact['sha256']}  {artifact['fileName']}\n" for artifact in manifest["archives"]),
    )
    return verified


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "release" / "upstream-sources")
    args = parser.parse_args()
    for path in fetch_upstream_sources(args.output_dir):
        print(f"Verified: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
