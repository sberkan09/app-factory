"""Ajanlar arası veri kontratları (ARCHITECTURE.md §1.3).

Her ajan bir sonraki ajana yalnızca bu Pydantic modellerinden birini aktarır.
Modeller aynı zamanda Anthropic structured-output şemaları olarak kullanılır.
"""

from typing import Literal

from pydantic import BaseModel, Field


# --- Idea Agent -> Spec Agent ---


class AppConcept(BaseModel):
    app_name: str
    one_liner: str = Field(description="Uygulamayı tek cümlede anlatan tanım")
    core_feature: str = Field(description="Tek çekirdek özellik (single-feature kısıtı)")
    target_audience: str
    differentiator: str = Field(description="Benzerlerinden ayıran tek nokta")


# --- Spec Agent -> UI/UX + Coder ---


class ScreenSpec(BaseModel):
    name: str
    purpose: str
    components: list[str]
    navigation_targets: list[str] = Field(default_factory=list)


class DataField(BaseModel):
    name: str
    type: str


class DataEntity(BaseModel):
    entity: str
    fields: list[DataField]


class ExternalAPI(BaseModel):
    name: str
    purpose: str
    auth_type: str


class AppSpec(BaseModel):
    app_name: str
    core_feature: str
    platform: Literal["flutter", "react-native"]
    screens: list[ScreenSpec]
    data_model: list[DataEntity] = Field(default_factory=list)
    external_apis: list[ExternalAPI] = Field(default_factory=list)
    offline_support: bool = False


# --- UI/UX Agent -> Coder + Visual Reviewer ---


class DesignTokens(BaseModel):
    primary_color: str
    secondary_color: str
    background_color: str
    text_color: str
    font_family: str
    corner_radius: int
    spacing_unit: int


class ScreenDesign(BaseModel):
    screen: str
    layout_description: str = Field(description="Ekranın yerleşiminin ayrıntılı sözel tarifi")
    key_components: list[str]


class DesignSpec(BaseModel):
    tokens: DesignTokens
    screen_designs: list[ScreenDesign]


# --- Coder Agent çıktısı ---


class GeneratedFile(BaseModel):
    path: str = Field(description="Proje köküne göre dosya yolu, örn. lib/main.dart")
    content: str


class CodeBundle(BaseModel):
    files: list[GeneratedFile]
    entry_point: str = Field(description="Ana dosya yolu, örn. lib/main.dart")
    notes: str = ""


# --- QA/Compiler Agent ---


class ErrorAnalysis(BaseModel):
    root_cause: str
    fix_strategy: str
    affected_files: list[str] = Field(default_factory=list)


class ErrorReport(BaseModel):
    iteration: int
    error_type: Literal["compile_error", "test_failure", "lint_error", "runtime_crash", "tooling_error"]
    step: str = Field(description="Hangi CI adımında oluştu: analyze | test | build")
    raw_output: str
    fingerprint: str
    analysis: ErrorAnalysis | None = None


class BuildResult(BaseModel):
    status: Literal["success", "failure", "skipped"]
    step: str = ""
    stdout: str = ""
    stderr: str = ""
    error_report: ErrorReport | None = None
    artifact_path: str | None = None


# --- Visual Reviewer Agent ---


class VisualIssue(BaseModel):
    type: Literal["overflow", "misalignment", "color_mismatch", "text_clipping", "contrast", "other"]
    screen: str
    description: str
    severity: Literal["blocker", "major", "minor"]


class VisualQAReport(BaseModel):
    verdict: Literal["pass", "fail", "skipped"]
    issues: list[VisualIssue] = Field(default_factory=list)
    summary: str = ""


# --- Release ---


class ReleaseCandidate(BaseModel):
    app_name: str
    version: str = "0.1.0"
    artifact_path: str | None = None
    changelog: str
    qa_iterations_used: int
    visual_iterations_used: int
