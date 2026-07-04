"""Spec Agent: konsepti teknik gereksinime çevirir (ekranlar, veri modeli)."""

from app_factory.llm import LLMProvider
from app_factory.schemas.contracts import AppConcept, AppSpec

SYSTEM = """Sen bir mobil uygulama teknik analistisin. Verilen konsepti
uygulanabilir bir teknik spesifikasyona çevir. Kurallar:
- En fazla 3 ekran (single-feature kısıtı).
- Veri modeli minimal olmalı; yalnızca çekirdek özelliğin ihtiyaç duyduğu
  entity'ler.
- Harici API yalnızca gerçekten zorunluysa ekle.
- Görsel tasarım yapma, kod yazma — yalnızca spesifikasyon."""


class SpecAgent:
    def __init__(self, llm: LLMProvider, model: str):
        self.llm = llm
        self.model = model

    def run(self, concept: AppConcept, platform: str) -> AppSpec:
        return self.llm.structured(
            model=self.model,
            output_model=AppSpec,
            system=SYSTEM,
            prompt=(
                f"Konsept:\n{concept.model_dump_json(indent=2)}\n\n"
                f"Hedef platform: {platform}\n"
                "Teknik spesifikasyonu üret."
            ),
        )
