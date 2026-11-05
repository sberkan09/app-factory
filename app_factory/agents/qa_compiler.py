"""QA/Compiler Agent: CI'ı çalıştırır, hatayı yapısal rapora çevirir.

Kod yazmaz/düzeltmez — yalnızca teşhis eder (ARCHITECTURE.md §1.1). Her
hatada kök neden analizi yapılır: ilk iterasyonlarda standart (ucuz) model,
inatçı hatalarda (eskalasyon) güçlü model kullanılır.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app_factory.llm import LLMProvider
from app_factory.schemas.contracts import BuildResult, ErrorAnalysis
from app_factory.services.ci import CIProvider

log = logging.getLogger(__name__)

ANALYSIS_SYSTEM = """Sen bir derleme hatası analiz uzmanısın. Verilen ham hata
çıktısından kök nedeni ve düzeltme stratejisini çıkar. Kod yazma — yalnızca
teşhis. Düzeltme stratejisi somut ve tek cümlelik olsun; etkilenen dosyaları
proje köküne göre yollarla listele."""


class QACompilerAgent:
    def __init__(self, ci: CIProvider, llm: LLMProvider | None, analysis_model: str,
                 escalation_model: str | None = None):
        self.ci = ci
        self.llm = llm
        self.analysis_model = analysis_model
        self.escalation_model = escalation_model or analysis_model

    def run(self, workspace: Path, platform: str, iteration: int, *, escalated: bool = False,
            analyze_with_llm: bool = True) -> BuildResult:
        result = self.ci.run_checks(workspace, platform, iteration)
        if result.status == "failure" and result.error_report and analyze_with_llm and self.llm:
            model = self.escalation_model if escalated else self.analysis_model
            try:
                result.error_report.analysis = self.llm.structured(
                    model=model,
                    output_model=ErrorAnalysis,
                    system=ANALYSIS_SYSTEM,
                    prompt=f"Hata çıktısı ({result.step} adımı):\n{result.error_report.raw_output}",
                    max_tokens=8000,
                )
            except Exception as exc:  # analiz opsiyoneldir; ham rapor yine de coder'a gider
                log.warning("Error analysis failed: %s", exc)
        return result
