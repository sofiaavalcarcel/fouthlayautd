from backend.app.modules.strapi_products.sync_plan import payload_matches, plan_change


def test_payload_match_ignores_extra_read_fields_and_unwraps_strapi_relations():
    current = {
        "tabs": {"data": [
            {"id": 12, "attributes": {"strapiName": "Perfil egreso"}},
        ]},
        "knowledgeArea": {"data": {"id": 7, "attributes": {"title": "Negocios"}}},
    }
    desired = {"tabs": [{"id": 12}], "knowledgeArea": 7}
    assert payload_matches(current, desired)


def test_payload_match_detects_nested_faq_text_difference():
    current = {"dropdowns": [{"id": 2, "dropdownTitle": "¿Duración?", "richText": "44 meses"}]}
    desired = {"dropdowns": [{"id": 2, "dropdownTitle": "¿Duración?", "richText": "48 meses"}]}
    assert not payload_matches(current, desired)


def test_change_plan_keeps_a_reviewable_before_and_after_value():
    change = plan_change("commonQuestions", {"value": "old"}, {"value": "new"})
    assert change == {
        "field": "commonQuestions",
        "action": "update",
        "before": {"value": "old"},
        "after": {"value": "new"},
        "verified": None,
    }
