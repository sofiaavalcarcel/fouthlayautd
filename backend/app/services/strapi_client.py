from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx


DEGREE_PREFIXES = ("licenciatura", "maestria", "maestría", "doctorado")


def searchable_program_name(program: str) -> str:
    """Remove a leading academic degree while preserving the original display name."""

    value = " ".join(str(program).strip().split())
    pattern = r"^(?:licenciatura|maestr[ií]a|doctorado)(?:\s+en)?\s+"
    remainder = re.sub(pattern, "", value, count=1, flags=re.IGNORECASE).strip()
    if remainder and remainder.casefold() != value.casefold():
        return remainder
    return value


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class StrapiClientError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "FAILED") -> None:
        super().__init__(message)
        self.kind = kind


class StrapiNotFoundError(StrapiClientError):
    def __init__(self, message: str) -> None:
        super().__init__(message, kind="NOT_FOUND")


class StrapiAmbiguousError(StrapiClientError):
    def __init__(self, message: str) -> None:
        super().__init__(message, kind="AMBIGUOUS")


class StrapiClient:
    def __init__(self, base_url: str, token: str, endpoint: str = "/api/products", timeout: float = 30.0, client: httpx.AsyncClient | None = None) -> None:
        if not base_url or not token:
            raise ValueError("STRAPI_URL y STRAPI_TOKEN son obligatorios.")
        self.endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            follow_redirects=True,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._client.request(method, path, **kwargs)
                if response.status_code not in RETRYABLE_STATUS_CODES or attempt == 2:
                    response.raise_for_status()
                    return response
                await asyncio.sleep(0.25 * (2**attempt))
            except httpx.RequestError as error:
                last_error = error
                if attempt == 2:
                    raise StrapiClientError("No se pudo conectar con Strapi.") from error
                await asyncio.sleep(0.25 * (2**attempt))
            except httpx.HTTPStatusError as error:
                raise StrapiClientError(f"Strapi respondio HTTP {error.response.status_code}.") from error
        raise StrapiClientError("La peticion a Strapi fallo.") from last_error

    async def find_product(self, program: str, locale: str, *, title_field: str = "title", seo_field: str = "seo", status: str = "draft") -> dict[str, Any]:
        if status not in {"draft", "published"}:
            raise ValueError("El estado de contenido de Strapi debe ser draft o published.")
        names = [searchable_program_name(program)]
        if names[0].casefold() != str(program).strip().casefold():
            names.append(" ".join(str(program).strip().split()))
        for name in names:
            for include_locale in (True, False):
                params = {
                    f"filters[{title_field}][$eq]": name,
                    "status": status,
                    f"populate[{seo_field}]": "*",
                    "pagination[pageSize]": 10,
                }
                if include_locale:
                    params["locale"] = locale
                response = await self._request("GET", self.endpoint, params=params)
                entries = response.json().get("data", [])
                if not entries:
                    continue
                if len(entries) > 1:
                    raise StrapiAmbiguousError(f"La busqueda devolvio {len(entries)} registros para {name!r} / {locale}.")
                return entries[0]
        raise StrapiNotFoundError(f"No se encontro el programa {program!r} para {locale}.")

    async def update_product(self, identifier: int | str, attributes: dict[str, Any]) -> dict[str, Any]:
        response = await self._request("PUT", f"{self.endpoint}/{identifier}", json={"data": attributes})
        return response.json()

    async def get_product_sync_attributes(self, identifier: int | str, locale: str) -> dict[str, Any]:
        """Read every product field managed by the PDP description synchronizer."""
        fields = (
            "commonQuestions", "tabsBulletSection", "programs", "downloadProgram", "downloadProgramExecutive", "downloadProgramHybrid",
            "modalities", "education_level", "form_education_levels", "relatedProducts",
            "knowledgeArea", "subjects", "curriculum",
            "resultsDuration", "modalitiesProgram", "programExplanation", "laborField", "studentProfile", "benefits", "academicValidity", "graduates", "activeGraduatesPercentaje",
            "enableExtraButtons", "enableForm",
        )
        params: dict[str, Any] = {"status": "draft", "locale": locale}
        params.update({f"populate[{name}][populate]": "*" for name in fields})
        params.update({
            "populate[programExplanation][populate][coverImageSectionConfig][populate]": "*",
            "populate[programExplanation][populate][coverImageSectionConfig][populate][containerConfig][populate]": "*",
            "populate[programExplanation][populate][coverImageSectionConfig][populate][coverImage][populate]": "*",
            "populate[programExplanation][populate][coverImageSectionConfig][populate][content][populate]": "*",
            "populate[commonQuestions][populate][containerConfig][populate]": "*",
            "populate[commonQuestions][populate][containerConfig][populate][background][populate]": "*",
        })
        response = await self._request("GET", f"{self.endpoint}/{identifier}", params=params)
        data = response.json().get("data", {})
        return data.get("attributes", data)

    async def find_upload_file_by_name(self, name: str) -> dict[str, Any] | None:
        response = await self._request("GET", "/api/upload/files", params={
            "filters[name][$eq]": name, "pagination[pageSize]": 10,
        })
        entries = response.json()
        if not isinstance(entries, list):
            entries = entries.get("data", [])
        if entries:
            return entries[0]
        return None

    async def find_certification_by_rvoe(self, rvoe: str, locale: str) -> dict[str, Any] | None:
        """Find the official academic validation matching an RVOE number."""
        response = await self._request("GET", "/api/certifications", params={
            "filters[description][$containsi]": rvoe,
            "locale": locale,
            "pagination[pageSize]": 10,
        })
        entries = response.json().get("data", [])
        return entries[0] if entries else None

    async def find_certification_by_title(self, title: str, locale: str) -> dict[str, Any] | None:
        response = await self._request("GET", "/api/certifications", params={
            "filters[title][$eq]": title,
            "locale": locale,
            "pagination[pageSize]": 10,
        })
        entries = response.json().get("data", [])
        return entries[0] if entries else None

    async def update_certification(self, identifier: int | str, attributes: dict[str, Any]) -> dict[str, Any]:
        response = await self._request("PUT", f"/api/certifications/{identifier}", json={"data": attributes})
        return response.json().get("data", {})

    async def create_certification(self, title: str, description: str, locale: str, *, logo_id: int | None = None) -> dict[str, Any]:
        data = {
            "title": title,
            "description": description,
            "type": "validation",
            "locale": locale,
        }
        if logo_id is not None:
            data["logo"] = {"id": logo_id}
        response = await self._request("POST", "/api/certifications", json={
            "data": data
        })
        return response.json().get("data", {})

    async def get_product_student_profile(self, identifier: int | str, locale: str) -> dict[str, Any]:
        """Read studentProfile with its nested tab relation expanded."""
        response = await self._request("GET", f"{self.endpoint}/{identifier}", params={
            "status": "draft",
            "locale": locale,
            "populate[studentProfile][populate][tabsData][populate]": "*",
        })
        data = response.json().get("data", {})
        attributes = data.get("attributes", data)
        return attributes.get("studentProfile") or {}

    async def get_product_programs(self, identifier: int | str) -> list[dict[str, Any]]:
        response = await self._request(
            "GET",
            f"{self.endpoint}/{identifier}",
            params={"status": "draft", "populate[programs][populate]": "*"},
        )
        data = response.json().get("data", {})
        attributes = data.get("attributes", data)
        return attributes.get("programs") or []

    async def get_product_download_program(self, identifier: int | str) -> dict[str, Any] | None:
        response = await self._request(
            "GET", f"{self.endpoint}/{identifier}",
            params={"status": "draft", "populate[downloadProgram][populate]": "*"},
        )
        data = response.json().get("data", {})
        return (data.get("attributes", data).get("downloadProgram"))

    async def find_experience_option(self, title_card: str, locale: str) -> dict[str, Any]:
        response = await self._request("GET", "/api/modalities", params={
            "filters[titleCard][$eq]": title_card, "locale": locale,
            "pagination[pageSize]": 10,
        })
        entries = response.json().get("data", [])
        if len(entries) != 1:
            raise StrapiNotFoundError(f"No se encontró una opción de experiencia única: {title_card} / {locale}.")
        return entries[0]

    async def find_relation_by_title(self, endpoint: str, title: str, locale: str) -> dict[str, Any]:
        response = await self._request("GET", f"/api/{endpoint}", params={
            "filters[title][$eq]": title, "locale": locale, "pagination[pageSize]": 10,
        })
        entries = response.json().get("data", [])
        if len(entries) != 1:
            raise StrapiNotFoundError(f"No se encontró una relación única: {title} / {locale}.")
        return entries[0]

    async def get_product_metadata_relations(self, identifier: int | str) -> dict[str, Any]:
        response = await self._request("GET", f"{self.endpoint}/{identifier}", params={
            "status": "draft", "populate[education_level]": "*",
            "populate[form_education_levels]": "*", "populate[knowledgeArea]": "*",
            "populate[relatedProducts]": "*",
        })
        data = response.json().get("data", {})
        return data.get("attributes", data)

    async def get_product_tabs_bullet_section(self, identifier: int | str, locale: str) -> dict[str, Any]:
        response = await self._request("GET", f"{self.endpoint}/{identifier}", params={
            "status": "draft", "locale": locale, "populate[tabsBulletSection][populate]": "*",
        })
        data = response.json().get("data", {})
        attributes = data.get("attributes", data)
        section = attributes.get("tabsBulletSection") or {}
        if isinstance(section, list):
            section = section[0] if section else {}
        tabs = section.get("tabs") or []
        if isinstance(tabs, dict):
            tabs = tabs.get("data", [])
        section = dict(section)
        section["tabs"] = [
            {
                "id": item.get("id"),
                "strapiName": (item.get("attributes", item)).get("strapiName"),
                "locale": (item.get("attributes", item)).get("locale"),
            }
            for item in tabs
            if isinstance(item, dict) and item.get("id") is not None
        ]
        return section

    async def get_product_common_questions(self, identifier: int | str, locale: str) -> dict[str, Any] | None:
        """Fetch the FAQ component and its dropdown components for exact comparison."""
        response = await self._request("GET", f"{self.endpoint}/{identifier}", params={
            "status": "draft", "locale": locale, "populate[commonQuestions][populate]": "*",
        })
        data = response.json().get("data", {})
        attributes = data.get("attributes", data)
        return attributes.get("commonQuestions")

    async def find_bullet_tab_by_strapi_name(self, strapi_name: str, locale: str) -> dict[str, Any]:
        for include_locale in (True, False):
            params = {
                "filters[strapiName][$eq]": strapi_name,
                "pagination[pageSize]": 10,
            }
            if include_locale:
                params["locale"] = locale
            response = await self._request("GET", "/api/bullet-tabs", params=params)
            entries = response.json().get("data", [])
            if not entries:
                continue
            if len(entries) > 1:
                raise StrapiAmbiguousError(f"Hay {len(entries)} pestañas llamadas {strapi_name!r}.")
            return entries[0]
        raise StrapiNotFoundError(f"No se encontró la pestaña {strapi_name!r} para {locale}.")

    async def get_bullet_tab_by_strapi_name(self, strapi_name: str, locale: str) -> dict[str, Any] | None:
        """Find one exact Bullet Tab and populate its editable content components."""
        for include_locale in (True, False):
            params = {
                "filters[strapiName][$eq]": strapi_name,
                "pagination[pageSize]": 10,
                "populate[content][on][section.bullets][populate][bullets][populate]": "*",
                "populate[content][on][section.bullets][populate][coverImage][populate][desktop][populate]": "*",
                "populate[title]": "*",
            }
            if include_locale:
                params["locale"] = locale
            response = await self._request("GET", "/api/bullet-tabs", params=params)
            entries = response.json().get("data", [])
            if not entries:
                continue
            if len(entries) > 1:
                raise StrapiAmbiguousError(f"Hay {len(entries)} pestañas llamadas {strapi_name!r}.")
            return entries[0]
        return None

    async def get_bullet_tab_by_id(self, identifier: int | str) -> dict[str, Any]:
        """Fetch an already-related tab so updates stay scoped to its product relation."""
        response = await self._request("GET", f"/api/bullet-tabs/{identifier}", params={
            "status": "draft",
            "populate[content][on][section.bullets][populate][bullets][populate]": "*",
            "populate[content][on][section.bullets][populate][coverImage][populate][desktop][populate]": "*",
            "populate[title]": "*",
        })
        return response.json().get("data", {})

    async def find_localized_bullet_tab_by_strapi_name(self, strapi_name: str, locale: str) -> dict[str, Any] | None:
        """Find an exact tab in one locale without falling back to another country."""
        response = await self._request("GET", "/api/bullet-tabs", params={
            "filters[strapiName][$eq]": strapi_name,
            "locale": locale,
            "pagination[pageSize]": 10,
            "populate[content][on][section.bullets][populate][bullets][populate]": "*",
            "populate[content][on][section.bullets][populate][coverImage][populate][desktop][populate]": "*",
            "populate[title]": "*",
        })
        entries = response.json().get("data", [])
        if len(entries) > 1:
            raise StrapiAmbiguousError(f"Hay {len(entries)} pestañas llamadas {strapi_name!r} para {locale}.")
        return entries[0] if entries else None

    async def find_bullet_tab_template(self, strapi_prefix: str, locale: str) -> dict[str, Any]:
        """Find a same-locale tab of the same kind, preferring one with a desktop image."""
        params = {
            "filters[strapiName][$containsi]": strapi_prefix,
            "locale": locale,
            "pagination[pageSize]": 100,
            "populate[content][on][section.bullets][populate][bullets][populate]": "*",
            "populate[content][on][section.bullets][populate][coverImage][populate][desktop][populate]": "*",
            "populate[title]": "*",
        }
        response = await self._request("GET", "/api/bullet-tabs", params=params)
        entries = response.json().get("data", [])
        matches = [
            entry for entry in entries
            if str((entry.get("attributes", entry)).get("strapiName", "")).casefold().startswith(strapi_prefix.casefold())
        ]
        for entry in matches:
            attributes = entry.get("attributes", entry)
            component = next((item for item in attributes.get("content") or [] if item.get("__component") == "section.bullets"), {})
            cover = component.get("coverImage") or {}
            desktop = cover.get("desktop") or {}
            image = desktop.get("image") or {}
            if isinstance(image, dict) and isinstance(image.get("data"), dict):
                image = image["data"]
            if isinstance(image, dict) and image.get("id") is not None:
                return entry
        if matches:
            return matches[0]
        raise StrapiNotFoundError(f"No se encontró una pestaña de referencia para {strapi_prefix!r} en {locale}.")

    async def create_bullet_tab(self, attributes: dict[str, Any]) -> dict[str, Any]:
        response = await self._request("POST", "/api/bullet-tabs", json={"data": attributes})
        return response.json().get("data", {})

    async def update_bullet_tab(self, identifier: int | str, attributes: dict[str, Any]) -> dict[str, Any]:
        response = await self._request("PUT", f"/api/bullet-tabs/{identifier}", json={"data": attributes})
        return response.json().get("data", {})

    async def find_subject(self, title: str, locale: str) -> dict[str, Any] | None:
        for include_locale in (True, False):
            params = {"filters[title][$eq]": title, "pagination[pageSize]": 10}
            if include_locale:
                params["locale"] = locale
            response = await self._request("GET", "/api/subjects", params=params)
            entries = response.json().get("data", [])
            if entries:
                # Match the Strapi relation picker: select the first option
                # returned when duplicate titles exist.
                return entries[0]
        response = await self._request("GET", "/api/subjects", params={
            "filters[title][$containsi]": title, "pagination[pageSize]": 10,
        })
        entries = response.json().get("data", [])
        if entries:
            return entries[0]
        return None

    async def create_subject(self, title: str, locale: str) -> dict[str, Any]:
        response = await self._request("POST", "/api/subjects", json={"data": {"title": title, "locale": locale}})
        return response.json().get("data", {})

    async def update_product_programs(self, identifier: int | str, programs: list[dict[str, Any]]) -> dict[str, Any]:
        """Replace the nested Programas components while preserving component ids."""
        return await self.update_product(identifier, {"programs": programs})

    async def update_product_descriptions(
        self,
        identifier: int | str,
        short_description: str,
        long_description: str,
    ) -> dict[str, Any]:
        """Update only the two PDP description fields on a product draft."""

        return await self.update_product(
            identifier,
            {
                "shortDescription": short_description,
                "longDescription": long_description,
            },
        )

    async def update_product_content_description(self, identifier: int | str, content_description: str) -> dict[str, Any]:
        """Update only the contentDescription PDP section."""
        return await self.update_product(identifier, {"contentDescription": content_description})

