"""Coder Agent: spec + design'dan tüm kaynak kodu üretir; self-healing
döngüsünde hata raporlarını ve insan geri bildirimini işleyip patch üretir."""

from __future__ import annotations

import json

from app_factory.llm import LLMProvider
from app_factory.schemas.contracts import AppSpec, CodeBundle, DesignSpec, ErrorReport

SYSTEM = """Sen kıdemli bir mobil uygulama geliştiricisisin. Verilen
spesifikasyon ve tasarıma göre EKSİKSİZ, DERLENEBİLİR bir proje üret. Kurallar:
- Tüm dosyaları üret: pubspec.yaml/package.json dahil, main dosya, tüm ekranlar.
- Placeholder, TODO veya "..." bırakma; her dosya çalışır durumda olmalı.
- Yalnızca spesifikasyondaki özelliği kodla; ekstra özellik ekleme.
- Design token'larını birebir uygula (renkler, tipografi, spacing).
- Hata raporu verildiyse: önceki denemelerin diff geçmişine bak, AYNI yanlış
  çözümü tekrarlama; kök nedeni düzelt ve yalnızca değişen dosyaları döndür
  (değişmeyen dosyaları tekrar üretme)."""


class CoderAgent:
    def __init__(self, llm: LLMProvider, standard_model: str, escalation_model: str):
        self.llm = llm
        self.standard_model = standard_model
        self.escalation_model = escalation_model

    def run(
        self,
        spec: AppSpec,
        design: DesignSpec,
        *,
        error_report: ErrorReport | None = None,
        human_feedback: str | None = None,
        existing_files: dict[str, str] | None = None,
        diff_history: list[str] | None = None,
        escalated: bool = False,
    ) -> CodeBundle:
        model = self.escalation_model if escalated else self.standard_model

        parts = [
            f"Spesifikasyon:\n{spec.model_dump_json(indent=2)}",
            f"Tasarım:\n{design.model_dump_json(indent=2)}",
        ]
        if existing_files:
            parts.append("Mevcut proje dosyaları:\n" + json.dumps(existing_files, indent=2))
        if diff_history:
            parts.append(
                "Önceki düzeltme denemelerinin diff'leri (bunlar İŞE YARAMADI, "
                "aynı yaklaşımı tekrarlama):\n" + "\n---\n".join(diff_history[-3:])
            )
        if error_report is not None:
            parts.append(
                "DÜZELTİLECEK HATA RAPORU:\n" + error_report.model_dump_json(indent=2)
                + "\nKök nedeni düzelt; yalnızca değişen dosyaları döndür."
            )
        if human_feedback:
            parts.append(f"İNSAN GERİ BİLDİRİMİ (öncelikli gereksinim):\n{human_feedback}")
        if error_report is None and not human_feedback:
            parts.append("Projeyi sıfırdan, eksiksiz üret.")

        return self.llm.structured(
            model=model,
            output_model=CodeBundle,
            system=SYSTEM,
            prompt="\n\n".join(parts),
            max_tokens=64000,
        )
