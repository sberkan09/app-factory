"""Dağıtım sağlayıcıları (ARCHITECTURE.md §5.2).

- StubDeployment: geliştirme için — dağıtımı loglar.
- PlayConsoleDeployment: fastlane supply ile Google Play Internal Testing'e
  yükleme. İlk dağıtım her zaman internal track'e gider.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Protocol

from app_factory.schemas.contracts import ReleaseCandidate


class DeploymentProvider(Protocol):
    def deploy(self, rc: ReleaseCandidate) -> str: ...


class StubDeployment:
    def deploy(self, rc: ReleaseCandidate) -> str:
        return f"[stub] {rc.app_name} v{rc.version} internal track'e yüklendi (artifact: {rc.artifact_path})"


class PlayConsoleDeployment:
    """`fastlane supply` üzerinden Google Play Developer API (androidpublisher v3)."""

    def __init__(self, package_name: str, json_key_path: str, track: str = "internal"):
        self.package_name = package_name
        self.json_key_path = json_key_path
        self.track = track

    def deploy(self, rc: ReleaseCandidate) -> str:
        if rc.artifact_path is None:
            raise ValueError("Release candidate has no artifact to deploy")
        if shutil.which("fastlane") is None:
            raise RuntimeError("fastlane is not installed")
        proc = subprocess.run(
            [
                "fastlane", "supply",
                "--package_name", self.package_name,
                "--json_key", self.json_key_path,
                "--track", self.track,
                "--aab" if rc.artifact_path.endswith(".aab") else "--apk", rc.artifact_path,
            ],
            capture_output=True, text=True, timeout=1800,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"fastlane supply failed: {proc.stderr[-2000:]}")
        return f"{rc.app_name} v{rc.version} -> Play Console ({self.track} track)"


def make_deployment_provider(settings) -> DeploymentProvider:
    if settings.deployment_provider == "play_console":
        import os

        return PlayConsoleDeployment(
            package_name=os.environ.get("PLAY_PACKAGE_NAME", ""),
            json_key_path=os.environ.get("PLAY_JSON_KEY", ""),
        )
    return StubDeployment()
