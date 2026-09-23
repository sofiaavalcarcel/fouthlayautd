"""Check imports and launch the installed browser without external requests."""
import importlib
from importlib.metadata import version
from pathlib import Path
from packaging.requirements import Requirement
from playwright.sync_api import sync_playwright

for line in (Path(__file__).resolve().parents[1] / 'backend/requirements.txt').read_text().splitlines():
    if not line.strip() or line.lstrip().startswith('#'):
        continue
    requirement = Requirement(line)
    if requirement.marker and not requirement.marker.evaluate():
        continue
    if not requirement.specifier.contains(version(requirement.name), prereleases=True):
        raise RuntimeError(f'Version incompatible: {requirement}')

for module in (
    'fastapi', 'uvicorn', 'pydantic_settings', 'httpx', 'cloudscraper',
    'openpyxl', 'multipart', 'phonenumbers',
):
    importlib.import_module(module)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_content('<title>UTEL setup check</title>')
    assert page.title() == 'UTEL setup check'
    browser.close()
