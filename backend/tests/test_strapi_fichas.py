import io

from openpyxl import Workbook

from backend.app.modules.strapi_products.fichas import FichasLookup


def test_fichas_lookup_can_read_uploaded_workbook_bytes():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Programa", "URL"])
    sheet.append(["Maestría en Educación - Argentina", "https://example.test/ficha.pdf"])
    output = io.BytesIO()
    workbook.save(output)

    lookup = FichasLookup(output.getvalue())

    assert lookup.find("Maestría en Educación", "Argentina") == "https://example.test/ficha.pdf"


def test_fichas_lookup_prefers_online_modality_when_country_has_multiple_fichas():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Nombre", "Link Acortado"])
    sheet.append(["Licenciatura en Educación - Ejecutiva - México", "https://example.test/ejecutiva"])
    sheet.append(["Licenciatura en Educación - En línea - México", "https://example.test/online"])
    sheet.append(["Licenciatura en Educación - Híbrida - México", "https://example.test/hibrida"])
    output = io.BytesIO()
    workbook.save(output)

    assert FichasLookup(output.getvalue()).find("Licenciatura en Educación", "Mexico") == "https://example.test/online"
