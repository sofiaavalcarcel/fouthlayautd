from __future__ import annotations

import asyncio
import time
from urllib.parse import quote, parse_qs, urlparse

import httpx


GOOGLE_DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API_URL = "https://www.googleapis.com/drive/v3"


class GoogleDriveClientError(RuntimeError):
    """A safe-to-display error raised while reading a Google Drive file."""


def google_document_id(source: str) -> str | None:
    """Extract a Google Docs/Drive file ID from a standard sharing URL."""

    parsed = urlparse(source)
    host = (parsed.hostname or "").casefold()
    if host not in {"docs.google.com", "drive.google.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if host == "docs.google.com":
        try:
            index = parts.index("document")
            if parts[index + 1] == "d":
                return parts[index + 2]
        except (ValueError, IndexError):
            return None
    if "d" in parts:
        try:
            return parts[parts.index("d") + 1]
        except IndexError:
            return None
    return parse_qs(parsed.query).get("id", [None])[0]


class GoogleDriveClient:
    """Read native Google Docs using a refresh token with the Drive readonly scope."""

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        refresh_token: str = "",
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.refresh_token = refresh_token.strip()
        self._client = client or httpx.AsyncClient(timeout=35.0, follow_redirects=True)
        self._owns_client = client is None
        self._access_token = ""
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)

    @property
    def has_any_configuration(self) -> bool:
        return bool(self.client_id or self.client_secret or self.refresh_token)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get_access_token(self) -> str:
        if not self.is_configured:
            raise GoogleDriveClientError(
                "Faltan GOOGLE_DRIVE_CLIENT_ID, GOOGLE_DRIVE_CLIENT_SECRET y "
                "GOOGLE_DRIVE_REFRESH_TOKEN para leer documentos privados."
            )
        if self._access_token and time.monotonic() < self._token_expires_at - 60:
            return self._access_token

        async with self._token_lock:
            if self._access_token and time.monotonic() < self._token_expires_at - 60:
                return self._access_token
            try:
                response = await self._client.post(
                    TOKEN_URL,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "refresh_token": self.refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                token = payload.get("access_token")
                if not token:
                    raise GoogleDriveClientError("Google no devolvió un access token válido.")
                self._access_token = str(token)
                self._token_expires_at = time.monotonic() + float(payload.get("expires_in", 3600))
                return self._access_token
            except GoogleDriveClientError:
                raise
            except (httpx.HTTPError, ValueError, TypeError) as error:
                raise GoogleDriveClientError(
                    "No se pudo renovar el acceso a Google Drive. Revisa las credenciales OAuth."
                ) from error

    async def export_docx(self, document_id: str) -> bytes:
        token = await self._get_access_token()
        url = f"{DRIVE_API_URL}/files/{quote(document_id, safe='')}/export"
        try:
            response = await self._client.get(
                url,
                params={"mimeType": GOOGLE_DOCX_MIME_TYPE},
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status in {401, 403}:
                message = (
                    "Google Drive rechazó el acceso al documento. Verifica que la cuenta autorizada "
                    "pueda abrirlo y que el refresh token incluya el alcance drive.readonly."
                )
            else:
                message = f"Google Drive respondió HTTP {status} al exportar el documento."
            raise GoogleDriveClientError(message) from error
        except httpx.HTTPError as error:
            raise GoogleDriveClientError("No se pudo descargar el documento de Google Drive.") from error
