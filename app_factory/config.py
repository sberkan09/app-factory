from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Tüm pipeline ayarları. Env prefix: AF_ (bkz. .env.example)."""

    model_config = SettingsConfigDict(env_prefix="AF_", env_file=".env", extra="ignore")

    # Model seçim matrisi (ARCHITECTURE.md §4.1). Model ID'leri env'den
    # değiştirilebilir ki model kataloğu değişince kod dokunmadan güncellensin.
    planner_model_id: str = "claude-sonnet-5-5"
    coder_model_id: str = "claude-sonnet-5-5"
    vision_model_id: str = "claude-sonnet-5-5"
    qa_escalation_model_id: str = "claude-opus-5-5"  # veya claude-fable-5-1

    # Self-healing circuit breaker (ARCHITECTURE.md §2.2)
    max_qa_iterations: int = 5
    max_same_fingerprint: int = 2  # aynı hata fingerprint'i bu kadar kez görülürse döngü kırılır
    escalate_after_iteration: int = 2  # bu iterasyondan sonra escalation modeline geç
    max_visual_iterations: int = 3

    # Sağlayıcılar
    ci_provider: str = "local"  # local | github | stub
    device_farm_provider: str = "stub"  # stub | maestro
    deployment_provider: str = "stub"  # stub | play_console

    # GitHub Actions CI
    github_token: str = ""
    github_repo: str = ""  # "owner/repo"
    github_workflow: str = "build.yml"
    github_ref: str = "main"  # workflow'un derleyeceği branch

    # Uygulama kimliği: her run için applicationId/bundle id = prefix + slug(app_name)
    app_id_prefix: str = "com.appfactory"

    # Depolama
    workspace_root: Path = Path("./workspaces")
    checkpoint_db: str = "./app_factory.sqlite"


settings = Settings()
