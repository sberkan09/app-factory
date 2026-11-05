"""Workspace ve CI yardımcılarının birim testleri."""

import pytest

from app_factory.schemas.contracts import CodeBundle, GeneratedFile
from app_factory.services.ci import error_fingerprint
from app_factory.services.workspace import WorkspaceService, app_slug, make_app_id


def test_app_slug_handles_turkish_and_symbols():
    assert app_slug("Su Takip!") == "su_takip"
    assert app_slug("Işık Ölçer") == "isik_olcer"
    assert app_slug("123 Go") == "app_123_go"
    assert make_app_id("com.acme.", "Su Takip") == "com.acme.su_takip"


def test_apply_bundle_writes_deletes_and_blocks_escape(tmp_path):
    ws = WorkspaceService(tmp_path)
    ws.apply_bundle("r1", CodeBundle(
        files=[GeneratedFile(path="lib/a.dart", content="a"), GeneratedFile(path="lib/b.dart", content="b")],
        entry_point="lib/a.dart",
    ))
    diff = ws.apply_bundle("r1", CodeBundle(files=[], entry_point="lib/a.dart", deleted_files=["lib/b.dart"]))
    assert "(deleted)" in diff
    assert not (tmp_path / "r1/lib/b.dart").exists()

    with pytest.raises(ValueError):
        ws.apply_bundle("r1", CodeBundle(
            files=[GeneratedFile(path="../../evil.txt", content="x")], entry_point="x"))
    with pytest.raises(ValueError):
        ws.apply_bundle("r1", CodeBundle(files=[], entry_point="x", deleted_files=["../r2/x"]))


def test_read_all_skips_build_and_native_dirs(tmp_path):
    ws = WorkspaceService(tmp_path)
    root = ws.path_for("r1")
    for rel in ["lib/main.dart", "build/out.txt", "android/app/build.gradle",
                "node_modules/x/index.js", ".dart_tool/cfg", "pubspec.lock"]:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x")
    assert list(ws.read_all("r1")) == ["lib/main.dart"]


def test_scaffold_is_noop_without_toolchain(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert WorkspaceService(tmp_path).scaffold("r1", "flutter", "com.a.b") is False
    assert WorkspaceService(tmp_path).scaffold("r1", "react-native", "com.a.b") is False


def test_fingerprint_ignores_tool_noise_before_error():
    a = error_fingerprint("analyze", "Analyzing app... 2.1s\nerror • Undefined name 'x' • lib/main.dart:3:5")
    b = error_fingerprint("analyze", "Analyzing app... 4.7s\nResolving deps\nerror • Undefined name 'x' • lib/main.dart:9:1")
    c = error_fingerprint("analyze", "Analyzing app... 2.1s\nerror • Undefined name 'y' • lib/main.dart:3:5")
    assert a == b
    assert a != c


def test_local_ci_installs_rn_deps_before_typecheck(tmp_path):
    from app_factory.services.ci import LocalCLIProvider

    steps = LocalCLIProvider()._steps("react-native", tmp_path)
    assert steps[0] == ("deps", ["npm", "install"])
    assert [name for name, _ in steps[1:]] == ["analyze", "test"]
