"""Configuración del sistema de logs visibles para desarrolladores."""

import logging
from datetime import date
from pathlib import Path


LOGGER_NAME = "qa_automation"


def configure_logging(storage_dir: Path, level: str = "INFO") -> logging.Logger:
    """Configura consola y un archivo diario sin duplicar handlers al recargar."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    if logger.handlers:
        return logger

    log_directory = storage_dir / "logs" / date.today().isoformat()
    log_directory.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    file_handler = logging.FileHandler(log_directory / "backend.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def get_logger() -> logging.Logger:
    """Obtiene el logger común; el arranque de FastAPI se encarga de configurarlo."""

    return logging.getLogger(LOGGER_NAME)
