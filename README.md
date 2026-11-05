# App Factory 🏭

Otonom mobil uygulama fabrikası — fikirden Play Store'a kadar insan müdahalesini tek bir **Onayla/Reddet** kararına indirgeyen çoklu-ajan pipeline'ı. Mimari detaylar: [ARCHITECTURE.md](./ARCHITECTURE.md).

## Akış

```
Idea → Spec → UI/UX → Coder → QA/Compiler ⟲ (self-healing) → Visual QA ⟲ → Release → [ONAY] → Deploy
```

- **Self-healing:** Derleme hatası fingerprint'lenip Coder'a geri beslenir; aynı hata 2. kez görülürse veya 5 iterasyon dolarsa circuit breaker keser ve insana devreder.
- **Model eskalasyonu:** Her derleme hatası QA ajanınca analiz edilir; ilk 2 deneme `claude-sonnet-5-5`, inatçı hatalarda `claude-opus-5-5` (veya `claude-fable-5-1`).
- **Başarısız deneme bağlamı:** Coder'a yalnızca *mevcut hata turundaki başarısız* düzeltme diff'leri "bunu zaten denedin" diye verilir; build geçince bağlam sıfırlanır.
- **Human gate:** LangGraph `interrupt()` — graf checkpoint'te bekler, panel üzerinden approve/reject ile devam eder. Breaker sonrası (sürüm adayı yokken) onay engellenir; yorumla reddetmek yeni bir tur başlatır.
- **Dayanıklılık:** Bir ajan çağrısı hata verirse run "takılı" kalmaz: hata panelde görünür, `POST /runs/{id}/retry` son checkpoint'ten devam ettirir (sunucu yeniden başlasa bile).
- **Maliyet takibi:** Her LLM çağrısının token kullanımı ve tahmini maliyeti run state'ine yazılır, panelde model bazında görünür.
- **Uygulama kimliği:** `applicationId` (`AF_APP_ID_PREFIX` + slug) spec'ten türetilir; Coder, Maestro flow'u ve Play Console dağıtımı aynı kimliği kullanır.

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
| `POST /runs/{id}/reject` `{"feedback": "..."}` | Yorumla reddet → Coder'a geri döner (boş yorum: run'ı sonlandırır) |
| `POST /runs/{id}/retry` | Hata alan / yarıda kalan run'ı son checkpoint'ten sürdür |
| `GET /panel` | Minimal onay paneli (HTML) |

## Testler

```bash
./.venv/bin/python -m pytest
```

Testler gerçek API çağrısı yapmaz (FakeLLM + StubCI); self-healing döngüsü, circuit breaker, eskalasyon, human gate, görsel QA geri dönüşü, API hata/retry akışı ve maliyet takibi uçtan uca doğrulanır.

## Sağlayıcılar (config ile seçilir)

| Katman | Varsayılan | Alternatifler |
|---|---|---|
| CI/derleme | `local` (flutter/npx varsa) | `github` (Actions workflow_dispatch), `stub` |
| Device farm | `stub` (görsel QA atlanır) | `maestro` (Maestro Cloud iskeleti) |
| Dağıtım | `stub` | `play_console` (fastlane supply → internal track) |
| Checkpointer | SQLite (`app_factory.sqlite`) | Postgres'e geçiş: `langgraph-checkpoint-postgres` |
| Native iskelet | `flutter create` (flutter kuruluysa) | RN: Expo managed — EAS Build prebuild yapar |

## Proje yapısı

```
app_factory/
├── config.py            # Ayarlar (AF_* env)
├── schemas/             # Ajanlar arası Pydantic kontratları + PipelineState
├── llm/client.py        # Anthropic structured-output katmanı (büyük çıktılarda streaming)
├── llm/usage.py         # Token/maliyet takibi
├── agents/              # Idea, Spec, Design, Coder, QA, Visual Reviewer
├── services/            # workspace, ci, device_farm, pixel_diff, deployment
├── graph/               # LangGraph node/edge kurulumu + circuit breaker routing
├── api/runs.py          # REST API + onay paneli
└── main.py              # Dependency wiring + FastAPI
```

## Sonraki adımlar

1. GitHub Actions entegrasyonunda workspace'i otomatik branch'e commit/push etme (şu an workflow `AF_GITHUB_REF` branch'ini derler)
2. Maestro Cloud gerçek screenshot toplama + `pixel_diff` ön filtre bağlantısı — bunun için UI/UX ajanının metin tasarımın yanında **referans mockup görseli** üretmesi gerekir (ör. tasarım token'larıyla render edilen HTML mockup → screenshot); şu an karşılaştırma yalnızca metin spesifikasyona karşı
3. Idea Agent'a `web_search` server tool'u ile gerçek pazar/rakip taraması
4. Altyapı hatalarını (CI dispatch, timeout) kod hatalarından ayırıp Coder'a göndermeden doğrudan insana/yeniden denemeye yönlendirme
5. Release build: imzalı `flutter build appbundle --release` (CI secret store'daki anahtarla) — yerel sağlayıcı şimdilik debug APK üretir
6. Postgres checkpointer + Temporal ile durable execution; Next.js onay paneli
