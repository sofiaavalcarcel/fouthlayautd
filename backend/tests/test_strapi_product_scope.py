import pytest

from backend.app.modules.strapi_products.models import ProductRow
from backend.app.modules.strapi_products.spreadsheet import select_product_rows


@pytest.fixture
def rows():
    return [ProductRow("Productos", index + 2, f"Producto {index + 1}") for index in range(5)]


def test_two_product_scope_keeps_the_first_two_rows(rows):
    selected = select_product_rows(rows, "2")

    assert [row.program for row in selected] == ["Producto 1", "Producto 2"]


def test_custom_scope_keeps_the_requested_number_of_rows(rows):
    selected = select_product_rows(rows, "3")

    assert [row.program for row in selected] == ["Producto 1", "Producto 2", "Producto 3"]


def test_all_product_scope_keeps_every_row_in_excel_order(rows):
    selected = select_product_rows(rows, "all")

    assert selected == rows


def test_unknown_product_scope_is_rejected(rows):
    with pytest.raises(ValueError, match="product_scope debe ser un entero positivo o all"):
        select_product_rows(rows, "abc")
