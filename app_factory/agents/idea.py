"""Idea Agent: ham fikri single-feature bir uygulama konseptine daraltır."""

from app_factory.llm import LLMProvider
from app_factory.schemas.contracts import AppConcept

SYSTEM = """Sen bir mobil uygulama ürün stratejistisin. Görevin, verilen ham
fikri TEK ÇEKİRDEK ÖZELLİKLİ (single-feature) bir mikro uygulama konseptine
daraltmak. Kurallar:
- core_feature tek bir cümle olmalı ve tek bir kullanıcı eylemini tarif etmeli.
- Kapsamı asla genişletme: login, profil, ayarlar, sosyal özellikler ekleme —
  yalnızca çekirdek özellik.
- app_name kısa ve mağaza-uyumlu olmalı."""


class IdeaAgent:
    def __init__(self, llm: LLMProvider, model: str):
        self.llm = llm
        self.model = model

    def run(self, idea_prompt: str) -> AppConcept:
        return self.llm.structured(
            model=self.model,
            output_model=AppConcept,
            system=SYSTEM,
            prompt=f"Ham fikir: {idea_prompt}\n\nBunu single-feature bir konsepte dönüştür.",
        )
