from __future__ import annotations

import argparse
import json
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
SCOPE = "https://www.googleapis.com/auth/drive.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    expected_state = ""
    result: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        returned_state = query.get("state", [""])[0]
        if returned_state != self.expected_state:
            self.result["error"] = "El estado OAuth no coincide."
            status = 400
            body = "No se pudo validar la respuesta. Puedes cerrar esta ventana."
        elif query.get("error"):
            self.result["error"] = query["error"][0]
            status = 400
            body = "Google no autorizó el acceso. Puedes cerrar esta ventana."
        else:
            self.result["code"] = query.get("code", [""])[0]
            status = 200
            body = "Google Drive quedó conectado. Puedes cerrar esta ventana y volver a Codex."
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:
        return


def read_client_credentials(path: Path) -> tuple[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    credentials = payload.get("installed") or payload.get("web") or {}
    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")
    if not client_id or not client_secret:
        raise ValueError("El JSON no contiene client_id y client_secret de OAuth.")
    return str(client_id), str(client_secret)


def get_authorization_code(client_id: str) -> tuple[str, str]:
    state = secrets.token_urlsafe(32)
    OAuthCallbackHandler.expected_state = state
    OAuthCallbackHandler.result = {}
    server = HTTPServer(("127.0.0.1", 0), OAuthCallbackHandler)
    server.timeout = 300
    redirect_uri = f"http://127.0.0.1:{server.server_port}/"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    authorization_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    if not webbrowser.open(authorization_url):
        print("Abre esta dirección en el navegador para autorizar Google Drive:")
        print(authorization_url)
    print("Esperando autorización de Google en el navegador (hasta 5 minutos)...")
    thread.join(timeout=305)
    server.server_close()
    if thread.is_alive():
        raise TimeoutError("No se recibió la respuesta de Google dentro de 5 minutos.")
    if OAuthCallbackHandler.result.get("error"):
        raise RuntimeError(OAuthCallbackHandler.result["error"])
    code = OAuthCallbackHandler.result.get("code")
    if not code:
        raise RuntimeError("Google no devolvió un código de autorización.")
    return code, redirect_uri


def exchange_code(code: str, redirect_uri: str, client_id: str, client_secret: str) -> str:
    body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("ascii")
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as error:  # noqa: BLE001
        raise RuntimeError("No se pudo intercambiar el código OAuth. Revisa el cliente de Google.") from error
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise RuntimeError(
            "Google no devolvió refresh_token. Revoca el acceso anterior de esta app y vuelve a autorizar."
        )
    return str(refresh_token)


def update_env(client_id: str, client_secret: str, refresh_token: str) -> None:
    values = {
        "GOOGLE_DRIVE_CLIENT_ID": client_id,
        "GOOGLE_DRIVE_CLIENT_SECRET": client_secret,
        "GOOGLE_DRIVE_REFRESH_TOKEN": refresh_token,
    }
    lines = ENV_PATH.read_text(encoding="utf-8-sig").splitlines() if ENV_PATH.exists() else []
    remaining = set(values)
    output = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in values:
            output.append(f"{key}={values[key]}")
            remaining.discard(key)
        else:
            output.append(line)
    if remaining and output and output[-1]:
        output.append("")
    output.extend(f"{key}={values[key]}" for key in values if key in remaining)
    ENV_PATH.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autoriza el backend a leer documentos privados de Google Drive."
    )
    parser.add_argument("credentials_json", type=Path, help="JSON OAuth descargado desde Google Cloud Console")
    args = parser.parse_args()
    client_id, client_secret = read_client_credentials(args.credentials_json)
    code, redirect_uri = get_authorization_code(client_id)
    refresh_token = exchange_code(code, redirect_uri, client_id, client_secret)
    update_env(client_id, client_secret, refresh_token)
    print(f"Credenciales guardadas en {ENV_PATH}.")
    print("Reinicia el backend para que cargue la conexión. No compartas ni subas .env a Git.")


if __name__ == "__main__":
    main()
