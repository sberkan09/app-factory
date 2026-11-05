"""Run başına izole çalışma dizini yönetimi.

Her run kendi dizininde çalışır (paralel run'lar çakışmaz). Her coder
iterasyonunda önceki içerikle unified diff üretilir — denetim izi ve
"bunu zaten denedin" bağlamı için (ARCHITECTURE.md §2.2).
"""

from __future__ import annotations

import difflib
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

from app_factory.schemas.contracts import CodeBundle

# Coder'a bağlam olarak gönderilmeyen / panelde listelenmeyen yollar:
# derleme çıktıları, bağımlılık klasörleri ve iskeletin ürettiği native kod.
IGNORED_DIRS = {
    "build", "node_modules", "Pods", "android", "ios", "web", "linux", "macos", "windows",
}
IGNORED_FILES = {"pubspec.lock", "package-lock.json", "yarn.lock", "app-release.stub.apk"}
MAX_FILE_BYTES = 100_000


def app_slug(app_name: str) -> str:
    """'Su Takip!' -> 'su_takip' (Dart paket adı ve applicationId parçası olarak geçerli)."""
    ascii_name = (
        unicodedata.normalize("NFKD", app_name.replace("ı", "i").replace("İ", "I"))
        .encode("ascii", "ignore")
        .decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = f"app_{slug}" if slug else "app"
    return slug[:40]


def make_app_id(prefix: str, app_name: str) -> str:
    return f"{prefix.rstrip('.')}.{app_slug(app_name)}"


def is_ignored(rel: Path) -> bool:
    parts = rel.parts
    if any(p.startswith(".") for p in parts):
        return True
    if parts and parts[0] in IGNORED_DIRS:
        return True
    return rel.name in IGNORED_FILES


class WorkspaceService:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, run_id: str) -> Path:
        p = self.root / run_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _safe_target(self, workspace: Path, rel_path: str) -> Path:
        target = (workspace / rel_path).resolve()
        if not target.is_relative_to(workspace.resolve()):
            raise ValueError(f"Path escapes workspace: {rel_path}")
        return target

    def scaffold(self, run_id: str, platform: str, app_id: str) -> bool:
        """Native platform iskeletini resmi araçla kurar.

        - Flutter: `flutter create` (android/ios klasörleri + doğru applicationId).
          Varsayılan sayaç testi silinir; uygulama kodunu Coder üretir.
        - React Native: Expo managed workflow native klasör gerektirmez
          (EAS Build prebuild yapar); iskelet adımı yok.
        Araç kurulu değilse False döner (CI tarafında iskelet kurulur).
        """
        workspace = self.path_for(run_id)
        if platform != "flutter" or shutil.which("flutter") is None:
            return False
        org, _, name = app_id.rpartition(".")
        proc = subprocess.run(
            ["flutter", "create", "--org", org, "--project-name", name,
             "--platforms", "android,ios", "."],
            cwd=workspace, capture_output=True, text=True, timeout=600,
        )
        if proc.returncode != 0:
            return False
        default_test = workspace / "test" / "widget_test.dart"
        if default_test.exists():
            default_test.unlink()
        return True

    def apply_bundle(self, run_id: str, bundle: CodeBundle) -> str:
        """Dosyaları yazar/siler; önceki içerikle unified diff döndürür."""
        workspace = self.path_for(run_id)
        diff_chunks: list[str] = []
        for f in bundle.files:
            target = self._safe_target(workspace, f.path)
            old = target.read_text() if target.exists() else ""
            if old != f.content:
                diff = difflib.unified_diff(
                    old.splitlines(keepends=True),
                    f.content.splitlines(keepends=True),
                    fromfile=f"a/{f.path}",
                    tofile=f"b/{f.path}",
                )
                diff_chunks.append("".join(diff))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.content)
        for rel in bundle.deleted_files:
            target = self._safe_target(workspace, rel)
            if target.is_file():
                diff_chunks.append(f"--- a/{rel}\n+++ /dev/null\n(deleted)\n")
                target.unlink()
        return "\n".join(diff_chunks)

    def iter_files(self, run_id: str):
        workspace = self.path_for(run_id)
        for p in sorted(workspace.rglob("*")):
            rel = p.relative_to(workspace)
            if p.is_file() and not is_ignored(rel):
                yield rel, p

    def read_all(self, run_id: str, max_bytes: int = 400_000) -> dict[str, str]:
        """Mevcut kaynak dosyaları oku (coder'a bağlam olarak verilir).

        Büyük/ikili dosyalar atlanır; toplam bütçe aşılırsa kalan dosyalar
        bağlama eklenmez (ilk kaynak dosyalar öncelikli).
        """
        out: dict[str, str] = {}
        total = 0
        for rel, p in self.iter_files(run_id):
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            try:
                text = p.read_text()
            except UnicodeDecodeError:
                continue
            if total + len(text) > max_bytes:
                continue
            total += len(text)
            out[str(rel)] = text
        return out
