"""Regression tests for release archive metadata generation."""

import json
import os
import ast
import sys
import tempfile
import traceback
from pathlib import Path
from zipfile import ZipFile

import build_release
from build_release import create_release_archive, sha256_file
from upload_contract import APP_VERSION


def test_packaged_main_executable_requests_administrator_elevation():
    """The elevated game must not sit above the assistant's hotkey integrity level."""
    spec_tree = ast.parse((Path(__file__).parent / "FT-DataUpload.spec").read_text(encoding="utf-8"))
    executable_calls = [
        node
        for node in ast.walk(spec_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "EXE"
    ]
    declarations = {}
    for call in executable_calls:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
        name_node = keywords.get("name")
        admin_node = keywords.get("uac_admin")
        if isinstance(name_node, ast.Constant) and isinstance(name_node.value, str):
            declarations[name_node.value] = admin_node.value if isinstance(admin_node, ast.Constant) else None

    assert declarations["FT-DataUpload"] is True
    assert declarations["FT-Capture"] is False


def test_release_archive_emits_importable_metadata_and_checksum():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "FT-DataUpload"
        (source / "_internal" / "runtime").mkdir(parents=True)
        (source / "FT-DataUpload.exe").write_bytes(b"desktop executable")
        (source / "FT-Capture.exe").write_bytes(b"capture executable")
        (source / "_internal" / "runtime" / "model.bin").write_bytes(b"ocr model")

        archive, source_archive, metadata_file, checksum_file, source_checksum_file, metadata = create_release_archive(
            source,
            root / "release",
            version="1.5.0",
            generated_at="2026-08-22T12:00:00Z",
        )

        assert archive.name == "FT-DataUpload-v1.5.0.zip"
        assert metadata_file.name == "release-info.json"
        assert checksum_file.name == "FT-DataUpload-v1.5.0.sha256.txt"
        assert metadata == json.loads(metadata_file.read_text(encoding="utf-8"))
        assert source_archive.name == "FT-DataUpload-v1.5.0-source.zip"
        assert source_checksum_file.name == "FT-DataUpload-v1.5.0-source.sha256.txt"
        assert metadata["schemaVersion"] == 2
        assert metadata["version"] == "1.5.0"
        assert metadata["binary"]["sizeBytes"] == archive.stat().st_size
        assert metadata["binary"]["sha256"] == sha256_file(archive)
        assert metadata["source"]["sizeBytes"] == source_archive.stat().st_size
        assert metadata["source"]["sha256"] == sha256_file(source_archive)
        assert checksum_file.read_text(encoding="utf-8") == (
            f"{metadata['binary']['sha256']}  {archive.name}\n"
        )
        assert source_checksum_file.read_text(encoding="utf-8") == (
            f"{metadata['source']['sha256']}  {source_archive.name}\n"
        )

        with ZipFile(archive) as package:
            assert set(package.namelist()) == {
                "FT-DataUpload/FT-Capture.exe",
                "FT-DataUpload/FT-DataUpload.exe",
                "FT-DataUpload/_internal/runtime/model.bin",
                "FT-DataUpload/COPYING",
                "FT-DataUpload/SOURCE-BUILD.md",
                "FT-DataUpload/THIRD-PARTY-NOTICES.md",
            }

        with ZipFile(source_archive) as package:
            names = set(package.namelist())
            assert "FT-DataUpload-source/sc-trading-hub-desktop-tool/COPYING" in names
            assert "FT-DataUpload-source/sc-trading-hub-desktop-tool/SOURCE-BUILD.md" in names
            assert "FT-DataUpload-source/sc-trading-hub-desktop-tool/THIRD-PARTY-NOTICES.md" in names
            assert "FT-DataUpload-source/sc-trading-hub-desktop-tool/main.py" in names
            assert "FT-DataUpload-source/sc-trading-hub-desktop-tool/FT-DataUpload.spec" in names
            assert "FT-DataUpload-source/sc-trading-hub/ocr-service/server.py" in names
            assert not any(".env" in name for name in names)
            assert not any("ft_upload_config.json" in name for name in names)


def test_release_builder_uses_the_application_contract_version():
    assert APP_VERSION == "1.5.0"


def test_release_builder_rejects_invalid_version_and_empty_distribution():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        empty = root / "empty"
        empty.mkdir()
        try:
            create_release_archive(empty, root / "release", version="not-a-version")
            raise AssertionError("invalid version should fail")
        except ValueError:
            pass


def _valid_distribution(root: Path) -> Path:
    source = root / "FT-DataUpload"
    (source / "_internal").mkdir(parents=True)
    (source / "FT-DataUpload.exe").write_bytes(b"app")
    (source / "FT-Capture.exe").write_bytes(b"capture")
    (source / "_internal" / "runtime.dll").write_bytes(b"runtime")
    return source


def test_release_builder_rejects_missing_helper_and_sensitive_runtime_data():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = _valid_distribution(root)
        (source / "FT-Capture.exe").unlink()
        try:
            create_release_archive(source, root / "release")
            raise AssertionError("missing capture helper should fail")
        except FileNotFoundError:
            pass

    for relative in ("ft_ocr.log", "ft_upload_config.json", "screenshots/shot.png", "unknown.txt"):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _valid_distribution(root)
            extra = source / relative
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_bytes(b"private")
            try:
                create_release_archive(source, root / "release")
                raise AssertionError(f"sensitive/unknown path should fail: {relative}")
            except ValueError:
                pass


def test_release_builder_rejects_symlinks_when_supported():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = _valid_distribution(root)
        target = root / "outside.dll"
        target.write_bytes(b"outside")
        link = source / "_internal" / "linked.dll"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            return
        try:
            create_release_archive(source, root / "release")
            raise AssertionError("release must reject symlinks")
        except ValueError:
            pass


def test_release_builder_removes_external_icu_from_build_path():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        windows_root = root / "Windows"
        system32 = windows_root / "System32"
        external = root / "external-tools"
        clean = root / "clean-tools"
        for directory in (system32, external, clean):
            directory.mkdir(parents=True)
        (system32 / "icuuc.dll").write_bytes(b"windows system ICU")
        (external / "icuuc.dll").write_bytes(b"incompatible external ICU")

        sanitized = build_release.sanitized_build_environment({
            "PATH": os.pathsep.join((str(external), str(system32), str(clean))),
            "WINDIR": str(windows_root),
        })

        assert sanitized["PATH"].split(os.pathsep) == [str(system32), str(clean)]


def test_release_builder_rejects_external_icu_in_distribution():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = _valid_distribution(root)
        (source / "_internal" / "icuuc.dll").write_bytes(b"incompatible external ICU")
        try:
            create_release_archive(source, root / "release")
            raise AssertionError("external ICU must never ship in the release")
        except ValueError as exc:
            assert "ICU" in str(exc)


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
