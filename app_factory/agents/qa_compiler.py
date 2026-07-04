"""QA/Compiler Agent: CI'ı çalıştırır, hatayı yapısal rapora çevirir.

Kod yazmaz/düzeltmez — yalnızca teşhis eder (ARCHITECTURE.md §1.1). İnatçı
hatalarda (escalation) kök neden analizi için güçlü model kullanılır.
"""

from __future__ import annotations

from pathlib import Path

from app_factory.llm import LLMProvider
from app_factory.schemas.contracts import BuildResult, ErrorAnalysis
from app_factory.services.ci import CIProvider

ANALYSIS_SYSTEM = """Sen bir derleme hatası analiz uzmanısın. Verilen ham hata
çıktısından kök nedeni ve düzeltme stratejisini çıkar. Kod yazma — yalnızca
teşhis. Düzeltme stratejisi somut ve tek cümlelik olsun."""


class QACompilerAgent:
    def __init__(self, ci: CIProvider, llm: LLMProvider | None, analysis_model: str):
        self.ci = ci
        self.llm = llm
        self.analysis_model = analysis_model

    def run(self, workspace: Path, platform: str, iteration: int, *, analyze_with_llm: bool) -> BuildResult:
        result = self.ci.run_checks(workspace, platform, iteration)
        if result.status == "failure" and result.error_report and analyze_with_llm and self.llm:
            try:
                result.error_report.analysis = self.llm.structured(
                    model=self.analysis_model,
                    output_model=ErrorAnalysis,
                    system=ANALYSIS_SYSTEM,
                    prompt=f"Hata çıktısı ({result.step} adımı):\n{result.error_report.raw_output}",
                    max_tokens=4000,
                )
            except Exception:
                pass  # analiz opsiyoneldir; ham rapor yine de coder'a gider
        return result
