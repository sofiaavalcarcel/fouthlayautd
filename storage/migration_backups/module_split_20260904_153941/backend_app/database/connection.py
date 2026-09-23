"""Conexiones SQLite y creación del esquema mínimo de la Fase 1."""

import sqlite3
from pathlib import Path
from typing import Iterator


def get_connection(database_path: Path) -> sqlite3.Connection:
    """Abre SQLite con filas accesibles por nombre y claves foráneas activas."""

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path: Path) -> None:
    """Crea las tablas necesarias sin borrar ejecuciones existentes."""

    database_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                automation_type TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_seconds REAL,
                summary TEXT,
                error_message TEXT,
                evidence_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_executions_started_at
                ON executions(started_at);

            CREATE INDEX IF NOT EXISTS idx_executions_status
                ON executions(status);

            CREATE TABLE IF NOT EXISTS test_leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_date TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                country TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                phone TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_test_leads_date
                ON test_leads(test_date);
            """
        )


def connection_rows(connection: sqlite3.Connection, query: str, parameters: tuple = ()) -> list[dict]:
    """Ejecuta una consulta de lectura y convierte sus filas a diccionarios simples."""

    return [dict(row) for row in connection.execute(query, parameters).fetchall()]
