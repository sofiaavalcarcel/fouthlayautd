"""Generación persistente de datos sintéticos para pruebas de leads."""

import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

import phonenumbers

from ..database.connection import get_connection, initialize_database


class TestLeadService:
    """Reserva identificadores de QA únicos con el formato exigido por cada país."""

    __test__ = False

    # Prefijo nacional y cantidad total de dígitos del teléfono que espera el formulario.
    PHONE_FORMATS = {
        "mexico": ("55", 10),
        "ecuador": ("9", 9),
        "colombia": ("3", 10),
        "peru": ("9", 9),
        "chile": ("9", 9),
        # El formulario ya agrega +54. Se usa el indicativo geográfico 11 y
        # diez dígitos nacionales; un 9 inicial pertenece al formato E.164 y
        # era rechazado cuando se enviaba dentro del campo local.
        "argentina": ("11", 10),
        "usa": ("20255501", 10),
        "united states": ("20255501", 10),
        "estados unidos": ("20255501", 10),
        "bolivia": ("6", 8),
        # Paraguay usa nueve dígitos nacionales para móvil. La serie 900 es no
        # geográfica; 981 mantiene una estructura móvil admitida por el formulario.
        "paraguay": ("981", 9),
        "dominicana": ("80955501", 10),
        "republica dominicana": ("80955501", 10),
        "dominican republic": ("80955501", 10),
        "guatemala": ("5", 8),
        "panama": ("6", 8),
        "el salvador": ("7", 8),
        "global": ("20255501", 10),
        "filipinas": ("9", 10),
        "philippines": ("9", 10),
        "india": ("9", 10),
    }

    # Región ISO usada por libphonenumber para comprobar que un número
    # autorizado pertenece realmente al país de la fila.
    COUNTRY_REGIONS = {
        "mexico": "MX",
        "ecuador": "EC",
        "colombia": "CO",
        "peru": "PE",
        "chile": "CL",
        "argentina": "AR",
        "usa": "US",
        "united states": "US",
        "estados unidos": "US",
        "bolivia": "BO",
        "paraguay": "PY",
        "dominicana": "DO",
        "republica dominicana": "DO",
        "dominican republic": "DO",
        "guatemala": "GT",
        "panama": "PA",
        "el salvador": "SV",
        "global": "US",
        "filipinas": "PH",
        "philippines": "PH",
        "india": "IN",
    }
    COUNTRY_POOL_ALIASES = {
        "usa": ("usa", "united states", "estados unidos"),
        "united states": ("usa", "united states", "estados unidos"),
        "estados unidos": ("usa", "united states", "estados unidos"),
        "dominicana": ("dominicana", "republica dominicana", "dominican republic"),
        "republica dominicana": ("dominicana", "republica dominicana", "dominican republic"),
        "dominican republic": ("dominicana", "republica dominicana", "dominican republic"),
        "global": ("global", "usa", "united states", "estados unidos"),
        "filipinas": ("filipinas", "philippines"),
        "philippines": ("filipinas", "philippines"),
    }

    def __init__(
        self,
        database_path: Path,
        authorized_phones: dict[str, list[str]] | None = None,
        allow_synthetic_real_phones: bool = False,
    ):
        self.database_path = database_path
        self.allow_synthetic_real_phones = allow_synthetic_real_phones
        self.authorized_phones = {
            self._normalize(country): list(phones)
            for country, phones in (authorized_phones or {}).items()
        }
        initialize_database(database_path)

    def reserve(
        self,
        country: str,
        require_authorized_phone: bool = False,
    ) -> dict[str, Any]:
        """Reserva un lead; en producción exige un teléfono controlado por QA."""

        return self.reserve_many([country], require_authorized_phone)[0]

    def reserve_many(
        self,
        countries: list[str],
        require_authorized_phone: bool = False,
    ) -> list[dict[str, Any]]:
        """Reserva un lote atómico para fallar antes del primer formulario."""

        if not countries:
            return []
        today = date.today().isoformat()
        reserved: list[dict[str, Any]] = []

        with get_connection(self.database_path) as connection:
            # BEGIN IMMEDIATE evita que dos ejecuciones simultáneas reciban el mismo N.
            connection.execute("BEGIN IMMEDIATE")
            next_sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM test_leads WHERE test_date = ?",
                (today,),
            ).fetchone()[0]
            phone_sequence = connection.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM test_leads"
            ).fetchone()[0]
            used = {
                str(row[0])
                for row in connection.execute("SELECT phone FROM test_leads")
            }

            for country in countries:
                country_label = country.strip()
                normalized_country = self._normalize(country)
                email = f"Testing{today}N{next_sequence}@testingUtel.com"
                if require_authorized_phone:
                    phone = self._next_authorized_phone(
                        normalized_country,
                        country_label,
                        used,
                    )
                else:
                    phone = self._generated_phone(
                        normalized_country,
                        country_label,
                        phone_sequence,
                        used,
                    )
                # Algunos portales UTEL rechazan cualquier dígito en el nombre.
                name = f"Danilo Prueba {self._alphabetic_sequence(phone_sequence)}"
                connection.execute(
                    "INSERT INTO test_leads (test_date, sequence, country, email, phone, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (today, next_sequence, country_label, email, phone, datetime.now().isoformat(timespec="seconds")),
                )
                reserved.append(
                    {
                        "name": name,
                        "email": email,
                        "phone": phone,
                        "country": country_label,
                        "sequence": next_sequence,
                    }
                )
                used.add(phone)
                next_sequence += 1
                phone_sequence += 1

        return reserved

    def validate_authorized_capacity(self, countries: list[str]) -> None:
        """Comprueba formato y capacidad del banco sin consumir sus números."""

        with get_connection(self.database_path) as connection:
            used = {
                str(row[0])
                for row in connection.execute("SELECT phone FROM test_leads")
            }
        simulated_used = set(used)
        for country in countries:
            country_label = country.strip()
            phone = self._next_authorized_phone(
                self._normalize(country),
                country_label,
                simulated_used,
            )
            simulated_used.add(phone)

    def _next_authorized_phone(
        self,
        normalized_country: str,
        country_label: str,
        used: set[str],
    ) -> str:
        aliases = self.COUNTRY_POOL_ALIASES.get(
            normalized_country,
            (normalized_country,),
        )
        configured = next(
            (
                self.authorized_phones[alias]
                for alias in aliases
                if alias in self.authorized_phones
            ),
            None,
        )
        if not configured:
            raise ValueError(
                f"No se inició ningún envío: falta un banco de teléfonos autorizados para {country_label} en UTEL_TEST_PHONES_JSON."
            )

        validated: list[str] = []
        for raw_phone in configured:
            validated.append(self._validate_authorized_phone(raw_phone, normalized_country, country_label))
        for phone in dict.fromkeys(validated):
            if phone not in used and self._is_valid_generated_phone(phone, normalized_country):
                return phone
        raise ValueError(
            f"No se inició ningún envío: se agotaron los teléfonos autorizados para {country_label}. Agrega números nuevos a UTEL_TEST_PHONES_JSON."
        )

    def _validate_authorized_phone(
        self,
        raw_phone: str,
        normalized_country: str,
        country_label: str,
    ) -> str:
        region = self.COUNTRY_REGIONS.get(normalized_country)
        if region is None:
            raise ValueError(
                f"No existe una regla telefónica para el país {country_label}."
            )
        try:
            parsed = phonenumbers.parse(raw_phone.strip(), None if raw_phone.strip().startswith("+") else region)
        except phonenumbers.NumberParseException as error:
            raise ValueError(
                f"El banco autorizado contiene un teléfono que no se puede interpretar para {country_label}."
            ) from error
        actual_region = phonenumbers.region_code_for_number(parsed)
        if not phonenumbers.is_valid_number(parsed) or actual_region != region:
            raise ValueError(
                f"El banco autorizado contiene un teléfono que no es válido para {country_label}."
            )

        national = str(parsed.national_number)
        # El selector UTEL ya envía +54. libphonenumber conserva el 9 móvil
        # internacional, pero el campo local del portal espera diez dígitos.
        if region == "AR" and len(national) == 11 and national.startswith("9"):
            national = national[1:]
        _, expected_digits = self.PHONE_FORMATS[normalized_country]
        if len(national) != expected_digits:
            raise ValueError(
                f"El teléfono autorizado para {country_label} no tiene la longitud nacional que espera UTEL."
            )
        return national

    def _generated_phone(
        self,
        normalized_country: str,
        country_label: str,
        phone_sequence: int,
        used: set[str],
    ) -> str:
        prefix, total_digits = self.PHONE_FORMATS.get(normalized_country, ("9", 10))
        suffix_digits = total_digits - len(prefix)
        capacity = 10 ** suffix_digits
        # Distribuye la secuencia por todo el rango para evitar patrones obvios
        # durante dry run. Estos valores nunca se permiten en envíos reales.
        candidate = (capacity // 3 + phone_sequence * 7919) % capacity
        for _ in range(len(used) + 1):
            phone = prefix + str(candidate).zfill(suffix_digits)
            if phone not in used:
                return phone
            candidate = (candidate + 1) % capacity
        raise ValueError(
            f"Se agotaron los teléfonos generados para dry run de {country_label}."
        )

    def _is_valid_generated_phone(self, phone: str, normalized_country: str) -> bool:
        """Comprueba el plan nacional en el modo sintético de envío real."""

        if not self.allow_synthetic_real_phones:
            return True
        region = self.COUNTRY_REGIONS.get(normalized_country)
        if region is None:
            return False
        try:
            parsed = phonenumbers.parse(phone, region)
        except phonenumbers.NumberParseException:
            return False
        return (
            phonenumbers.is_valid_number(parsed)
            and phonenumbers.region_code_for_number(parsed) == region
        )

    @staticmethod
    def _normalize(value: str) -> str:
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _alphabetic_sequence(value: int) -> str:
        """Convierte 1, 2, ..., 27 en A, B, ..., AA sin usar dígitos."""

        if value < 1:
            raise ValueError("La secuencia del lead debe ser positiva.")
        letters: list[str] = []
        current = value
        while current:
            current, remainder = divmod(current - 1, 26)
            letters.append(chr(ord("A") + remainder))
        return "".join(reversed(letters))
