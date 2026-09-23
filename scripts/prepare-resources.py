"""Prepare portable QA resources; never copy credentials from another computer."""
import argparse
import json
from pathlib import Path
import shutil
import zipfile

from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]
CATALOG = 'backend/data/Programas_UTEL_Todos_los_Paises.xlsx'


def inspect(root):
    config = dotenv_values(root / '.env')
    catalog = Path(config.get('PROGRAM_CATALOG_PATH') or CATALOG)
    if not catalog.is_absolute():
        catalog = root / catalog
    if not catalog.is_file():
        raise ValueError(f'Falta el catalogo {catalog}. Copie el proyecto completo, incluyendo backend/data.')
    with zipfile.ZipFile(catalog) as workbook:
        if 'xl/workbook.xml' not in workbook.namelist() or workbook.testzip():
            raise ValueError('El catalogo de programas esta danado.')
    for relative in (
        'backend/app/modules/weekly_auto/weekly_photos/default_urls.txt',
        'backend/app/modules/bot_leads_deploy/data/utel_programas1.xlsx',
        'backend/app/modules/bot_nuevos_productos/data/utel_programas1.xlsx',
    ):
        if not (root / relative).is_file():
            raise ValueError(f'Falta el recurso {relative}. Copie el proyecto completo.')
    bank = json.loads(config.get('UTEL_TEST_PHONES_JSON') or '{}')
    if not isinstance(bank, dict) or any(
        not isinstance(numbers, list) or any(not isinstance(n, str) for n in numbers)
        for numbers in bank.values()
    ):
        raise ValueError('El banco de telefonos debe contener paises y listas de numeros.')
    synthetic = str(config.get('UTEL_ALLOW_SYNTHETIC_REAL_PHONES') or '').lower() in ('true', '1', 'yes')
    return config, bank, synthetic


def prepare(root, apply=False):
    config, bank, synthetic = inspect(root)
    has_bank = any(bank.values())
    pending = not (root / '.env').exists() or (not has_bank and not synthetic)
    if pending and not apply:
        print('Configuracion pendiente: no hay banco de telefonos ni generacion de pruebas habilitada.')
        return 2
    if apply:
        if not (root / '.env').exists():
            shutil.copyfile(root / '.env.example', root / '.env')
        if not has_bank and not synthetic:
            set_key(root / '.env', 'UTEL_ALLOW_SYNTHETIC_REAL_PHONES', 'true', quote_mode='never')
        for folder in ('logs', 'reports', 'screenshots', 'visual_comparisons', 'browser_profiles'):
            (root / 'storage' / folder).mkdir(parents=True, exist_ok=True)
    print('Catalogo y recursos incluidos: OK. Telefonos: ' + ('banco configurado' if has_bank else 'generacion local de pruebas') + '.')
    if not (config.get('INCONCERT_USERNAME') or config.get('CRM_USERNAME')):
        print('Pendiente por equipo: configurar credenciales de InConcert en .env antes de usar el CRM.')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    try:
        raise SystemExit(prepare(ROOT, args.prepare))
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        print(f'No se pudieron preparar los recursos: {error}')
        raise SystemExit(1)
