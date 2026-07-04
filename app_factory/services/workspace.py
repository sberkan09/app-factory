"""Run başına izole çalışma dizini yönetimi.

Her run kendi dizininde çalışır (paralel run'lar çakışmaz). Her coder
iterasyonunda önceki içerikle unified diff üretilir — denetim izi ve
"bunu zaten denedin" bağlamı için (ARCHITECTURE.md §2.2).
"""

from __future__ import annotations

import difflib
from pathlib import Path

from app_factory.schemas.contracts import CodeBundle


class WorkspaceService:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, run_id: str) -> Path:
        p = self.root / run_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def apply_bundle(self, run_id: str, bundle: CodeBundle) -> str:
        """Dosyaları yazar; önceki içerikle unified diff döndürür."""
        workspace = self.path_for(run_id)
        diff_chunks: list[str] = []
        for f in bundle.files:
            target = (workspace / f.path).resolve()
            if not str(target).startswith(str(workspace.resolve())):
                raise ValueError(f"Path escapes workspace: {f.path}")
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
        return "\n".join(diff_chunks)

    def read_all(self, run_id: str, max_bytes: int = 400_000) -> dict[str, str]:
        """Mevcut kaynak dosyaları oku (coder'a bağlam olarak verilir)."""
        workspace = self.path_for(run_id)
        out: dict[str, str] = {}
        total = 0
        for p in sorted(workspace.rglob("*")):
            if not p.is_file() or any(part.startswith(".") for part in p.parts):
                continue
            try:
                text = p.read_text()
            except UnicodeDecodeError:
                continue
            total += len(text)
            if total > max_bytes:
                break
            out[str(p.relative_to(workspace))] = text
        return out
