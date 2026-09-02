"""Regression tests for the Windows installer build contract."""

import re
import json
import tempfile
import traceback
import sys
from pathlib import Path

from build_installer import (
    APP_ID,
    atomic_replace_with_exact_case,
    build_installer_release,
    compile_installer,
    stage_installer_tree,
    write_installer_release_metadata,
)


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "installer" / "FT-DataUpload.iss"


def _valid_distribution(root: Path) -> Path:
    source = root / "FT-DataUpload"
    (source / "_internal" / "PySide6").mkdir(parents=True)
    (source / "FT-DataUpload.exe").write_bytes(b"app")
    (source / "FT-Capture.exe").write_bytes(b"capture")
    (source / "_internal" / "PySide6" / "Qt6Core.dll").write_bytes(b"dynamic Qt")
    (source / "_internal" / "PySide6" / "Qt6Widgets.dll").write_bytes(b"dynamic widgets")
    return source


def _upstream_sources(root: Path):
    upstream = root / "upstream-sources"
    upstream.mkdir()
    qt = upstream / "qt-everywhere-src-6.11.2.zip"
    pyside = upstream / "pyside-setup-everywhere-src-6.11.2.tar.xz"
    qt.write_bytes(b"qt source")
    pyside.write_bytes(b"pyside source")
    manifest = root / "UPSTREAM-SOURCES.json"
    from build_release import sha256_file
    manifest.write_text(json.dumps({
        "schemaVersion": 1,
        "releaseVersion": "2.0.0",
        "archives": [
            {"fileName": pyside.name, "sizeBytes": pyside.stat().st_size, "sha256": sha256_file(pyside), "url": "https://download.qt.io/pyside"},
            {"fileName": qt.name, "sizeBytes": qt.stat().st_size, "sha256": sha256_file(qt), "url": "https://download.qt.io/qt"},
        ],
    }), encoding="utf-8")
    return upstream, manifest


def test_inno_script_locks_the_approved_install_and_uninstall_experience():
    script = SCRIPT.read_text(encoding="utf-8")

    assert APP_ID == "{B85B27CF-32C2-4F80-A187-27B0FA7E0A15}"
    assert "AppId={{B85B27CF-32C2-4F80-A187-27B0FA7E0A15}" in script
    assert "DefaultDirName={autopf}\\FT-DataUpload" in script
    assert "DisableDirPage=no" in script
    assert "PrivilegesRequired=lowest" in script
    assert "PrivilegesRequiredOverridesAllowed" not in script
    assert "ArchitecturesAllowed=x64compatible" in script
    assert "CloseApplications=yes" in script
    assert "CloseApplicationsFilter=FT-DataUpload.exe,FT-Capture.exe" in script
    assert "RestartApplications=no" in script
    assert re.search(r'Name: "desktopicon";(?![^\n]*unchecked)', script)
    assert 'Filename: "{app}\\FT-DataUpload.exe"; Description:' in script
    assert "postinstall" in script
    assert "SuppressibleMsgBox" in script
    assert "MB_DEFBUTTON2" in script
    assert "{localappdata}\\FantianTradingHub\\DesktopAssistant" in script
    assert "ExtractFileName(UserDataPath) = 'DesktopAssistant'" in script
    assert "ExtractFileName(ExtractFileDir(UserDataPath)) = 'FantianTradingHub'" in script
    assert "DelTree(UserDataPath, True, True, True)" in script
    assert "ChineseSimplified.isl" not in script
    assert "#error AppVersion must be supplied" in script
    assert '#define AppVersion "2.0.0"' not in script


def test_staging_copies_runtime_and_lgpl_materials_without_private_data():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = _valid_distribution(root)
        staged = stage_installer_tree(source, root / "stage")

        assert (staged / "FT-DataUpload.exe").read_bytes() == b"app"
        assert (staged / "FT-Capture.exe").read_bytes() == b"capture"
        assert (staged / "_internal" / "PySide6" / "Qt6Core.dll").is_file()
        for document in ("GPL-3.0.txt", "LGPL-3.0.txt", "RELINKING.md", "PRIVATE-BUILD-AUDIT.md", "THIRD-PARTY-NOTICES.md"):
            document = Path("licenses") / document
            assert (staged / document).is_file()
        assert not (staged / "ft_upload_config.json").exists()
        assert not (staged / "screenshots").exists()


def test_compile_installer_uses_defines_and_atomically_emits_expected_name():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = _valid_distribution(root)
        calls = []

        def fake_runner(command, **kwargs):
            calls.append((command, kwargs))
            defines = {
                item[2:].split("=", 1)[0]: item[2:].split("=", 1)[1]
                for item in command
                if item.startswith("/D")
            }
            output = Path(defines["OutputDir"])
            output.mkdir(parents=True, exist_ok=True)
            (output / "FT-DataUpload-v2.0.0-setup.exe").write_bytes(b"MZ" + b"\0" * 65534)

        installer = compile_installer(
            source,
            root / "release",
            version="2.0.0",
            iscc_path=root / "ISCC.exe",
            runner=fake_runner,
        )

        assert installer.name == "FT-DataUpload-v2.0.0-setup.exe"
        assert installer.read_bytes().startswith(b"MZ")
        command, kwargs = calls[0]
        assert command[0] == str(root / "ISCC.exe")
        assert "/DAppVersion=2.0.0" in command
        assert any(item.startswith("/DSourceDir=") for item in command)
        assert any(item.startswith("/DOutputDir=") for item in command)
        assert command[-1] == str(SCRIPT)
        assert kwargs["check"] is True


def test_atomic_replace_forces_exact_public_filename_case():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        existing = root / "FT-DataUpload-v2.0.0-Setup.exe"
        incoming_dir = root / "incoming"
        incoming_dir.mkdir()
        incoming = incoming_dir / "FT-DataUpload-v2.0.0-setup.exe"
        existing.write_bytes(b"old")
        incoming.write_bytes(b"new")

        expected = root / "FT-DataUpload-v2.0.0-setup.exe"
        atomic_replace_with_exact_case(incoming, expected)

        actual_names = [entry.name for entry in root.iterdir() if entry.is_file()]
        assert actual_names == ["FT-DataUpload-v2.0.0-setup.exe"]
        assert expected.read_bytes() == b"new"


def test_installer_metadata_is_schema_v4_and_omits_proprietary_source():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        installer = root / "FT-DataUpload-v2.0.0-setup.exe"
        installer.write_bytes(b"installer")
        upstream, manifest = _upstream_sources(root)

        metadata_path, metadata = write_installer_release_metadata(
            installer,
            upstream,
            root,
            version="2.0.0",
            generated_at="2026-09-01T12:00:00Z",
            manifest_path=manifest,
        )

        assert metadata["schemaVersion"] == 4
        assert metadata["installer"]["fileName"] == installer.name
        assert metadata["installer"]["signed"] is False
        assert [item["id"] for item in metadata["openSourceComponents"]] == ["qt", "pyside6"]
        assert metadata["openSourceComponents"][0]["source"]["fileName"] == "qt-everywhere-src-6.11.2.zip"
        assert "source" not in metadata
        assert "binary" not in metadata
        assert metadata_path.read_text(encoding="utf-8").endswith("\n")


def test_one_release_command_emits_installer_private_audit_source_and_v4_metadata():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = _valid_distribution(root)
        upstream, manifest = _upstream_sources(root)

        def fake_runner(command, **_kwargs):
            defines = {
                item[2:].split("=", 1)[0]: item[2:].split("=", 1)[1]
                for item in command
                if item.startswith("/D")
            }
            output = Path(defines["OutputDir"])
            output.mkdir(parents=True, exist_ok=True)
            (output / "FT-DataUpload-v2.0.0-setup.exe").write_bytes(b"MZ" + b"\0" * 65534)

        result = build_installer_release(
            source,
            root / "release",
            version="2.0.0",
            iscc_path=root / "ISCC.exe",
            runner=fake_runner,
            upstream_source_dir=upstream,
            upstream_manifest_path=manifest,
        )

        assert result["installer"].is_file()
        assert result["portable"].is_file()
        assert result["private_source"].is_file()
        assert result["private_source"].parent.name == "private"
        assert result["installer_checksum"].read_text(encoding="utf-8").endswith(
            "  FT-DataUpload-v2.0.0-setup.exe\n"
        )
        assert b"\r" not in result["installer_checksum"].read_bytes()
        assert b"\r" not in result["private_source_checksum"].read_bytes()
        assert result["private_source_checksum"].is_file()
        assert result["metadata"].is_file()
        assert '"schemaVersion": 4' in result["metadata"].read_text(encoding="utf-8")
        assert "private-build-source" not in result["metadata"].read_text(encoding="utf-8")


def test_failed_compiler_never_replaces_existing_public_metadata():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = _valid_distribution(root)
        upstream, manifest = _upstream_sources(root)
        release = root / "release"
        release.mkdir()
        metadata = release / "release-info.json"
        metadata.write_text('{"schemaVersion":3,"version":"previous"}\n', encoding="utf-8")

        def failing_runner(*_args, **_kwargs):
            raise RuntimeError("compiler failed")

        try:
            build_installer_release(
                source, release, version="2.0.0", iscc_path=root / "ISCC.exe",
                runner=failing_runner,
                upstream_source_dir=upstream,
                upstream_manifest_path=manifest,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("compiler failure must propagate")

        assert metadata.read_text(encoding="utf-8") == '{"schemaVersion":3,"version":"previous"}\n'


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
