"""Derleme/test sağlayıcıları (ARCHITECTURE.md §2.1).

Fail-fast sırası: statik analiz -> unit test -> derleme. Ucuz kontroller önce
çalışır ki LLM iterasyonu başına maliyet düşük kalsın.

- LocalCLIProvider: makinede flutter/node varsa gerçek komutları çalıştırır.
- GitHubActionsCI: workflow_dispatch ile cloud derleme tetikler, sonucu poll eder.
- StubCI: test/geliştirme için programlanabilir sahte sağlayıcı.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Protocol

from app_factory.schemas.contracts import BuildResult, ErrorReport


def error_fingerprint(step: str, raw_output: str) -> str:
    """Hata çıktısından kararlı bir hash üret (döngü tespiti için).

    Satır numaraları/geçici yollar değişse de aynı hatanın aynı hash'i
    üretmesi için çıktı normalize edilir.
    """
    lines = [l.strip() for l in raw_output.splitlines() if l.strip()]
    # Araç gürültüsünü ("Analyzing...", "Resolving dependencies...") atlamak için
    # önce hata satırlarına odaklan; yoksa ilk satırlara düş.
    error_lines = [l for l in lines if _ERROR_LINE.search(l)]
    significant = " ".join((error_lines or lines)[:5])
    normalized = re.sub(r"(?:[A-Za-z]:)?[/\\][^\s:]+[/\\]", "/PATH/", significant)
    normalized = re.sub(r"\d+", "N", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return hashlib.sha256(f"{step}:{normalized}".encode()).hexdigest()[:16]


_ERROR_LINE = re.compile(r"\berror\b|\bexception\b|\bfailed\b|^E\s", re.IGNORECASE)


def _classify(step: str) -> str:
    return {
        "analyze": "lint_error",
        "test": "test_failure",
        "build": "compile_error",
    }.get(step, "tooling_error")


def make_failure(step: str, stdout: str, stderr: str, iteration: int) -> BuildResult:
    raw = (stderr or "") + "\n" + (stdout or "")
    return BuildResult(
        status="failure",
        step=step,
        stdout=stdout[-8000:],
        stderr=stderr[-8000:],
        error_report=ErrorReport(
            iteration=iteration,
            error_type=_classify(step),
            step=step,
            raw_output=raw.strip()[-8000:],
            fingerprint=error_fingerprint(step, raw),
        ),
    )


class CIProvider(Protocol):
    def run_checks(self, workspace: Path, platform: str, iteration: int) -> BuildResult: ...

    def build_artifact(self, workspace: Path, platform: str) -> str | None: ...


class LocalCLIProvider:
    """Yerelde kurulu CLI araçlarıyla derleme. Araç yoksa adım atlanır."""

    def run_checks(self, workspace: Path, platform: str, iteration: int) -> BuildResult:
        steps = self._steps(platform, workspace)
        ran_any = False
        for step_name, cmd in steps:
            if shutil.which(cmd[0]) is None:
                continue
            ran_any = True
            proc = subprocess.run(
                cmd, cwd=workspace, capture_output=True, text=True, timeout=600
            )
            if proc.returncode != 0:
                return make_failure(step_name, proc.stdout, proc.stderr, iteration)
        if not ran_any:
            return BuildResult(status="skipped", step="analyze",
                               stdout="No local toolchain found; checks skipped.")
        return BuildResult(status="success", step="build")

    def _steps(self, platform: str, workspace: Path) -> list[tuple[str, list[str]]]:
        if platform == "flutter":
            steps = [
                ("deps", ["flutter", "pub", "get"]),
                ("analyze", ["flutter", "analyze", "--no-pub"]),
            ]
            if (workspace / "test").is_dir():
                steps.append(("test", ["flutter", "test"]))
            return steps
        return [
            ("deps", ["npm", "install"]),
            ("analyze", ["npx", "tsc", "--noEmit"]),
            ("test", ["npx", "jest", "--passWithNoTests"]),
        ]

    def build_artifact(self, workspace: Path, platform: str) -> str | None:
        if platform == "flutter" and shutil.which("flutter"):
            proc = subprocess.run(
                ["flutter", "build", "apk", "--debug"],
                cwd=workspace, capture_output=True, text=True, timeout=1800,
            )
            if proc.returncode == 0:
                apk = workspace / "build/app/outputs/flutter-apk/app-debug.apk"
                return str(apk) if apk.exists() else None
        return None


class GitHubActionsCI:
    """GitHub Actions'ı workflow_dispatch ile tetikleyip sonucu poll eder."""

    def __init__(self, token: str, repo: str, workflow: str, poll_interval: int = 20,
                 timeout_s: int = 1800, ref: str = "main"):
        self.ref = ref
        self.token = token
        self.repo = repo
        self.workflow = workflow
        self.poll_interval = poll_interval
        self.timeout_s = timeout_s

    def _client(self):
        import httpx

        return httpx.Client(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=30,
        )

    def run_checks(self, workspace: Path, platform: str, iteration: int) -> BuildResult:
        # Not: workspace'in bir branch'e push edilmiş olması beklenir; orkestratör
        # commit/push'u yapar. Burada workflow tetiklenir ve sonuç beklenir.
        with self._client() as http:
            # Dispatch'ten hemen önceki an: yalnızca bundan sonra oluşturulan
            # run'ları kabul et (önceki/başka run'ı yanlışlıkla okumamak için).
            dispatched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5))
            resp = http.post(
                f"/repos/{self.repo}/actions/workflows/{self.workflow}/dispatches",
                json={"ref": self.ref, "inputs": {"platform": platform}},
            )
            if resp.status_code >= 300:
                return make_failure("tooling", "", f"workflow_dispatch failed: {resp.text}", iteration)

            deadline = time.time() + self.timeout_s
            while time.time() < deadline:
                time.sleep(self.poll_interval)
                runs = http.get(
                    f"/repos/{self.repo}/actions/workflows/{self.workflow}/runs",
                    params={"per_page": 1, "event": "workflow_dispatch",
                            "branch": self.ref, "created": f">={dispatched_at}"},
                ).json()
                if not runs.get("workflow_runs"):
                    continue
                run = runs["workflow_runs"][0]
                run_id = run["id"]
                if run["status"] == "completed":
                    if run["conclusion"] == "success":
                        return BuildResult(status="success", step="build")
                    logs = f"GitHub Actions run {run_id} concluded: {run['conclusion']}"
                    return make_failure("build", "", logs, iteration)
            return make_failure("build", "", f"CI timeout after {self.timeout_s}s", iteration)

    def build_artifact(self, workspace: Path, platform: str) -> str | None:
        return None  # artifact indirimi: run artifacts API'siyle genişletilebilir


class StubCI:
    """Testler için: ilk `fail_times` çağrıda verilen hatayı döndürür."""

    def __init__(self, fail_times: int = 0, failure_output: str = "Error: something broke",
                 failure_outputs: list[str] | None = None):
        self.fail_times = fail_times
        self.failure_output = failure_output
        self.failure_outputs = failure_outputs
        self.calls = 0

    def run_checks(self, workspace: Path, platform: str, iteration: int) -> BuildResult:
        self.calls += 1
        if self.calls <= self.fail_times:
            if self.failure_outputs:
                output = self.failure_outputs[min(self.calls - 1, len(self.failure_outputs) - 1)]
            else:
                output = self.failure_output
            return make_failure("build", "", output, iteration)
        return BuildResult(status="success", step="build")

    def build_artifact(self, workspace: Path, platform: str) -> str | None:
        artifact = workspace / "app-release.stub.apk"
        artifact.write_text("stub artifact")
        return str(artifact)


def make_ci_provider(settings) -> CIProvider:
    if settings.ci_provider == "github":
        return GitHubActionsCI(settings.github_token, settings.github_repo, settings.github_workflow,
                               ref=settings.github_ref)
    if settings.ci_provider == "stub":
        return StubCI()
    return LocalCLIProvider()
