# Otonom Mobil Uygulama Fabrikası — Sistem Mimarisi v1.0

> Amaç: Fikirden Play Store'a kadar, insan müdahalesini tek bir "Onayla/Reddet" kararına indirgeyen, kendi kendini iyileştiren (self-healing) çoklu-ajan mimarisi. Tamamen cloud API + cloud CI/CD üzerinde çalışır, lokal GPU/donanım gerektirmez.

---

## 0. Üst Seviye Akış (Özet)

```
[Idea Agent] -> [Spec Agent] -> [UI/UX Agent] -> [Coder Agent] <-> [QA/Compiler Agent (self-heal loop)]
                                                        |
                                                        v
                                            [Visual Reviewer Agent (multi-modal, self-heal loop)]
                                                        |
                                                        v
                                            [Release Candidate Builder]
                                                        |
                                                        v
                                        [Human Approval Panel]  <-- SADECE BURADA insan var
                                                        |
                                                 onay ---+--- red (yorumla)
                                                        |            |
                                                        v            v
                                        [Deployment Agent]    [Coder Agent'a geri besleme]
                                                        |
                                                        v
                                  Google Play Console API / App Store Connect API
```

Tüm graf **LangGraph** üzerinde `StateGraph` olarak modellenir; her düğüm state'i okur/yazar, `Postgres` tabanlı `checkpointer` ile her adım kalıcı hale getirilir (crash-safe, resumable). Bu sayede bir ajan çöktüğünde veya cloud runner zaman aşımına uğradığında iş kaldığı yerden devam eder.

---

## 1. Multi-Agent Pipeline & State Management

### 1.1 Ajan Tanımları

| Ajan | Model | Rol | Sınırlar (Kesinlikle Yapmaz) |
|---|---|---|---|
| **Idea Agent** | Claude Sonnet 5 | Kullanıcıdan gelen ham fikri (1 cümle bile olabilir) alır, pazar/rakip taraması yapar (WebSearch tool), "Single-Feature" ilkesine uyacak şekilde fikri daraltır. Çıktısı: `AppConcept` JSON. | Kod yazmaz, UI tasarlamaz, kapsamı genişletemez (max 1 core feature kuralı hard-coded). |
| **Spec Agent** | Claude Sonnet 5 | `AppConcept`'i teknik gereksinime çevirir: ekran listesi, veri modeli, 3rd-party API ihtiyaçları, navigasyon akışı. Çıktısı: `AppSpec` JSON. | Görsel tasarım yapmaz, kod yazmaz. |
| **UI/UX Agent** | Claude Sonnet 5 (+ vision) | `AppSpec`'ten wireframe/mockup üretir (aşağıda tool seçenekleri). Design token'ları (renk, tipografi, spacing) üretir. Çıktısı: `DesignSpec` JSON + mockup görselleri (S3/GCS URL). | Kod yazmaz, backend mantığı kurmaz. |
| **Coder Agent** | **Claude Sonnet 5** (agentic coding) | `AppSpec` + `DesignSpec`'i alıp Flutter/RN proje iskeletini ve tüm kaynak kodunu yazar/düzenler. Self-healing döngüsünde hata raporlarını okuyup patch üretir. | Test/derleme yapmaz (bunu QA Agent yapar), kendi kendine "onaylandı" diyemez. |
| **QA/Compiler Agent** | İlk 2 iterasyon: Claude Sonnet 5. 3. iterasyondan sonra eskalasyon: **Claude Opus 4.8 / Fable 5** | Cloud CI runner'ı tetikler, derleme/lint/unit test loglarını toplar, stack trace'i yapısal `ErrorReport` JSON'a çevirir. | Kod yazmaz/düzeltmez — sadece teşhis eder, Coder Agent'a devreder. |
| **Visual Reviewer Agent** | Claude Sonnet 5 (vision) | Cloud device farm'dan gelen ekran görüntülerini `DesignSpec` mockup'larıyla karşılaştırır, UI bug'larını (taşma, kırpılma, kontrast, hizalama) tespit eder. Çıktısı: `VisualQAReport` JSON. | Kodu düzeltmez, sadece bulgu raporlar. |
| **Release Candidate Builder** | Model yok (deterministik orkestrasyon kodu) | Tüm QA + Visual QA geçtiyse imzalı APK/AAB/IPA üretir, metadata + changelog hazırlar, Approval Panel'e gönderir. | Karar vermez, insan onayı bekler. |
| **Deployment Agent** | Model yok (deterministik) | Onay sonrası Play Console / App Store Connect API'lerini çağırır. | Onay olmadan asla tetiklenmez (hard gate). |

> **Not — model versiyonlama riski:** "Claude Fable 5" ve "Opus 4.8" adları senin promptunda geçiyor; kodda model ID'lerini config/env değişkeninden okuyacağız (`CODER_MODEL_ID`, `QA_ESCALATION_MODEL_ID` vb.) ki gerçek model kataloğu değiştiğinde tek satır değişikliği yeterli olsun. Kodlamaya başlarken kullanılabilir model ID'lerini API'den doğrulayacağız.

### 1.2 Paylaşılan State Object (LangGraph State)

Tek bir büyük `PipelineState` TypedDict/Pydantic modeli, her node'un okuyup güncellediği alanlarla:

```python
class PipelineState(TypedDict):
    run_id: str
    phase: Literal["idea","spec","design","coding","qa","visual_qa","release","done","failed"]

    app_concept: AppConcept | None
    app_spec: AppSpec | None
    design_spec: DesignSpec | None

    repo_ref: str                     # git worktree / branch referansı
    code_diff_history: list[CodeDiff] # her coder iterasyonunun diff'i (denetim izi)

    build_result: BuildResult | None
    qa_iteration: int                 # circuit breaker sayacı
    qa_error_fingerprints: list[str]  # döngü tespiti için hash geçmişi

    visual_qa_result: VisualQAReport | None
    visual_qa_iteration: int

    release_candidate: ReleaseCandidate | None
    human_decision: Literal["pending","approved","rejected"] | None
    human_feedback: str | None

    escalation_level: Literal["sonnet","opus_fable"]
    circuit_breaker_tripped: bool
```

### 1.3 Kritik JSON Şemaları (ajanlar arası kontrat)

```json
// AppSpec (Spec Agent -> UI/UX Agent, Coder Agent)
{
  "app_name": "string",
  "core_feature": "string (tek cümlelik, single-feature kısıtı)",
  "platform": "flutter | react-native",
  "screens": [
    {"name": "HomeScreen", "purpose": "string", "components": ["string"], "navigation_targets": ["string"]}
  ],
  "data_model": [{"entity": "string", "fields": [{"name": "string", "type": "string"}]}],
  "external_apis": [{"name": "string", "purpose": "string", "auth_type": "string"}],
  "non_functional": {"offline_support": "bool", "target_sdk": "string"}
}
```

```json
// ErrorReport (QA Agent -> Coder Agent) — self-healing döngüsünün kalbi
{
  "run_id": "string",
  "iteration": 2,
  "error_type": "compile_error | test_failure | lint_error | runtime_crash",
  "raw_stack_trace": "string",
  "file_path": "lib/screens/home_screen.dart",
  "line_number": 42,
  "structured_summary": "string (LLM tarafından özetlenmiş kök neden)",
  "fingerprint": "sha256-hash (file+error_type+normalized_message)",
  "previous_fix_attempt": "string | null"
}
```

```json
// VisualQAReport (Visual Reviewer -> Coder Agent)
{
  "run_id": "string",
  "screenshot_url": "string",
  "reference_mockup_url": "string",
  "verdict": "pass | fail",
  "issues": [
    {
      "type": "overflow | misalignment | color_mismatch | text_clipping | contrast",
      "screen": "HomeScreen",
      "bounding_box": [x, y, w, h],
      "description": "string",
      "severity": "blocker | major | minor"
    }
  ]
}
```

### 1.4 LangGraph Node/Edge Modeli

```python
graph = StateGraph(PipelineState)

graph.add_node("idea", idea_agent_node)
graph.add_node("spec", spec_agent_node)
graph.add_node("design", ui_ux_agent_node)
graph.add_node("code", coder_agent_node)
graph.add_node("build_and_test", qa_compiler_agent_node)
graph.add_node("visual_review", visual_reviewer_agent_node)
graph.add_node("build_release_candidate", release_candidate_node)
graph.add_node("await_human", human_gate_node)   # interrupt() burada
graph.add_node("deploy", deployment_agent_node)

graph.set_entry_point("idea")
graph.add_edge("idea", "spec")
graph.add_edge("spec", "design")
graph.add_edge("design", "code")
graph.add_edge("code", "build_and_test")

# Self-healing kenarı (koşullu)
graph.add_conditional_edges(
    "build_and_test",
    route_after_build,   # bkz. 2.2
    {
        "retry_code": "code",
        "proceed_visual": "visual_review",
        "circuit_break": "await_human",  # başarısızlıkla insana devret
    },
)

graph.add_conditional_edges(
    "visual_review",
    route_after_visual_qa,
    {
        "retry_code": "code",
        "proceed_release": "build_release_candidate",
        "circuit_break": "await_human",
    },
)

graph.add_edge("build_release_candidate", "await_human")
graph.add_conditional_edges(
    "await_human",
    route_after_human,
    {"deploy": "deploy", "retry_code": "code", "end": END},
)
graph.add_edge("deploy", END)

app = graph.compile(checkpointer=PostgresSaver(conn))
```

`await_human` node'u LangGraph'ın `interrupt()` mekanizmasını kullanır: graf burada gerçekten duraklar, Approval Panel'den webhook gelene kadar Postgres checkpoint'te bekler (worker kaynak tüketmez).

---

## 2. Self-Healing & Compilation Loop (Kritik Bölüm)

### 2.1 Cloud Derleme Pipeline'ı

Lokal GPU/donanım yok kısıtı gereği, derleme tamamen cloud CI üzerinde:

- **Flutter hedefi:** GitHub Actions (`macos-14` runner, iOS build için gerekli; Android için `ubuntu-latest` yeterli) + `subosito/flutter-action`. Alternatif/daha az ops yükü isteyen için **Codemagic** (Flutter'a özel, yerleşik imzalama ve mağaza entegrasyonu var).
- **React Native hedefi:** **EAS Build** (Expo Application Services) — yönetilen imzalama, cloud derleme, hem iOS hem Android tek API çağrısıyla (`eas build --platform all --non-interactive --json`).
- Orkestratör (FastAPI backend), CI'ı **API üzerinden** tetikler (GitHub Actions `workflow_dispatch` REST API veya EAS Build REST API), polling/webhook ile sonucu alır. Ajanlar hiçbir zaman doğrudan CI sistemine kod push etmez — orkestratör bir git worktree/branch'e commit atar, CI o branch'i build eder.

Derleme adımları (sırayla, "fail fast" için ucuz kontroller önce):
1. `flutter analyze` / `eslint + tsc --noEmit` — statik analiz (saniyeler içinde, LLM çağrısı gerektirmez)
2. `flutter test` / `jest` — unit testler
3. `flutter build appbundle --release` / `eas build` — asıl derleme
4. Başarılıysa artifact S3/GCS'e yüklenir, `BuildResult.status = "success"`

### 2.2 Hata Besleme Döngüsü ve Circuit Breaker

```python
MAX_ITERATIONS = 5
MAX_SAME_FINGERPRINT_REPEAT = 2  # aynı hata 2 kez tekrar ederse "döngüde takıldı" say

def route_after_build(state: PipelineState) -> str:
    if state["build_result"].status == "success":
        return "proceed_visual"

    state["qa_iteration"] += 1
    fp = state["build_result"].error_report.fingerprint
    repeat_count = state["qa_error_fingerprints"].count(fp)
    state["qa_error_fingerprints"].append(fp)

    if state["qa_iteration"] >= MAX_ITERATIONS or repeat_count >= MAX_SAME_FINGERPRINT_REPEAT:
        state["circuit_breaker_tripped"] = True
        return "circuit_break"

    # Eskalasyon: ilk 2 deneme Sonnet, sonrası Opus/Fable (karmaşık hata analizi)
    if state["qa_iteration"] > 2:
        state["escalation_level"] = "opus_fable"

    return "retry_code"
```

**Circuit Breaker prensipleri:**
- **Sayaç bazlı sınır:** `qa_iteration >= 5` → otomatik olarak insana (`await_human`) devredilir, "sistem bu hatayı kendi başına çözemedi" notuyla, son 5 diff + hata geçmişi ekli.
- **Fingerprint bazlı döngü tespiti:** Aynı hata hash'i 2. kez görülürse (Coder Agent aynı hatayı tekrar üretmiş demektir → ilerleme yok), döngü kırılır — 5 hakkı beklemeden erken çıkış.
- **Model eskalasyonu maliyet kontrolü:** İlk 2 deneme ucuz/hızlı modelle (Sonnet), inatçı hatalarda daha güçlü akıl yürütme modeline (Opus/Fable) geçilir — her hata için en pahalı modeli kullanmak yerine.
- **Bağlam biriktirme:** Her iterasyonda `code_diff_history`'e önceki fix denemesi eklenir; Coder Agent prompt'unda "bunları zaten denedin, işe yaramadı" bilgisi verilir — aynı yanlış çözümü tekrar üretmesini engeller.

---

## 3. Visual QA & Multi-Modal Verification

### 3.1 Ekran Görüntüsü Toplama (Cloud Device Farm)

- **Maestro** (mobile.dev): YAML tabanlı E2E akış tanımları (`- launchApp`, `- tapOn`, `- takeScreenshot`), hem Flutter hem RN'de çalışır, **Maestro Cloud** üzerinden gerçek cihazlarda çalıştırılıp ekran görüntüleri otomatik toplanır. Spec Agent'ın ürettiği `screens[].navigation_targets` bilgisinden Maestro flow YAML'ı otomatik üretilir.
- Alternatif/tamamlayıcı: **Firebase Test Lab** (Robo test — otomatik keşif + ekran görüntüsü) veya **BrowserStack App Automate** (Appium tabanlı, daha fazla cihaz/OS çeşitliliği).
- Her ekran için: `golden_path` görüntüsü (ana akış) + kritik ekranların tekil görüntüleri toplanır, S3/GCS'e yüklenir.

### 3.2 Multi-Modal Karşılaştırma Mimarisi

```
[Screenshot (device farm)] + [Reference Mockup (UI/UX Agent çıktısı)]
                    |
                    v
        Visual Reviewer Agent (Claude Sonnet 5, vision)
        Prompt: "Bu ekran görüntüsünü referans mockup ile karşılaştır.
                 Taşma, hizalama bozukluğu, kontrast sorunu, kırpılmış
                 metin var mı? Her sorunu bounding-box ile raporla."
                    |
                    v
        Structured Output -> VisualQAReport (JSON, şema 1.3'te)
```

- İki aşamalı kontrol: önce ucuz bir **piksel-diff** aracı (örn. `pixelmatch` kütüphanesi veya **Applitools Eyes** API) kaba farkları tespit eder → sadece fark bulunan ekranlar LLM'e gönderilir (maliyet optimizasyonu, her ekranı her seferinde vision modeline göndermek yerine).
- LLM çıktısı `severity: blocker` içeriyorsa otomatik olarak `retry_code`'a döner (Coder Agent'a UI fix görevi olarak `VisualQAReport` iletilir). `severity: minor` bulgular birikip insana bilgi amaçlı raporlanır ama döngüyü tetiklemez (aşırı-hassasiyet/gereksiz iterasyonu önlemek için eşik).
- `visual_qa_iteration` için de aynı circuit breaker mantığı (max 3 iterasyon) uygulanır — kod derleme döngüsünden ayrı sayaç.

---

## 4. Tech Stack & Model Seçim Matrisi

### 4.1 Model Dağılımı

| Görev | Model | Gerekçe |
|---|---|---|
| Idea/Spec/UI-UX/Coder (ana iş yükü) | **Claude Sonnet 5** | Agentic coding ve computer-use görevlerinde en yüksek hız/maliyet/kalite dengesi; büyük context window sayesinde tüm proje kod tabanını tek seferde görebilir. |
| QA hata çözümleme — 1-2. deneme | **Claude Sonnet 5** | Çoğu compile/lint hatası basit kalıplardır, ucuz modelle hızlıca çözülür. |
| QA hata çözümleme — 3+ deneme (eskalasyon) | **Claude Opus 4.8 / Fable 5** | Yüksek reasoning derinliği gerektiren inatçı/çok katmanlı hatalarda (örn. state management race condition, native modül çakışması) daha güçlü model devreye girer — maliyet sadece gerçekten gerektiğinde artar. |
| Visual Reviewer | **Claude Sonnet 5 (vision)** | Ekran görüntüsü + mockup karşılaştırmasında güçlü vision yeteneği; GPT-4o vendor-çeşitliliği için opsiyonel ikinci-görüş (cross-check) olarak eklenebilir ama zorunlu değil. |

Maliyet kontrolü: her ajan çağrısı `LangSmith` veya `Langfuse` ile trace'lenir, run başına token/maliyet dashboard'da izlenir; eskalasyon eşikleri (`MAX_ITERATIONS`, `escalation_level`) config'den ayarlanabilir olmalı ki maliyet/kalite dengesi sonradan tune edilebilsin.

### 4.2 Backend Mimarisi

```
┌─────────────────────────────────────────────────────────┐
│  FastAPI (orkestrasyon API katmanı)                       │
│   - POST /runs           -> yeni pipeline başlat           │
│   - GET  /runs/{id}      -> durum sorgula                  │
│   - POST /runs/{id}/approve | /reject  -> human gate       │
│   - Webhook receiver: CI sonucu, device farm sonucu        │
└─────────────────────────────────────────────────────────┘
        |                          |                    |
        v                          v                    v
  LangGraph Runtime      Postgres (state +      Redis (job queue,
  (StateGraph.compile)   checkpointer)          rate limiting)
        |
        v
  Celery / Temporal worker'ları (uzun süren build/device-farm
  bekleme adımlarını async, retry-able şekilde yönetir)
        |
        v
  S3 / GCS (kod artifact, screenshot, APK/AAB/IPA depolama)
```

- **Temporal** özellikle önerilir çünkü self-healing döngüsü ve saatler sürebilen device-farm beklemeleri için native "durable execution" + retry/backoff sağlar (Celery'ye göre bu senaryoda daha az custom kod gerektirir).
- Git işlemleri için her run kendi **git worktree**'sinde izole çalışır (paralel run'lar birbirine karışmaz).
- Approval Panel: ayrı bir **Next.js** dashboard, FastAPI'ye REST ile konuşur, Postgres'i doğrudan okumaz (API sınırı korunur).

---

## 5. Deployment & Delivery Flow

### 5.1 Onay Paneli

Next.js dashboard, her `run_id` için:
- Ekran görüntüleri galerisi (device farm çıktısı) + yanına referans mockup (yan yana diff görünümü)
- Build durumu, test sonuçları özeti, kaç self-healing iterasyonu geçtiği (şeffaflık için)
- İndirilebilir APK/AAB linki (imzalı, S3 presigned URL) — isteğe bağlı TestFlight/Internal Testing linki
- **[Onaylıyorum]** / **[Reddet + Yorum Ekle]** butonları

Reddetme akışı: yorum metni `human_feedback` alanına yazılır, `phase = "coding"`'e geri döner, Coder Agent bu yorumu yeni bir "insan-kaynaklı gereksinim" olarak işler (kendi ürettiği hata raporlarından ayrı bir kategori — `source: "human"` etiketiyle).

### 5.2 Otomatik Dağıtım

Onay sonrası **Deployment Agent** (deterministik, modelsiz):

- **Android:** `androidpublisher` (Google Play Developer API v3) — `fastlane supply` üzerinden AAB'yi `internal` track'e yükler. İlk dağıtım her zaman **Internal Testing**'e gider, production'a geçiş ayrı, açık bir manuel/otomatik kural gerektirir (örn. "N gün internal'da sorunsuz kalırsa otomatik production'a promote et" — bu kuralı da sistemde config olarak tanımlarız, varsayılan kapalı).
- **iOS:** App Store Connect API (`fastlane pilot` / `eas submit`) ile **TestFlight**'a yükleme.
- Kimlik/imzalama: Google Play App Signing (yönetilen anahtar) veya EAS managed credentials — özel anahtarları ajan/LLM asla görmez, sadece CI secret store'da (GitHub Actions Secrets / EAS Secrets) tutulur.
- Dağıtım sonrası webhook ile Approval Panel'e "yayınlandı" bildirimi düşer, `phase = "done"`.

---

## 6. Somut Araç Listesi (Özet Tablo)

| Katman | Araç |
|---|---|
| Ajan orkestrasyonu | LangGraph + Postgres checkpointer |
| Backend API | FastAPI |
| Durable execution / uzun işler | Temporal |
| Queue/cache | Redis |
| Kod derleme (Flutter) | GitHub Actions / Codemagic |
| Kod derleme (RN) | EAS Build |
| E2E + ekran görüntüsü | Maestro / Maestro Cloud, Firebase Test Lab |
| Piksel-diff ön filtre | Applitools Eyes / pixelmatch |
| Observability (LLM trace) | LangSmith / Langfuse |
| Artifact depolama | S3 / GCS |
| Onay Paneli | Next.js |
| Android dağıtım | Google Play Developer API (androidpublisher v3) + fastlane supply |
| iOS dağıtım | App Store Connect API + fastlane pilot / eas submit |

---

## 7. Sonraki Adım (Kodlamaya Geçiş İçin)

Bu doküman kodlamaya başlamak için yeterli netlikte. Önerilen ilk implementasyon sırası (MVP daraltması):
1. `PipelineState` + Postgres checkpointer ile boş LangGraph iskeleti
2. Idea → Spec → Coder zinciri (henüz self-healing yok) — tek bir Flutter "hello world + tek özellik" ile uçtan uca test
3. QA/Compiler Agent + circuit breaker döngüsü ekle (GitHub Actions entegrasyonu)
4. Visual Reviewer Agent + Maestro entegrasyonu ekle
5. Approval Panel (Next.js) + Deployment Agent (Play Console internal track) ekle

Hazır olduğunda hangi adımdan başlamak istediğini söyle, o modülün kodunu yazmaya başlayalım.
