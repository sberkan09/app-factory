"""Run kayıt defteri.

LangGraph checkpointer thread listesini dışarı vermediği için run listesi
küçük bir JSON dosyasında tutulur (workspace_root/runs.json). Canlı durum
(phase vb.) her sorguda graph state'inden okunur; burada yalnızca sabit
meta veriler durur.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class RunRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text())
        except json.JSONDecodeError:
            return []

    def add(self, run_id: str, idea: str, platform: str) -> None:
        with self._lock:
            runs = self._read()
            runs.insert(0, {
                "run_id": run_id,
                "idea": idea,
                "platform": platform,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            self.path.write_text(json.dumps(runs, ensure_ascii=False, indent=2))

    def list(self) -> list[dict]:
        with self._lock:
            return self._read()
