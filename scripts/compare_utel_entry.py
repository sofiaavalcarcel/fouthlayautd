"""Compare direct/list entry using the application's runner, never submitting.

Two fresh Chromium sessions, identical launch settings and target program.
Does not modify the app, the user's rotation history, or CRM records.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.modules.bot_nuevos_productos.runner import UtelInconcertRunner, UtelQaError
from app.config.settings import Settings
from app.modules.bot_nuevos_productos.schemas import UtelQaConfig

PROGRAM = "Doctorado en Administración Estratégica Empresarial"
SLUG = "doctorado-en-administracion-estrategica-empresarial"
# Listing paths are taken from the user's a10f70638a5e4921826dff4662180813 log.
ARGENTINA = ("Argentina", "argentina", "doctorados-virtuales", "9000000000")
OTHER_COUNTRIES = [
    ("Usa", "usa", "doctorados-online", "2025550100"),
    ("Bolivia", "bolivia", "doctorados-virtuales", "60000000"),
    ("Chile", "chile", "doctorados-virtuales", "900000000"),
    ("Paraguay", "paraguay", "doctorados-virtuales", "900000000"),
    ("Dominicana", "dominicana", "doctorados-virtuales", "8095550100"),
    ("Guatemala", "guatemala", "doctorados-virtuales", "50000000"),
    ("Panama", "panama", "doctorados-virtuales", "60000000"),
    ("El Salvador", "elsalvador", "doctorados-online", "70000000"),
]


class ComparisonRunner(UtelInconcertRunner):
    def _rotate_program(self, candidates, url):
        # Only fix the target; inherited code still performs the normal card click.
        target = self._normalize(PROGRAM).removeprefix("doctorado en ")
        for candidate in candidates:
            label = self._normalize(candidate["text"]).removeprefix("doctorado en ")
            if label == target:
                return candidate
        raise UtelQaError("utel_navigation", "El doctorado objetivo no aparece en las tarjetas disponibles.")

    async def _submit_utel_form(self, *args, **kwargs):
        raise AssertionError("Los envíos están prohibidos en esta comparación.")

    async def _open_inconcert(self, *args, **kwargs):
        raise AssertionError("Esta comparación no debe acceder al CRM.")

    async def _run_stage(self, number, stage, *args, **kwargs):
        print(f"INICIO {stage}", flush=True)
        result = await super()._run_stage(number, stage, *args, **kwargs)
        print(f"OK {stage}", flush=True)
        return result


def write_report(output_dir, report):
    output_dir = output_dir.resolve()
    (output_dir / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Comparación de acceso UTEL — sin envíos", "",
        f"Programa: {PROGRAM}.", "",
        "Chromium visible, viewport 1440 × 900. Una sesión nueva por ruta, "
        "misma configuración. Un intento por ruta; sin reintentos ante bloqueo. "
        "No se accede a InConcert y no se modifica la rotación de la app.", "",
        "PASS significa formulario preparado sin enviar; no confirma la creación de un lead.", "",
        f"Ejecuciones completadas: {len(report['results'])}/{report['planned_attempts']}.", "",
        "Esta comparación documenta el resultado de un intento por ruta. No identifica "
        "la regla de seguridad que produjo el bloqueo ni garantiza disponibilidad futura.", "",
        "| País | Ruta | Resultado | Etapa final | Evidencia |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in report["results"]:
        result = entry["result"]
        last_stage = result["stages"][-1] if result["stages"] else {}
        blocked = last_stage.get("stage") == "utel_access" and result["status"] == "FAIL"
        outcome = "Bloqueado" if blocked else ("Formulario listo, sin envío" if result["status"] == "PASS" else "Error distinto de bloqueo")
        evidence_stage = next((stage for stage in reversed(result["stages"]) if stage.get("screenshot")), {})
        screenshot = evidence_stage.get("screenshot")
        evidence = f"[Captura: {evidence_stage['stage']}](<{(output_dir.parent / screenshot).as_posix()}>)" if screenshot else "Sin captura"
        if not last_stage.get("screenshot"):
            evidence += "; sin captura de la etapa final"
        lines.append(f"| {entry['country']} | {entry['route']} | {outcome} | {last_stage.get('stage', '')} | {evidence} |")
    lines.extend(["", "## Detalles", ""])
    for entry in report["results"]:
        last_stage = entry["result"]["stages"][-1] if entry["result"]["stages"] else {}
        lines.extend([
            f"### {entry['country']} — {entry['route']}", "",
            f"Entrada: {entry['entry_url']}", "",
            f"URL final: {last_stage.get('url', '')}", "",
            f"Resultado: {last_stage.get('message', '')}", "",
        ])
    (output_dir / "comparison.md").write_text("\n".join(lines), encoding="utf-8")


async def main(countries):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_dir = ROOT / "storage" / "diagnostics" / f"entry_comparison_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=False)
    settings = Settings(
        _env_file=None,
        storage_dir=output_dir,
        database_path=output_dir / "unused.db",
        crm_username="", crm_password="", inconcert_username="", inconcert_password="",
    )
    report = {
        "target_program": PROGRAM,
        "browser": "chromium", "headless": False,
        "viewport": {"width": 1440, "height": 900},
        "session_design": "fresh independent session per route; same runner and launch options",
        "dry_run": True, "results": [],
        "planned_countries": [country[0] for country in countries],
        "planned_attempts": 2 * len(countries),
    }
    for country, country_path, listing_path, phone in countries:
        direct = f"https://utel.edu.mx/{country_path}/{SLUG}"
        listing = f"https://utel.edu.mx/{country_path}/{listing_path}"
        for route, url, program in [("direct", direct, PROGRAM), ("listing_click", listing, "")]:
            print(f"PRUEBA {country} {route}: {url}", flush=True)
            config = UtelQaConfig(
                name=f"Comparacion {country} {route}", environment="production", dry_run=True,
                country=country, utel_url=url, inconcert_url="",
                modality="En linea", level="Doctorado", form_type="tarjeta",
                program_name=program, workflow_mode="form_validation",
                browser="chromium", headless=False, keep_browser_open=False,
                lead={"name": "QAComparacionSinEnvio", "email": "qa.comparacion@example.invalid", "phone": phone},
            )
            result = await ComparisonRunner(settings).run(config)
            result["stages"] = [stage.model_dump() for stage in result["stages"]]
            report["results"].append({"country": country, "route": route, "entry_url": url, "result": result})
            write_report(output_dir, report)
            print(json.dumps({"country": country, "route": route, "status": result["status"], "stages": result["stages"]}, ensure_ascii=False), flush=True)
    print(f"REPORTE {output_dir / 'comparison.json'}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--other-countries", action="store_true", help="Compare the eight other countries in the user's error log.")
    args = parser.parse_args()
    asyncio.run(main(OTHER_COUNTRIES if args.other_countries else [ARGENTINA]))
