import json
from copy import deepcopy
from pathlib import Path

from backend.app.modules.strapi_products.schema_validation import validate_product_payload


def test_product_schema_accepts_supported_pdp_layout_and_sections():
    payload = {
        "customLayoutPDP": "thirdLayout",
        "tabsBulletSection": {
            "idForScrolling": "bannerSectionPdp",
            "hideSection": False,
            "tabs": [{"id": 12}, {"id": 13}, {"id": 14}],
        },
        "commonQuestions": {
            "idForScrolling": "commonQuestions",
            "dropdownInitialOpen": True,
            "hideSection": False,
            "dropdowns": [{"dropdownTitle": "¿Pregunta?", "richText": "Respuesta"}],
        },
        "contentDescription": "Descripción del producto",
    }

    assert validate_product_payload(payload) == []


def test_product_schema_rejects_unknown_field_and_invalid_layout():
    errors = validate_product_payload({
        "customLayoutPDP": "unknownLayout",
        "fieldThatDoesNotExist": "value",
    })

    assert any("customLayoutPDP" in error and "enum" in error for error in errors)
    assert any("fieldThatDoesNotExist" in error for error in errors)


def test_selected_json_schema_is_used_for_this_validation():
    schema_path = Path(__file__).parents[1] / "app/modules/strapi_products/strapi-product-schema.json"
    selected_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    selected_schema = deepcopy(selected_schema)
    selected_schema["product"]["attributes"].pop("commonQuestions")

    errors = validate_product_payload({"commonQuestions": {"dropdowns": []}}, selected_schema)

    assert any("commonQuestions" in error for error in errors)
