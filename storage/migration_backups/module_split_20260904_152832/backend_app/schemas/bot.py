"""Contratos de entrada y salida del Bot de verificaciones."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


BotStepType = Literal[
    "goto",
    "click",
    "hover",
    "check",
    "uncheck",
    "fill",
    "select",
    "assert_text",
    "assert_url",
    "wait",
    "screenshot",
    "scroll",
]


class BotStep(BaseModel):
    """Un paso pequeño y explícito que el ejecutor puede traducir a Playwright."""

    type: BotStepType
    target: str = ""
    value: str = ""


class BotConfig(BaseModel):
    """Configuración completa de un flujo web, sin secretos sensibles."""

    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2000)
    browser: Literal["chromium", "chrome", "firefox", "webkit"] = "chromium"
    headless: bool = True
    keep_browser_open: bool = False
    steps: list[BotStep] = Field(min_length=1, max_length=100)


class BotStepResult(BaseModel):
    """Resultado legible de un paso individual."""

    step_number: int
    type: BotStepType
    status: Literal["PASS", "FAIL"]
    message: str
    screenshot: str | None = None


class BotRunResponse(BaseModel):
    """Resultado general que la interfaz mostrará al usuario."""

    status: Literal["PASS", "FAIL"]
    summary: str
    started_at: str
    finished_at: str
    duration_seconds: float
    steps: list[BotStepResult]
    screenshots: list[str] = Field(default_factory=list)


class BotStartResponse(BaseModel):
    """Respuesta inmediata al poner un bot en segundo plano."""

    job_id: str
    name: str
    status: Literal["QUEUED", "RUNNING"]
    started_at: str
    lead_email: str | None = None
    lead_phone: str | None = None
    lead_name: str | None = None


class BotJobResponse(BaseModel):
    """Estado consultable de una ejecución en segundo plano."""

    job_id: str
    name: str
    status: Literal["QUEUED", "RUNNING", "PASS", "FAIL", "CANCELLED"]
    started_at: str
    finished_at: str | None = None
    duration_seconds: float | None = None
    summary: str | None = None
    result: BotRunResponse | None = None


class UtelLead(BaseModel):
    """Datos del lead que se enviaran al formulario UTEL."""

    name: str = Field(default="pending", min_length=1, max_length=160)
    email: str = Field(default="pending@testingUtel.com", min_length=3, max_length=254)
    phone: str = Field(default="900000000", min_length=5, max_length=30)

    @field_validator("name", mode="before")
    @classmethod
    def default_name(cls, value: str | None) -> str:
        return str(value or "").strip() or "pending"

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        """Valida un correo sin depender de paquetes adicionales."""

        email = value.strip()
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            raise ValueError("El correo del lead no tiene un formato valido.")
        return email


class UtelQaConfig(BaseModel):
    """Configuracion del flujo especializado UTEL -> InConcert."""

    name: str = Field(default="QA UTEL + InConcert", min_length=1, max_length=120)
    environment: Literal["sandbox", "production"] = "sandbox"
    dry_run: bool = True
    country: str = Field(min_length=1, max_length=80)
    utel_url: str = Field(min_length=1, max_length=2000)
    inconcert_url: str = Field(default="", max_length=2000)
    # URL explícita de origen del lead: InConcert o Balanceador.
    lead_origin_url: str = Field(default="", max_length=2000)
    modality: str = Field(min_length=1, max_length=100)
    level: str = Field(min_length=1, max_length=120)
    form_type: Literal["lateral", "tarjeta", "footer"] = "lateral"
    program_selection_strategy: Literal["first", "exact_match"] = "first"
    program_name: str = Field(default="", max_length=180)
    submit_success_pattern: str = Field(default="Env\u00edo correcto|Pronto recibir\u00e1s informaci\u00f3n", max_length=240)
    submit_error_pattern: str = Field(default="Error al enviar|Contacta a soporte|error|invalido|inválido|obligatorio|requerido|fall", max_length=240)
    browser: Literal["chromium", "chrome", "firefox", "webkit"] = "chromium"
    headless: bool = True
    keep_browser_open: bool = False
    workflow_mode: Literal["product_release", "form_validation"] = "product_release"
    source_filename: str = Field(default="", max_length=260)
    navigation_modality: str = Field(default="", max_length=120)
    navigation_level: str = Field(default="", max_length=160)
    navigation_sublevel: str = Field(default="", max_length=160)
    defer_crm_verification: bool = False
    verification_only: bool = False
    skip_preselected_fields: bool = False
    lead: UtelLead

    @field_validator("program_name")
    @classmethod
    def clean_program_name(cls, value: str) -> str:
        return value.strip()


class UtelQaStageResult(BaseModel):
    """Resultado auditable de una etapa de negocio."""

    step_number: int
    stage: str
    status: Literal["PASS", "FAIL"]
    message: str
    selector: str | None = None
    url: str | None = None
    screenshot: str | None = None


class UtelQaRunResponse(BaseModel):
    """Resultado general del flujo UTEL -> InConcert."""

    status: Literal["PASS", "FAIL"]
    summary: str
    started_at: str
    finished_at: str
    duration_seconds: float
    country: str
    level: str
    modality: str
    form_type: str
    lead_email: str
    lead_name: str = ""
    lead_phone: str = ""
    selected_program_name: str = ""
    program_selection_notice: str = ""
    lead_url: str | None = None
    environment: str
    dry_run: bool
    workflow_mode: Literal["product_release", "form_validation"] = "product_release"
    # Permite distinguir fallos seguros para reintentar de cualquier resultado
    # ocurrido después del clic, donde un segundo envío podría duplicar el lead.
    utel_submission_attempted: bool = False
    utel_submission: Literal["pending", "success", "failed", "skipped"]
    utel_submission_message: str = ""
    inconcert_login: Literal["pending", "success", "failed", "skipped"]
    lead_found: Literal["pending", "success", "failed", "skipped"]
    conversion_found: Literal["pending", "success", "failed", "skipped"]
    stages: list[UtelQaStageResult]
    screenshots: list[str] = Field(default_factory=list)


class UtelQaJobResponse(BaseModel):
    """Estado consultable de una ejecucion UTEL en segundo plano."""

    job_id: str
    name: str
    status: Literal["QUEUED", "RUNNING", "PASS", "FAIL", "CANCELLED"]
    started_at: str
    finished_at: str | None = None
    duration_seconds: float | None = None
    summary: str | None = None
    result: UtelQaRunResponse | None = None
    cancel_requested: bool = False
