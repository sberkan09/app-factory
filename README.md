# App Factory 🏭

Otonom mobil uygulama fabrikası — fikirden Play Store'a kadar insan müdahalesini tek bir **Onayla/Reddet** kararına indirgeyen çoklu-ajan pipeline'ı. Mimari detaylar: [ARCHITECTURE.md](./ARCHITECTURE.md).

## Akış

```
Idea → Spec → UI/UX → Coder → QA/Compiler ⟲ (self-healing) → Visual QA ⟲ → Release → [ONAY] → Deploy
```

- **Self-healing:** Derleme hatası fingerprint'lenip Coder'a geri beslenir; aynı hata 2. kez görülürse veya 5 iterasyon dolarsa circuit breaker keser ve insana devreder.
- **Model eskalasyonu:** İlk 2 düzeltme denemesi `claude-sonnet-5`, sonrası `claude-opus-4-8` (veya `claude-fable-5`).
- **Human gate:** LangGraph `interrupt()` — graf checkpoint'te bekler, panel üzerinden approve/reject ile devam eder.

## Kurulum

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # ANTHROPIC_API_KEY doldur (veya `ant auth login`)
```

## Çalıştırma

```bash
./.venv/bin/uvicorn app_factory.main:app --reload
# Onay paneli: http://localhost:8000/panel
```

API:

| Endpoint | Açıklama |
|---|---|
| `POST /runs` `{"idea": "...", "platform": "flutter"}` | Yeni pipeline başlat |
| `GET /runs/{id}` | Durum sorgula |
| `POST /runs/{id}/approve` | Onayla → deploy tetiklenir |
| `POST /runs/{id}/reject` `{"feedback": "..."}` | Yorumla reddet → Coder'a geri döner |
| `GET /panel` | Minimal onay paneli (HTML) |

## Testler

```bash
./.venv/bin/python -m pytest
```

Testler gerçek API çağrısı yapmaz (FakeLLM + StubCI); self-healing döngüsü, circuit breaker, eskalasyon, human gate ve görsel QA geri dönüşü uçtan uca doğrulanır.

## Sağlayıcılar (config ile seçilir)

| Katman | Varsayılan | Alternatifler |
|---|---|---|
| CI/derleme | `local` (flutter/npx varsa) | `github` (Actions workflow_dispatch), `stub` |
| Device farm | `stub` (görsel QA atlanır) | `maestro` (Maestro Cloud iskeleti) |
| Dağıtım | `stub` | `play_console` (fastlane supply → internal track) |
| Checkpointer | SQLite (`app_factory.sqlite`) | Postgres'e geçiş: `langgraph-checkpoint-postgres` |

## Proje yapısı

```
app_factory/
├── config.py            # Ayarlar (AF_* env)
├── schemas/             # Ajanlar arası Pydantic kontratları + PipelineState
├── llm/client.py        # Anthropic structured-output katmanı
├── agents/              # Idea, Spec, Design, Coder, QA, Visual Reviewer
├── services/            # workspace, ci, device_farm, pixel_diff, deployment
├── graph/               # LangGraph node/edge kurulumu + circuit breaker routing
├── api/runs.py          # REST API + onay paneli
└── main.py              # Dependency wiring + FastAPI
```

## Sonraki adımlar

1. GitHub Actions entegrasyonunda workspace'i otomatik branch'e commit/push etme
2. Maestro Cloud gerçek screenshot toplama + `pixel_diff` ön filtre bağlantısı
3. Postgres checkpointer + Temporal ile durable execution
4. Next.js onay paneli (mevcut HTML panelin yerine)
