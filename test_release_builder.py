"""Regression tests for release archive metadata generation."""

import json
import os
import ast
import sys
import tempfile
import traceback
from unittest.mock import patch
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
        (source / "_internal" / "PySide6").mkdir(parents=True)
        (source / "FT-DataUpload.exe").write_bytes(b"desktop executable")
        (source / "FT-Capture.exe").write_bytes(b"capture executable")
        (source / "_internal" / "runtime" / "model.bin").write_bytes(b"ocr model")
        (source / "_internal" / "PySide6" / "Qt6Core.dll").write_bytes(b"qt core")
        (source / "_internal" / "PySide6" / "Qt6Widgets.dll").write_bytes(b"qt widgets")

        archive, source_archive, metadata_file, checksum_file, source_checksum_file, metadata = create_release_archive(
            source,
            root / "release",
            version="1.5.0",
            generated_at="2026-08-22T12:00:00Z",
        )

        assert archive.name == "FT-DataUpload-v1.5.0.zip"
        assert metadata_file.name == "build-audit-info.json"
        assert checksum_file.name == "FT-DataUpload-v1.5.0.sha256.txt"
        assert metadata == json.loads(metadata_file.read_text(encoding="utf-8"))
        assert source_archive.name == "FT-DataUpload-v1.5.0-private-build-source.zip"
        assert source_archive.parent.name == "private"
        assert source_checksum_file.name == "FT-DataUpload-v1.5.0-private-build-source.sha256.txt"
        assert metadata["schemaVersion"] == "internal-1"
        assert metadata["version"] == "1.5.0"
        assert metadata["portable"]["sizeBytes"] == archive.stat().st_size
        assert metadata["portable"]["sha256"] == sha256_file(archive)
        assert metadata["privateBuildSource"]["sizeBytes"] == source_archive.stat().st_size
        assert metadata["privateBuildSource"]["sha256"] == sha256_file(source_archive)
        assert checksum_file.read_text(encoding="utf-8") == (
            f"{metadata['portable']['sha256']}  {archive.name}\n"
        )
        assert source_checksum_file.read_text(encoding="utf-8") == (
            f"{metadata['privateBuildSource']['sha256']}  {source_archive.name}\n"
        )
        assert b"\r" not in checksum_file.read_bytes()
        assert b"\r" not in source_checksum_file.read_bytes()

        with ZipFile(archive) as package:
            assert set(package.namelist()) == {
                "FT-DataUpload/FT-Capture.exe",
                "FT-DataUpload/FT-DataUpload.exe",
                "FT-DataUpload/_internal/runtime/model.bin",
                "FT-DataUpload/_internal/PySide6/Qt6Core.dll",
                "FT-DataUpload/_internal/PySide6/Qt6Widgets.dll",
                "FT-DataUpload/licenses/GPL-3.0.txt",
                "FT-DataUpload/licenses/LGPL-3.0.txt",
                "FT-DataUpload/licenses/RELINKING.md",
                "FT-DataUpload/licenses/PRIVATE-BUILD-AUDIT.md",
                "FT-DataUpload/licenses/THIRD-PARTY-NOTICES.md",
                "FT-DataUpload/licenses/UPSTREAM-SOURCES.json",
            }
            qt_source_notice = package.read("FT-DataUpload/licenses/RELINKING.md").decode("utf-8")
            assert "pyside-setup-everywhere-src-6.11.2.tar.xz" in qt_source_notice
            assert "qt-everywhere-src-6.11.2.zip" in qt_source_notice
            assert "three years" in qt_source_notice.lower()
            assert "FT Trading Hub website" in qt_source_notice
            assert "replace" in qt_source_notice.lower()

        with ZipFile(source_archive) as package:
            names = set(package.namelist())
            assert "FT-DataUpload-source/sc-trading-hub-desktop-tool/COPYING" in names
            assert "FT-DataUpload-source/sc-trading-hub-desktop-tool/COPYING.LESSER" in names
            assert "FT-DataUpload-source/sc-trading-hub-desktop-tool/QT-LGPL-SOURCE.md" in names
            assert "FT-DataUpload-source/sc-trading-hub-desktop-tool/SOURCE-BUILD.md" in names
            assert "FT-DataUpload-source/sc-trading-hub-desktop-tool/THIRD-PARTY-NOTICES.md" in names
            assert "FT-DataUpload-source/sc-trading-hub-desktop-tool/UPSTREAM-SOURCES.json" in names
            assert "FT-DataUpload-source/sc-trading-hub-desktop-tool/fetch_upstream_sources.py" in names
            assert "FT-DataUpload-source/sc-trading-hub-desktop-tool/main.py" in names
            assert "FT-DataUpload-source/sc-trading-hub-desktop-tool/FT-DataUpload.spec" in names
            assert "FT-DataUpload-source/sc-trading-hub/ocr-service/server.py" in names
            assert not any(".env" in name for name in names)
            assert not any("ft_upload_config.json" in name for name in names)


def test_release_builder_uses_the_application_contract_version():
    assert APP_VERSION == "2.0.0"


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
    (source / "_internal" / "PySide6").mkdir(parents=True)
    (source / "FT-DataUpload.exe").write_bytes(b"app")
    (source / "FT-Capture.exe").write_bytes(b"capture")
    (source / "_internal" / "runtime.dll").write_bytes(b"runtime")
    (source / "_internal" / "PySide6" / "Qt6Core.dll").write_bytes(b"qt core")
    (source / "_internal" / "PySide6" / "Qt6Widgets.dll").write_bytes(b"qt widgets")
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


def test_release_builder_rejects_gpl_only_qt_modules():
    for relative in (
        Path("_internal/PySide6/Qt6VirtualKeyboard.dll"),
        Path("_internal/PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll"),
    ):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _valid_distribution(root)
            forbidden = source / relative
            forbidden.parent.mkdir(parents=True, exist_ok=True)
            forbidden.write_bytes(b"GPL-only Qt module")
            try:
                create_release_archive(source, root / "release")
            except ValueError as exc:
                assert "GPL-only Qt" in str(exc)
            else:
                raise AssertionError(f"GPL-only Qt module was accepted: {relative}")


def test_release_builder_rejects_pyqt6_runtime():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = _valid_distribution(root)
        forbidden = source / "_internal" / "PyQt6" / "Qt6" / "bin" / "Qt6Core.dll"
        forbidden.parent.mkdir(parents=True)
        forbidden.write_bytes(b"GPL runtime")
        try:
            create_release_archive(source, root / "release")
        except ValueError as exc:
            assert "PyQt6" in str(exc)
        else:
            raise AssertionError("PyQt6 runtime was accepted")


def test_release_builder_requires_replaceable_qt_core_and_widgets_libraries():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = _valid_distribution(root)
        (source / "_internal" / "PySide6" / "Qt6Widgets.dll").unlink()
        try:
            create_release_archive(source, root / "release")
        except FileNotFoundError as exc:
            assert "qt6widgets.dll" in str(exc).lower()
        else:
            raise AssertionError("distribution without Qt6Widgets.dll was accepted")


def test_release_staging_cleanup_retries_a_transient_windows_file_lock():
    with tempfile.TemporaryDirectory() as temp:
        parent = Path(temp)
        real_rmtree = build_release.shutil.rmtree
        attempts = 0

        def transient_lock(path):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise PermissionError(32, "file is temporarily in use")
            real_rmtree(path)

        with patch.object(build_release.shutil, "rmtree", side_effect=transient_lock), \
                patch.object(build_release.time, "sleep"):
            with build_release.release_temporary_directory(".test-", parent) as staging:
                (staging / "unsigned.exe").write_bytes(b"MZ")

        assert attempts == 2
        assert not staging.exists()


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
