from __future__ import annotations

from collections import Counter
from typing import Any, Callable

from ...services.logging_service import get_logger
from ...services.strapi_client import StrapiClientError, StrapiClient, StrapiAmbiguousError, StrapiNotFoundError
from .canonical import add_country_to_canonical
from .models import ProductResult, ProductRow, ProductSummary


class StrapiProductRunner:
    def __init__(self, client: StrapiClient, country: str, locale: str, country_slugs: dict[str, str], *, dry_run: bool = True, expected_host: str = "utel.edu.mx", title_field: str = "title", seo_field: str = "seo", canonical_field: str = "LinkCanonical", status: str = "draft", progress_callback: Callable[[str], None] | None = None) -> None:
        self.client = client
        self.country = country
        self.locale = locale
        self.country_slugs = country_slugs
        self.dry_run = dry_run
        self.expected_host = expected_host
        self.title_field = title_field
        self.seo_field = seo_field
        self.canonical_field = canonical_field
        self.status = status
        self.progress_callback = progress_callback
        self.logger = get_logger()

    async def process(self, row: ProductRow) -> ProductResult:
        if self.progress_callback:
            self.progress_callback(f"Procesando: {row.program}")
        context = {"sheet": row.sheet, "row": row.row_number, "program": row.program, "country": self.country}
        try:
            product = await self.client.find_product(row.program, self.locale, title_field=self.title_field, seo_field=self.seo_field, status=self.status)
            attributes = product.get("attributes") or {}
            seo = attributes.get(self.seo_field)
            if not isinstance(seo, dict):
                raise ValueError("El componente SEO no existe.")
            old_canonical = seo.get(self.canonical_field)
            if not old_canonical:
                raise ValueError("LinkCanonical esta vacio o no existe.")

            new_canonical = add_country_to_canonical(old_canonical, self.country, self.country_slugs, self.expected_host)
            if new_canonical == old_canonical:
                result = ProductResult(row.sheet, row.row_number, row.program, self.country, "SKIPPED", old_canonical, old_canonical, "El pais ya estaba incluido.")
            else:
                if not self.dry_run:
                    identifier = product.get("id") or product.get("documentId")
                    if identifier is None:
                        raise ValueError("El producto no tiene id ni documentId.")
                    # Solo se envia el componente SEO; el resto de atributos queda intacto.
                    updated_seo = dict(seo)
                    updated_seo[self.canonical_field] = new_canonical
                    await self.client.update_product(identifier, {self.seo_field: updated_seo})
                result = ProductResult(row.sheet, row.row_number, row.program, self.country, "DRY_RUN" if self.dry_run else "UPDATED", old_canonical, new_canonical)
            self.logger.info("Strapi product result %s", {**context, "status": result.status})
            return result
        except StrapiNotFoundError as error:
            return self._failure(row, "NOT_FOUND", str(error))
        except StrapiAmbiguousError as error:
            return self._failure(row, "AMBIGUOUS", str(error))
        except ValueError as error:
            return self._failure(row, "INVALID_DATA", str(error))
        except StrapiClientError as error:
            return self._failure(row, "FAILED", str(error))
        except Exception as error:  # noqa: BLE001
            self.logger.exception("Unexpected Strapi product error: %s", context)
            return self._failure(row, "FAILED", "Error inesperado al procesar la fila.")

    def _failure(self, row: ProductRow, status: str, message: str) -> ProductResult:
        self.logger.warning("Strapi product result %s", {"sheet": row.sheet, "row": row.row_number, "program": row.program, "country": self.country, "status": status, "message": message})
        return ProductResult(row.sheet, row.row_number, row.program, self.country, status, message=message)

    async def run(self, rows: list[ProductRow]) -> tuple[list[ProductResult], ProductSummary]:
        results = [await self.process(row) for row in rows]
        counts = Counter(result.status for result in results)
        summary = ProductSummary(
            total=len(results), updated=counts["UPDATED"], dry_run=counts["DRY_RUN"], skipped=counts["SKIPPED"],
            not_found=counts["NOT_FOUND"], ambiguous=counts["AMBIGUOUS"], invalid_data=counts["INVALID_DATA"], failed=counts["FAILED"],
        )
        return results, summary

