"""Rotacion persistente de candidatos disponibles; no equivale a pruebas aprobadas."""

import json
import sqlite3
import unicodedata
from pathlib import Path


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower().split())


class ProgramRotationService:
    def __init__(self, path: Path):
        self.path = path

    def choose(self, scope: list[str], candidates: list[dict]) -> dict:
        """Reserva el menos recientemente intentado entre los candidatos actuales."""
        if not candidates:
            raise ValueError("No hay programas disponibles para rotar.")
        scope_key = json.dumps([normalize(part) for part in scope], ensure_ascii=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=30) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS program_rotation (
                scope TEXT NOT NULL, program TEXT NOT NULL, last_attempt INTEGER NOT NULL,
                PRIMARY KEY(scope, program))""")
            connection.execute("BEGIN IMMEDIATE")
            history = dict(connection.execute(
                "SELECT program, last_attempt FROM program_rotation WHERE scope = ?", (scope_key,)
            ))
            # Texto estable: IDs de resultados autocomplete pueden cambiar entre consultas.
            candidate = min(candidates, key=lambda item: history.get(normalize(item["text"]), 0))
            key = normalize(candidate["text"])
            connection.execute("""INSERT INTO program_rotation VALUES (?, ?, ?)
                ON CONFLICT(scope, program) DO UPDATE SET last_attempt = excluded.last_attempt""",
                (scope_key, key, max(history.values(), default=0) + 1))
        return candidate
