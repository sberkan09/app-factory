"""Coder Agent: spec + design'dan tüm kaynak kodu üretir; self-healing
döngüsünde hata raporlarını ve insan geri bildirimini işleyip patch üretir."""

from __future__ import annotations

import json

from app_factory.llm import LLMProvider
from app_factory.schemas.contracts import AppSpec, CodeBundle, DesignSpec, ErrorReport

SYSTEM = """Sen kıdemli bir mobil uygulama geliştiricisisin. Verilen
spesifikasyon ve tasarıma göre EKSİKSİZ, DERLENEBİLİR bir proje üret. Kurallar:
- Uygulama kodunu üret: pubspec.yaml/package.json, ana dosya, tüm ekranlar ve
  çekirdek mantık için en az bir unit test.
- Native platform klasörlerini (android/, ios/) ÜRETME; bunlar iskelet adımında
  resmi araçla (flutter create / create-expo-app) oluşturulur.
- Placeholder, TODO veya "..." bırakma; her dosya çalışır durumda olmalı.
- Yalnızca spesifikasyondaki özelliği kodla; ekstra özellik ekleme.
- Design token'larını birebir uygula (renkler, tipografi, spacing).
- Hata raporu verildiyse: başarısız önceki denemelere bak, AYNI yanlış çözümü
  tekrarlama; kök nedeni düzelt ve yalnızca değişen dosyaları döndür
  (değişmeyen dosyaları tekrar üretme). Gereksizleşen dosyaları deleted_files'a yaz."""

PLATFORM_NOTES = {
    "flutter": "Flutter (Dart, null-safety). Test dosyaları test/ altında, flutter_test ile.",
    "react-native": "React Native + Expo + TypeScript. Testler jest ile (__tests__/ altında).",
}


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
        app_id: str = "",
        error_report: ErrorReport | None = None,
        human_feedback: str | None = None,
        existing_files: dict[str, str] | None = None,
        fix_attempts: list[dict] | None = None,
        escalated: bool = False,
    ) -> CodeBundle:
        model = self.escalation_model if escalated else self.standard_model

        parts = [
            f"Platform: {PLATFORM_NOTES.get(spec.platform, spec.platform)}",
            f"Spesifikasyon:\n{spec.model_dump_json(indent=2)}",
            f"Tasarım:\n{design.model_dump_json(indent=2)}",
        ]
        if app_id:
            parts.append(
                f"Uygulama kimliği (applicationId / bundle id / Expo package): {app_id}"
            )
        if existing_files:
            parts.append("Mevcut proje dosyaları:\n" + json.dumps(existing_files, indent=2, ensure_ascii=False))
        if fix_attempts:
            attempts = "\n---\n".join(
                f"[deneme {a.get('iteration')}] hedeflenen hata: {a.get('error_summary', '')}\n{a.get('diff', '')}"
                for a in fix_attempts[-3:]
            )
            parts.append(
                "Bu hata turunda daha önce denenen ve BAŞARISIZ olan düzeltmeler "
                "(aynı yaklaşımı tekrarlama):\n" + attempts
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
