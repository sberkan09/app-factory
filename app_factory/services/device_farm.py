"""Ekran görüntüsü toplama sağlayıcıları (ARCHITECTURE.md §3.1).

- StubDeviceFarm: geliştirme/test için — screenshot üretmez, Visual QA
  "skipped" olarak geçer.
- MaestroCloudFarm: Maestro Cloud API entegrasyonu için iskelet; spec'teki
  ekran listesinden flow YAML üretir.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app_factory.schemas.contracts import AppSpec


@dataclass
class Screenshot:
    screen_name: str
    png_bytes: bytes


class DeviceFarmProvider(Protocol):
    def capture(self, workspace: Path, spec: AppSpec, artifact_path: str | None,
                app_id: str = "") -> list[Screenshot]: ...


class StubDeviceFarm:
    def capture(self, workspace: Path, spec: AppSpec, artifact_path: str | None,
                app_id: str = "") -> list[Screenshot]:
        return []


class MaestroCloudFarm:
    """Maestro Cloud üzerinden gerçek cihazda flow çalıştırıp screenshot toplar."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def generate_flow_yaml(self, spec: AppSpec, app_id: str) -> str:
        lines = [f"appId: {app_id or 'com.example.app'}", "---", "- launchApp"]
        for screen in spec.screens:
            lines.append(f"- takeScreenshot: {screen.name}")
            for target in screen.navigation_targets[:1]:
                lines.append(f"- tapOn: '{target}'")
        return "\n".join(lines)

    def capture(self, workspace: Path, spec: AppSpec, artifact_path: str | None,
                app_id: str = "") -> list[Screenshot]:
        if artifact_path is None:
            return []
        flow = self.generate_flow_yaml(spec, app_id)
        (workspace / "maestro_flow.yaml").write_text(flow)
        # Gerçek entegrasyon: `maestro cloud --apiKey ... <apk> maestro_flow.yaml`
        # çağrısı + sonuç API'sinden screenshot indirme. MVP'de flow dosyası
        # üretilir; capture boş döner (Visual QA skipped).
        return []


def make_device_farm(settings) -> DeviceFarmProvider:
    if settings.device_farm_provider == "maestro":
        import os

        return MaestroCloudFarm(api_key=os.environ.get("MAESTRO_API_KEY", ""))
    return StubDeviceFarm()
