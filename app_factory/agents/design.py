"""UI/UX Agent: spec'ten design token'ları ve ekran tasarımları üretir."""

from app_factory.llm import LLMProvider
from app_factory.schemas.contracts import AppSpec, DesignSpec

SYSTEM = """Sen bir mobil UI/UX tasarımcısısın. Verilen spesifikasyon için
tutarlı bir tasarım sistemi üret. Kurallar:
- Renkler hex formatında, WCAG AA kontrast oranını sağlamalı.
- Her ekran için layout_description o kadar ayrıntılı olmalı ki bir geliştirici
  mockup görmeden ekranı birebir kodlayabilsin.
- Jenerik AI estetiğinden kaçın: Inter/Roboto ve mor gradyan kullanma; uygulamanın
  konusuna özgü karakterli bir palet ve tipografi seç.
- Kod yazma — yalnızca tasarım."""


class DesignAgent:
    def __init__(self, llm: LLMProvider, model: str):
        self.llm = llm
        self.model = model

    def run(self, spec: AppSpec) -> DesignSpec:
        return self.llm.structured(
            model=self.model,
            output_model=DesignSpec,
            system=SYSTEM,
            prompt=(
                f"Spesifikasyon:\n{spec.model_dump_json(indent=2)}\n\n"
                "Design token'ları ve her ekranın tasarımını üret."
            ),
        )
