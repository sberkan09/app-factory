"""Visual Reviewer Agent: ekran görüntülerini tasarım spesifikasyonuyla
multi-modal karşılaştırır (ARCHITECTURE.md §3)."""

from __future__ import annotations

from app_factory.llm import LLMProvider
from app_factory.schemas.contracts import DesignSpec, VisualQAReport
from app_factory.services.device_farm import Screenshot

SYSTEM = """Sen bir görsel QA uzmanısın. Verilen ekran görüntülerini tasarım
spesifikasyonuyla karşılaştır. Şunları denetle: buton/metin taşması, hizalama
bozukluğu, renk uyumsuzluğu, kırpılmış metin, yetersiz kontrast. Her sorunu
severity ile raporla: blocker (kullanımı engelliyor), major (belirgin bozukluk),
minor (kozmetik). Kod önerme — yalnızca bulgu raporla."""


class VisualReviewerAgent:
    def __init__(self, llm: LLMProvider, model: str):
        self.llm = llm
        self.model = model

    def run(self, design: DesignSpec, screenshots: list[Screenshot]) -> VisualQAReport:
        if not screenshots:
            return VisualQAReport(
                verdict="skipped",
                summary="Ekran görüntüsü alınamadı (device farm yapılandırılmamış); görsel QA atlandı.",
            )
        screen_names = ", ".join(s.screen_name for s in screenshots)
        return self.llm.structured(
            model=self.model,
            output_model=VisualQAReport,
            system=SYSTEM,
            prompt=(
                f"Tasarım spesifikasyonu:\n{design.model_dump_json(indent=2)}\n\n"
                f"Ekteki ekran görüntüleri sırasıyla şu ekranlara ait: {screen_names}.\n"
                "Görsel sorunları raporla; sorun yoksa verdict=pass döndür."
            ),
            images=[s.png_bytes for s in screenshots],
        )
