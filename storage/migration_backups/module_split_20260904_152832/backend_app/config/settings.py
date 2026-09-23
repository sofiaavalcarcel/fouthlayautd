"""Configuración centralizada y rutas de almacenamiento del proyecto."""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# Este archivo está tres niveles por debajo de la raíz del proyecto:
# backend/app/config/settings.py -> raíz del proyecto.
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Valores que controlan el backend sin esconderlos dentro de los servicios."""

    app_env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_url: str = "http://127.0.0.1:8000"
    database_path: Path = PROJECT_ROOT / "storage" / "qa_automation.db"
    storage_dir: Path = PROJECT_ROOT / "storage"
    # Catálogo oficial de programas con URL directa por país y nivel.
    program_catalog_path: Path = PROJECT_ROOT / "backend" / "data" / "utel_programas1.xlsx"
    log_level: str = "INFO"

    # Estas variables se reservan para las fases que integrarán servicios externos.
    strapi_url: str = ""
    strapi_token: str = ""
    crm_url: str = ""
    crm_username: str = ""
    crm_password: str = ""
    inconcert_username: str = ""
    inconcert_password: str = ""
    lead_balancer_url: str = "https://lead-balancer.scalahed.com/leads/"
    lead_balancer_username: str = ""
    lead_balancer_password: SecretStr = SecretStr("")
    # JSON con teléfonos reales controlados por QA, agrupados por país. Se
    # mantiene como secreto para que nunca aparezca en reprs ni respuestas.
    utel_test_phones_json: SecretStr = SecretStr("{}")
    # Permite probar formularios con teléfonos sintéticos válidos por país.
    # Está desactivado por defecto para exigir números autorizados por QA.
    utel_allow_synthetic_real_phones: bool = False

    # Servicios de IA: las claves se cargan desde .env y nunca se envían al renderer.
    ollama_api_key: SecretStr = SecretStr("")
    ollama_base_url: str = "https://ollama.com/api"
    ollama_model: str = "gpt-oss:120b"
    # Servidor de respaldo sin cuota de API. Requiere Ollama instalado y el modelo descargado.
    ollama_local_base_url: str = "http://127.0.0.1:11434/api"
    ollama_local_model: str = "gpt-oss:20b"
    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-2.5-flash"
    # El lote procesa filas consecutivas sin pausa. Al completar cada tanda,
    # publica un Excel acumulado y descansa antes de iniciar la siguiente.
    batch_size: int = 10
    batch_delay_seconds: int = 60
    # Tiempo máximo de espera para que InConcert indexe un lead antes de
    # consultar automáticamente el mismo email en el Balanceador.
    inconcert_index_wait_seconds: int = 60

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def ensure_directories(self) -> None:
        """Crea las carpetas que usarán las ejecuciones y los reportes."""

        # Las rutas relativas del .env se interpretan desde la raíz del proyecto,
        # aunque FastAPI haya sido iniciado desde la carpeta backend.
        if not self.storage_dir.is_absolute():
            self.storage_dir = PROJECT_ROOT / self.storage_dir
        if not self.database_path.is_absolute():
            self.database_path = PROJECT_ROOT / self.database_path
        if not self.program_catalog_path.is_absolute():
            self.program_catalog_path = PROJECT_ROOT / self.program_catalog_path

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        for folder_name in (
            "logs",
            "reports",
            "screenshots",
            "visual_comparisons",
        ):
            (self.storage_dir / folder_name).mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    def authorized_test_phones(self) -> dict[str, list[str]]:
        """Lee el banco privado de teléfonos autorizado para envíos reales."""

        raw_value = self.utel_test_phones_json.get_secret_value().strip() or "{}"
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise ValueError(
                "UTEL_TEST_PHONES_JSON no contiene un JSON válido."
            ) from error
        if not isinstance(parsed, dict):
            raise ValueError(
                "UTEL_TEST_PHONES_JSON debe ser un objeto con países y listas de teléfonos."
            )
        result: dict[str, list[str]] = {}
        for country, phones in parsed.items():
            if not isinstance(country, str) or not isinstance(phones, list) or not all(
                isinstance(phone, str) for phone in phones
            ):
                raise ValueError(
                    "Cada país de UTEL_TEST_PHONES_JSON debe contener una lista de teléfonos de texto."
                )
            result[country] = phones
        return result


@lru_cache
def get_settings() -> Settings:
    """Devuelve una única configuración para toda la ejecución del backend."""

    return Settings()
