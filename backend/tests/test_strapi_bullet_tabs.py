import asyncio
import io

from docx import Document

from backend.app.modules.strapi_products.bullet_tabs import (
    BulletTabContent,
    build_bullet_tab_payload,
    extract_bullet_tabs,
)
from backend.app.modules.strapi_products.description_runner import StrapiDescriptionRunner
from backend.app.modules.strapi_products.models import ProductRow


def _document() -> bytes:
    document = Document()
    document.add_paragraph("Programa de prueba", style="Title")
    document.add_paragraph("Descripción general del PDP.")
    document.add_paragraph("Asignaturas", style="Heading 1")
    document.add_paragraph("Información del plan.")
    document.add_paragraph("1° cuatrimestre", style="Heading 2")
    for heading, intro, bullets in (
        ("Perfil de ingreso:", "Texto introductorio de ingreso.", ["Interés ambiental: comprender el entorno.", "Análisis: organizar información."]),
        ("Perfil de egreso", "Texto introductorio de egreso.", ["Diseño: crear proyectos."]),
        ("¿Dónde podrás trabajar?", "Texto introductorio de empleabilidad.", ["Consultoría: asesorar organizaciones."]),
    ):
        document.add_paragraph(heading, style="Heading 1")
        document.add_paragraph(intro)
        for text in bullets:
            document.add_paragraph(text, style="List Bullet")
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def test_extract_bullet_tabs_separates_intro_from_bulleted_content():
    tabs = extract_bullet_tabs("pdp.docx", _document())
    assert tabs["Perfil ingreso"].description == "Texto introductorio de ingreso."
    assert tabs["Perfil ingreso"].bullets == (
        "Interés ambiental: comprender el entorno.",
        "Análisis: organizar información.",
    )
    assert tabs["Perfil egreso"].description == "Texto introductorio de egreso."
    assert tabs["Empleabilidad"].bullets == ("Consultoría: asesorar organizaciones.",)


def test_build_existing_bullet_tab_changes_only_its_own_text_and_preserves_settings():
    existing = {
        "id": 25,
        "attributes": {
            "strapiName": "Perfil ingreso Programa A",
            "title": {"id": 90, "desktop": "Perfil ingreso"},
            "content": [{
                "id": 12,
                "__component": "section.bullets",
                "iconsColor": "secondary.default",
                "hideSection": False,
                "bulletsDescription": {"id": 91, "desktop": "Texto anterior", "chakraConfig": None},
                "bullets": [{"id": 92, "title": None, "description": "Anterior", "chakraConfig": None}],
            }],
        },
    }
    template = {"id": 8, "attributes": {"strapiName": "Perfil ingreso Otro programa", "content": [{"id": 3, "__component": "section.bullets", "iconsColor": "red", "bullets": [{"id": 2, "description": "Texto prestado"}]}]}}
    payload = build_bullet_tab_payload(
        "Programa A", BulletTabContent("Perfil ingreso", "Nuevo párrafo.", ("Viñeta fiel al documento.",)),
        existing=existing, template=template, locale="es-AR",
    )
    component = payload["content"][0]
    assert component["id"] == 12
    assert component["iconsColor"] == "secondary.default"
    assert component["bulletsDescription"]["desktop"] == "Nuevo párrafo."
    assert component["bullets"][0]["description"] == "Viñeta fiel al documento."
    assert "strapiName" not in payload
    assert existing["attributes"]["content"][0]["bullets"][0]["description"] == "Anterior"
    assert template["attributes"]["content"][0]["bullets"][0]["description"] == "Texto prestado"


def test_build_new_bullet_tab_copies_style_without_reusing_component_ids():
    template = {
        "id": 8,
        "attributes": {
            "title": {"id": 77, "desktop": "Perfil ingreso", "chakraConfig": None},
            "iconTitle": None,
            "content": [{
                "id": 3,
                "__component": "section.bullets",
                "iconsColor": "secondary.default",
                "hideSection": False,
                "bulletsDescription": {"id": 4, "desktop": "Texto de referencia", "chakraConfig": None},
                "bullets": [{"id": 5, "description": "Texto ajeno", "chakraConfig": None}],
            }],
        },
    }
    payload = build_bullet_tab_payload(
        "Programa B", BulletTabContent("Perfil ingreso", "Texto del programa B.", ("Viñeta del programa B.",)),
        template=template, locale="es-AR",
    )
    assert payload["strapiName"] == "Perfil ingreso Programa B"
    assert payload["locale"] == "es-AR"
    assert payload["title"]["desktop"] == "Perfil ingreso"
    component = payload["content"][0]
    assert "id" not in component
    assert component["iconsColor"] == "secondary.default"
    assert component["bulletsDescription"]["desktop"] == "Texto del programa B."
    assert "id" not in component["bulletsDescription"]
    assert component["bullets"] == [{
        "title": None,
        "description": "Viñeta del programa B.",
        "chakraConfig": None,
        "icon": {"name": "UilCheck", "chakraConfig": None},
        "iconMobile": None,
    }]
    assert template["attributes"]["content"][0]["bullets"][0]["description"] == "Texto ajeno"


def test_existing_tab_without_desktop_image_copies_same_locale_template_media():
    existing = {
        "id": 25,
        "attributes": {
            "strapiName": "Perfil egreso Programa A",
            "content": [{
                "id": 12,
                "__component": "section.bullets",
                "coverImage": {"id": 50, "desktop": None},
                "bullets": [],
            }],
        },
    }
    template = {
        "id": 26,
        "attributes": {
            "strapiName": "Perfil egreso Programa B",
            "locale": "es-AR",
            "content": [{
                "id": 13,
                "__component": "section.bullets",
                "coverImage": {
                    "id": 51,
                    "desktop": {
                        "id": 52,
                        "image": {"data": {"id": 700, "attributes": {"name": "egreso.png"}}},
                        "objectFit": "cover",
                        "chakraConfig": {"objectPosition": "top center"},
                        "preload": False,
                    },
                },
                "bullets": [],
            }],
        },
    }
    payload = build_bullet_tab_payload(
        "Programa A", BulletTabContent("Perfil egreso", "Intro.", ("Viñeta.",)),
        existing=existing, template=template, locale="es-AR",
    )
    cover = payload["content"][0]["coverImage"]
    assert cover["id"] == 50
    assert cover["desktop"] == {
        "image": {"id": 700},
        "objectFit": "cover",
        "chakraConfig": {"objectPosition": "top center"},
        "preload": False,
    }
    assert template["attributes"]["content"][0]["coverImage"]["desktop"]["id"] == 52


def test_existing_tab_normalizes_populated_desktop_media_for_strapi_updates():
    existing = {
        "id": 25,
        "attributes": {
            "strapiName": "Perfil egreso Programa A",
            "content": [{
                "id": 12,
                "__component": "section.bullets",
                "coverImage": {
                    "id": 50,
                    "desktop": {
                        "id": 52,
                        "image": {"data": {"id": 700, "attributes": {"name": "egreso.png"}}},
                        "objectFit": "cover",
                    },
                },
                "bullets": [],
            }],
        },
    }
    payload = build_bullet_tab_payload(
        "Programa A", BulletTabContent("Perfil egreso", "Intro.", ("Viñeta.",)),
        existing=existing, locale="es-AR",
    )
    desktop = payload["content"][0]["coverImage"]["desktop"]
    assert desktop["id"] == 52
    assert desktop["image"] == {"id": 700}


def test_description_runner_updates_only_product_specific_bullet_tabs(tmp_path):
    source = tmp_path / "programa.docx"
    source.write_bytes(_document())
    updates = []
    created = []

    class FakeClient:
        def __init__(self):
            self.entries = {
                "Perfil ingreso Programa de prueba": {"id": 41, "attributes": {"strapiName": "Perfil ingreso Programa de prueba", "content": [{"id": 1, "__component": "section.bullets", "bullets": [], "bulletsDescription": {"desktop": "viejo"}}]}},
                "Perfil egreso Programa de prueba": {"id": 42, "attributes": {"strapiName": "Perfil egreso Programa de prueba", "content": [{"id": 2, "__component": "section.bullets", "bullets": [], "bulletsDescription": {"desktop": "viejo"}}]}},
                "Empleabilidad Programa de prueba": None,
            }
            self.template = {"id": 99, "attributes": {"title": {"desktop": "Empleabilidad"}, "content": [{"id": 9, "__component": "section.bullets", "iconsColor": "secondary.default", "bullets": []}]}}

        async def find_product(self, *args, **kwargs): return {"id": 7}
        async def get_product_tabs_bullet_section(self, *args):
            return {"id": 8, "hideSection": False, "tabs": [
                {"id": 41, "strapiName": "Perfil de ingreso Programa de prueba"},
                {"id": 42, "strapiName": "Perfil de egreso Programa de prueba"},
            ]}
        async def get_bullet_tab_by_id(self, identifier):
            return next(entry for entry in self.entries.values() if entry and entry["id"] == identifier)
        async def find_bullet_tab_template(self, prefix, locale): return self.template
        async def update_bullet_tab(self, identifier, payload):
            entry = next(item for item in self.entries.values() if item and item["id"] == identifier)
            entry["attributes"].update(payload)
            updates.append((identifier, payload))
            return {"id": identifier}
        async def create_bullet_tab(self, payload):
            created.append(payload)
            self.entries[payload["strapiName"]] = {"id": 43, "attributes": payload}
            return {"id": 43}
        async def update_product(self, identifier, payload): updates.append(("product", payload)); return {}

    client = FakeClient()
    results, summary = asyncio.run(StrapiDescriptionRunner(client, "Argentina", "es-AR", dry_run=False).run([
        ProductRow("Sheet", 2, "Programa de prueba", str(source))
    ]))
    assert results[0].status == "UPDATED", (results[0].message, results[0].verification)
    assert summary.updated == 1
    assert [item[0] for item in updates[:2]] == [41, 42]
    assert updates[0][1]["content"][0]["bulletsDescription"]["desktop"] == "Texto introductorio de ingreso."
    assert updates[0][1]["content"][0]["bullets"][0]["description"] == "Interés ambiental: comprender el entorno."
    assert updates[0][1]["content"][0]["bullets"][0]["icon"]["name"] == "UilCheck"
    assert len(created) == 1
    assert created[0]["strapiName"] == "Empleabilidad Programa de prueba"
    product_update = updates[-1][1]
    assert product_update["tabsBulletSection"]["tabs"] == [{"id": 41}, {"id": 42}, {"id": 43}]
    assert client.template["attributes"]["content"][0]["iconsColor"] == "secondary.default"


def test_description_runner_dry_run_does_not_create_or_update_strapi_entries(tmp_path):
    source = tmp_path / "programa.docx"
    source.write_bytes(_document())
    writes = []

    class FakeClient:
        async def find_product(self, *args, **kwargs): return {"id": 7}
        async def get_product_tabs_bullet_section(self, *args):
            return {"id": 8, "hideSection": False, "tabs": [
                {"id": 41, "strapiName": "Perfil de ingreso Programa de prueba"},
                {"id": 42, "strapiName": "Perfil de egreso Programa de prueba"},
            ]}
        async def get_bullet_tab_by_id(self, identifier):
            return {"id": identifier, "attributes": {"strapiName": f"tab {identifier}", "content": [{"id": identifier, "__component": "section.bullets", "bullets": []}]}}
        async def find_bullet_tab_template(self, prefix, locale):
            return {"id": 99, "attributes": {"title": {"desktop": prefix}, "content": [{"id": 9, "__component": "section.bullets", "bullets": []}]}}
        async def update_bullet_tab(self, *args): writes.append(("update-tab", args))
        async def create_bullet_tab(self, *args): writes.append(("create-tab", args))
        async def update_product(self, *args): writes.append(("update-product", args))

    results, summary = asyncio.run(StrapiDescriptionRunner(FakeClient(), "Argentina", "es-AR", dry_run=True).run([
        ProductRow("Sheet", 2, "Programa de prueba", str(source))
    ]))
    assert results[0].status == "DRY_RUN"
    assert summary.dry_run == 1
    assert writes == []
