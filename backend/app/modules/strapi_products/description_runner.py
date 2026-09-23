from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse
from typing import Callable

import httpx

from ...services.logging_service import get_logger
from ...services.google_drive_client import GoogleDriveClient, GoogleDriveClientError, google_document_id
from ...services.strapi_client import StrapiAmbiguousError, StrapiClient, StrapiClientError, StrapiNotFoundError
from .models import ProductResult, ProductRow, ProductSummary
from .pdp_description import LaborFieldContent, extract_active_graduates_percentage, extract_content_description, extract_curriculum, extract_description, extract_graduate_testimonies, extract_labor_field_content, extract_program_explanation, extract_program_durations, extract_rvoe_numbers, extract_subjects
from .common_questions import build_common_questions_payload, common_questions_match, extract_common_questions
from .bullet_tabs import TAB_PREFIXES, build_bullet_tab_payload, extract_bullet_tabs, extract_study_modalities, has_desktop_cover_image, linked_tab_prefix
from .fichas import FichasLookup
from .balancer_catalog import BalancerCatalogError
from .sync_plan import payload_matches, plan_change
from .schema_validation import validate_product_payload


EXPERIENCE_SUFFIX = {"Argentina": "Arg", "México": "", "Mexico": "", "Colombia": "Col", "Ecuador": "Ecu", "Perú": "Per", "Peru": "Per", "Chile": "Chile", "El Salvador": "SV", "Panamá": "Pan", "Panama": "Pan", "Bolivia": "Bol", "USA": "USA", "República Dominicana": "Dom", "Republica Dominicana": "Dom"}
FIXED_BENEFITS = (
    ("UilAward", "Título con validez oficial SEP"),
    ("UilBriefcaseAlt", "Especialidad única en México"),
    ("UilGraduationCap", "Diseñada por especialistas del sector"),
)


def program_option_specs(durations: list[str]) -> tuple[tuple[str, str, str], ...]:
    """Map extracted durations to the program cards written to Strapi.

    The one- and two-option mappings remain compatible with existing PDPs. For the
    current three-option PDP, the shortest option is Súper Intensivo, the
    middle option is Intensivo and the longest is Base. Unknown extra options
    still receive their own card using the duration as a fallback title.
    """
    if not durations:
        raise ValueError("Se necesita al menos una duración para construir los programas.")

    descriptions = {
        "Programa Intensivo": "Hasta 3 materias.  <br/>\nPara quienes buscan un equilibrio ideal entre su vida profesional y personal.",
        "Programa Base": "Hasta 2 materias.  <br/>\nPara quienes buscan avanzar a un ritmo constante y una carga académica más ligera.",
    }
    if len(durations) == 1:
        names = (f"Programa {durations[0]}",)
    elif len(durations) == 2:
        names = ("Programa Intensivo", "Programa Base")
    elif len(durations) == 3:
        names = ("Programa Súper Intensivo", "Programa Intensivo", "Programa Base")
    else:
        names = tuple(f"Programa {duration}" for duration in durations)

    return tuple(
        (name, duration, descriptions.get(name, f"Duración: {duration}."))
        for name, duration in zip(names, durations)
    )


def experience_title(country: str) -> str:
    suffix = EXPERIENCE_SUFFIX.get(country, country)
    return f"En línea Home2026{(' ' + suffix) if suffix else ''}"


def experience_title_candidates(modality: str, country: str) -> tuple[str, ...]:
    """Return the Strapi title variants used by the modality catalog."""
    suffix = EXPERIENCE_SUFFIX.get(country, country)
    normalized = modality.casefold().replace("í", "i").strip()
    if normalized == "en linea":
        return (experience_title(country),)
    if normalized == "ejecutiva":
        base = f"Ejecutiva Home 2026{(' ' + suffix) if suffix else ''}"
        return (base, base.replace("Home 2026", "Home2026"))
    if normalized == "hibrida":
        base = f"Híbrida Home2026{(' ' + suffix) if suffix else ''}"
        return (base, base.replace("Híbrida", "Hibrida"), base.replace("Híbrida ", "Híbrida"), base.replace("Híbrida ", "Hibrida"))
    return ()


def format_duration_summary(durations: list[str]) -> str:
    """Format all document durations as one resultsDuration label."""
    values = [duration.removesuffix(" meses").removesuffix(" mes") for duration in durations]
    if len(values) == 1:
        summary = values[0]
    elif len(values) == 2:
        summary = f"{values[0]} y {values[1]}"
    else:
        summary = f"{', '.join(values[:-1])} y {values[-1]}"
    return f"Duración: {summary} meses"


def format_duration_options(durations: list[str]) -> str:
    """Format durations for the modalitiesProgram description."""
    values = [duration.removesuffix(" meses").removesuffix(" mes") for duration in durations]
    options = [f"{value} meses" for value in values]
    if len(options) <= 1:
        return options[0] if options else ""
    if len(options) == 2:
        return f"{options[0]} o {options[1]}"
    return f"{', '.join(options[:-1])} o {options[-1]}"


def format_modalities_summary(modalities: tuple[str, ...]) -> str:
    """Format FT modality labels as the overview title."""
    labels = ["En línea" if modality.casefold().replace("í", "i") == "en linea" else modality for modality in modalities]
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} o {labels[1]}"
    return f"{', '.join(labels[:-1])} o {labels[-1]}"


def education_level_title(program: str) -> str:
    value = program.casefold().strip()
    if value.startswith("licenciatura"):
        return "Licenciatura"
    if value.startswith("maestr"):
        return "Maestría"
    if value.startswith("doctorado"):
        return "Doctorado"
    raise ValueError(f"No se pudo determinar el nivel educativo de {program}.")


def program_article(program: str) -> str:
    return "el" if program.casefold().startswith(("doctorado", "bachillerato")) else "la"


def merge_labor_field_content(contents: list[LaborFieldContent]) -> LaborFieldContent:
    """Merge PDP and FT labor sections while preserving source order and removing duplicates."""
    areas: list[tuple[str, str]] = []
    positions: list[str] = []
    market: list[str] = []
    seen_areas: set[tuple[str, str]] = set()
    seen_positions: set[str] = set()
    seen_market: set[str] = set()
    for content in contents:
        for title, description in content.areas:
            key = (title.casefold(), description.casefold())
            if key not in seen_areas:
                seen_areas.add(key)
                areas.append((title, description))
        for position in content.positions:
            key = position.casefold()
            if key not in seen_positions:
                seen_positions.add(key)
                positions.append(position)
        if content.market_description and content.market_description.casefold() not in seen_market:
            seen_market.add(content.market_description.casefold())
            market.append(content.market_description)
    return LaborFieldContent(tuple(areas), tuple(positions), "\n\n".join(market))


def build_student_profile_payload(current: dict | None, program: str, tab_ids: list[int]) -> dict:
    """Build the student profile with only the ingreso and egreso tabs."""
    payload = deepcopy(current or {})
    payload.pop("__component", None)
    tabs_data = deepcopy(payload.get("tabsData") or {})
    tabs_data["tabs"] = [{"id": tab_id} for tab_id in tab_ids]
    payload["tabsData"] = tabs_data
    payload["titleSection"] = f"Perfil del estudiante en {program}"
    # Strapi's captured enum uses this casing, although the UI label is
    # commonly written as "tabbedSplitLayout".
    payload["layout"] = "TabbedSplitLayout"
    return payload


def _program_article(program: str) -> str:
    normalized_program = program.strip().casefold()
    return "el" if normalized_program.startswith(("doctorado", "master", "máster", "diplomado")) else "la"


def build_benefits_payload(current: dict | None, program: str) -> dict:
    """Build the same three official benefits for every product."""
    payload = deepcopy(current or {})
    title = deepcopy(payload.get("title") or {})
    title["desktop"] = f"Beneficios de {_program_article(program)} {program}"
    title["chakraConfig"] = {"color": "black"}
    payload["title"] = title
    current_items = payload.get("benefits") or []
    items = []
    for icon_name, text in FIXED_BENEFITS:
        current_item = next((item for item in current_items if item.get("text") == text), {})
        item = deepcopy(current_item)
        icon = deepcopy(item.get("icon") or {})
        icon["name"] = icon_name
        item["icon"] = icon
        item["text"] = text
        items.append(item)
    payload["benefits"] = items
    return payload


def build_graduates_payload(current: dict | None, program: str, testimonies: list[tuple[str, str]]) -> dict:
    """Build graduate testimonials with no date and five stars."""
    payload = deepcopy(current or {})
    title = deepcopy(payload.get("title") or {})
    title["desktop"] = f"Testimonios de egresados de {_program_article(program)} {program}"
    payload["title"] = title
    current_entries = payload.get("graduates") or []
    graduates = []
    for name, comment in testimonies:
        existing = next((item for item in current_entries if item.get("name") == name), {})
        item = deepcopy(existing)
        item["name"] = name
        item["date"] = None
        item["comment"] = comment
        item["stars"] = 5
        graduates.append(item)
    payload["graduates"] = graduates
    cta = deepcopy(payload.get("CTA") or {})
    cta["url"] = "#formSection"
    cta["children"] = "Empieza tu camino"
    payload["CTA"] = cta
    return payload


def student_profile_matches(current: dict | None, desired: dict) -> bool:
    """Compare studentProfile while accepting Strapi's relation `{data: [...]}` shape."""
    current = current or {}
    if current.get("titleSection") != desired.get("titleSection") or current.get("layout") != desired.get("layout"):
        return False
    current_tabs = ((current.get("tabsData") or {}).get("tabs") or [])
    if isinstance(current_tabs, dict):
        current_tabs = current_tabs.get("data") or []
    current_ids = [item.get("id") for item in current_tabs if isinstance(item, dict)]
    desired_ids = [item.get("id") for item in ((desired.get("tabsData") or {}).get("tabs") or [])]
    return current_ids == desired_ids


class StrapiDescriptionRunner:
    def __init__(self, client: StrapiClient, country: str, locale: str, *, dry_run: bool = True, short_field: str = "shortDescription", long_field: str = "longDescription", content_field: str = "contentDescription", programs_field: str = "programs", download_program_field: str = "downloadProgram", experience_field: str = "modalities", education_field: str = "education_level", related_products_field: str = "relatedProducts", form_education_field: str = "form_education_levels", knowledge_area_field: str = "knowledgeArea", subjects_field: str = "subjects", results_duration_field: str = "resultsDuration", siu_key_field: str = "siuKey", banner_key_field: str = "bannerKey", siu_key_lookup=None, title_field: str = "title", status: str = "draft", google_drive_client: GoogleDriveClient | None = None, fichas_lookup: FichasLookup | None = None, product_schema: dict | None = None, progress_callback: Callable[[str], None] | None = None, stg_environment: bool = False) -> None:
        self.client = client
        self.country = country
        self.locale = locale
        self.dry_run = dry_run
        self.short_field = short_field
        self.long_field = long_field
        self.content_field = content_field
        self.programs_field = programs_field
        self.download_program_field = download_program_field
        self.experience_field = experience_field
        self.education_field = education_field
        self.related_products_field = related_products_field
        self.form_education_field = form_education_field
        self.knowledge_area_field = knowledge_area_field
        self.subjects_field = subjects_field
        self.results_duration_field = results_duration_field
        self.siu_key_field = siu_key_field
        self.banner_key_field = banner_key_field
        self.siu_key_lookup = siu_key_lookup
        self.fichas_lookup = fichas_lookup
        self.product_schema = product_schema
        self.title_field = title_field
        self.status = status
        self.google_drive_client = google_drive_client
        self.progress_callback = progress_callback
        self.stg_environment = stg_environment
        self.logger = get_logger()

    async def _document_content(self, source: str) -> tuple[str, bytes]:
        if not source:
            raise ValueError("La fila no tiene Documento PDP.")
        parsed = urlparse(source)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            document_id = google_document_id(source)
            if document_id and self.google_drive_client and self.google_drive_client.has_any_configuration and not self.google_drive_client.is_configured:
                raise GoogleDriveClientError(
                    "La configuración OAuth de Google Drive está incompleta. Define las tres variables "
                    "GOOGLE_DRIVE_CLIENT_ID, GOOGLE_DRIVE_CLIENT_SECRET y GOOGLE_DRIVE_REFRESH_TOKEN."
                )
            if document_id and self.google_drive_client and self.google_drive_client.is_configured:
                return "google-drive-document.docx", await self.google_drive_client.export_docx(document_id)
            request_url = self._google_doc_export_url(source)
            async with httpx.AsyncClient(follow_redirects=True, timeout=35) as client:
                try:
                    response = await client.get(request_url)
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    if document_id and error.response.status_code in {401, 403}:
                        raise GoogleDriveClientError(
                            "El documento de Google Drive es privado. Configura las credenciales OAuth "
                            "de Google Drive en .env para leerlo desde el backend."
                        ) from error
                    raise
                return "google-drive-document.docx", response.content
        path = Path(source.strip('\\"'))
        if not path.is_file():
            raise ValueError(f"No se encontro el Documento PDP: {source}")
        return str(path), path.read_bytes()

    @staticmethod
    def _google_doc_export_url(source: str) -> str:
        """Convert a Google Docs edit/share URL to a downloadable DOCX URL."""
        parsed = urlparse(source)
        if parsed.netloc.casefold() not in {"docs.google.com", "drive.google.com"}:
            return source
        parts = [part for part in parsed.path.split("/") if part]
        try:
            document_index = parts.index("document")
            if parts[document_index + 1] != "d":
                return source
            document_id = parts[document_index + 2]
        except (ValueError, IndexError):
            return source
        return f"https://docs.google.com/document/d/{document_id}/export?format=docx"

    async def process(self, row: ProductRow) -> ProductResult:
        if self.progress_callback:
            self.progress_callback(f"Procesando: {row.program}")
        changes: list[dict] = []
        verification: dict = {"ok": None, "performed": False}
        description: str | None = None
        siu_key: str | None = None
        try:
            source, content = await self._document_content(row.document or "")
            bullet_source, bullet_content = source, content
            if row.ft_document:
                bullet_source, bullet_content = await self._document_content(row.ft_document)
            study_modalities = extract_study_modalities(bullet_source, bullet_content)
            labor_sources = [(source, content)]
            if bullet_source != source or bullet_content != content:
                labor_sources.append((bullet_source, bullet_content))
            active_graduates_percentage = extract_active_graduates_percentage(source, content)
            labor_contents: list[LaborFieldContent] = []
            for labor_source, labor_content in labor_sources:
                try:
                    labor_contents.append(extract_labor_field_content(labor_source, labor_content))
                except ValueError:
                    continue
            labor_field_content = merge_labor_field_content(labor_contents)
            rvoe_numbers: list[str] = []
            for validity_source, validity_content in labor_sources:
                for number in extract_rvoe_numbers(validity_source, validity_content):
                    if number not in rvoe_numbers:
                        rvoe_numbers.append(number)
            graduate_testimonies: list[tuple[str, str]] = []
            seen_graduates: set[str] = set()
            for graduate_source, graduate_content in labor_sources:
                for name, comment in extract_graduate_testimonies(graduate_source, graduate_content, row.program):
                    if name.casefold() not in seen_graduates:
                        seen_graduates.add(name.casefold())
                        graduate_testimonies.append((name, comment))
            description = extract_description(row.program, source, content)
            try:
                program_explanation = extract_program_explanation(row.program, source, content)
            except ValueError:
                program_explanation = description
            content_description = extract_content_description(source, content)
            curriculum = extract_curriculum(source, content)
            subjects = extract_subjects(source, content)
            programs_error: str | None = None
            duration_sources_message: str | None = None
            try:
                pdp_durations = extract_program_durations(source, content)
                ft_durations: list[str] = []
                try:
                    ft_durations = extract_program_durations(bullet_source, bullet_content)
                except ValueError:
                    pass
                durations = sorted(
                    set(pdp_durations) | set(ft_durations),
                    key=lambda value: int(value.split()[0]),
                )
                if ft_durations:
                    if set(pdp_durations) == set(ft_durations):
                        duration_sources_message = "Duraciones PDP y FT coinciden"
                    else:
                        added = sorted(set(ft_durations) - set(pdp_durations), key=lambda value: int(value.split()[0]))
                        duration_sources_message = (
                            "Duraciones PDP y FT analizadas; adicionales incorporadas: "
                            + ", ".join(added)
                            if added else "Duraciones PDP y FT analizadas; se conservaron las del PDP"
                        )
            except ValueError as error:
                # Descriptions can still be synchronized when a PDP has no
                # two-duration Programas section; report that section without
                # inventing a second duration.
                durations = []
                programs_error = str(error)
            ficha_url = self.fichas_lookup.find(row.program, self.country) if self.fichas_lookup else None
            product = await self.client.find_product(row.program, self.locale, title_field=self.title_field, seo_field="seo", status=self.status)
            identifier = product.get("id") or product.get("documentId")
            if identifier is None:
                raise ValueError("El producto no tiene id ni documentId.")
            common_questions_payload = None
            faq_matches = None
            faq_entries = extract_common_questions(source, content)
            if faq_entries is not None and hasattr(self.client, "get_product_common_questions"):
                current_faq = await self.client.get_product_common_questions(identifier, self.locale)
                faq_matches = common_questions_match(faq_entries, current_faq)
                common_questions_payload = build_common_questions_payload(faq_entries, current_faq)
            siu_key = None
            if self.siu_key_lookup:
                try:
                    siu_key = await self.siu_key_lookup(row.program)
                except BalancerCatalogError:
                    # If the catalog has duplicate rows for the same degree,
                    # keep the already assigned product key instead of
                    # stopping the entire PDP synchronization. This is safe
                    # because the key belongs to the product currently being
                    # edited and is also what the run would write back.
                    product_attributes = product.get("attributes", product)
                    existing_siu_key = product_attributes.get(self.siu_key_field)
                    if existing_siu_key:
                        siu_key = str(existing_siu_key)
                    else:
                        raise
            tabs_bullet_section_payload = None
            bullet_tab_operations = []
            manages_bullet_tabs = all(
                hasattr(self.client, name)
                for name in (
                    "get_bullet_tab_by_id", "find_bullet_tab_template",
                    "create_bullet_tab", "update_bullet_tab",
                )
            )
            if manages_bullet_tabs and hasattr(self.client, "get_product_tabs_bullet_section"):
                bullet_tab_sections = extract_bullet_tabs(bullet_source, bullet_content)
                section = await self.client.get_product_tabs_bullet_section(identifier, self.locale)
                tab_ids = []
                for tab_prefix in TAB_PREFIXES:
                    tab_name = f"{tab_prefix} {row.program}"
                    linked_matches = [
                        item for item in (section.get("tabs") or [])
                        if item.get("id") is not None
                        and linked_tab_prefix(item.get("strapiName") or "", row.program) == tab_prefix
                    ]
                    if len(linked_matches) > 1:
                        raise StrapiAmbiguousError(f"El producto tiene varias pestañas relacionadas para {tab_prefix!r}.")
                    existing_tab = (
                        await self.client.get_bullet_tab_by_id(linked_matches[0]["id"])
                        if linked_matches else None
                    )
                    if existing_tab is None and hasattr(self.client, "find_localized_bullet_tab_by_strapi_name"):
                        existing_tab = await self.client.find_localized_bullet_tab_by_strapi_name(tab_name, self.locale)
                    template = None
                    if existing_tab is None or (
                        tab_prefix == "Perfil egreso" and not has_desktop_cover_image(existing_tab)
                    ):
                        template = await self.client.find_bullet_tab_template(tab_prefix, self.locale)
                    payload = build_bullet_tab_payload(
                        row.program, bullet_tab_sections[tab_prefix],
                        existing=existing_tab, template=template, locale=self.locale,
                    )
                    bullet_tab_operations.append((existing_tab, payload, tab_name))
                    tab_id = existing_tab.get("id") if existing_tab else None
                    tab_ids.append({"id": tab_id} if tab_id is not None else None)
                tabs_bullet_section_payload = {
                    "idForScrolling": "bannerSectionPdp",
                    "hideSection": section.get("hideSection", False),
                }
                if section.get("id") is not None:
                    tabs_bullet_section_payload["id"] = section["id"]
                if all(tab_ids):
                    tabs_bullet_section_payload["tabs"] = tab_ids
            elif hasattr(self.client, "get_product_tabs_bullet_section") and hasattr(self.client, "find_bullet_tab_by_strapi_name"):
                section = await self.client.get_product_tabs_bullet_section(identifier, self.locale)
                tabs = []
                for tab_prefix in TAB_PREFIXES:
                    tab = await self.client.find_bullet_tab_by_strapi_name(
                        f"{tab_prefix} {row.program}", self.locale
                    )
                    if tab.get("id") is None:
                        raise StrapiNotFoundError(f"La pestaña {tab_prefix!r} no tiene un id válido.")
                    tabs.append({"id": tab["id"]})
                tabs_bullet_section_payload = {
                    "idForScrolling": "bannerSectionPdp",
                    "hideSection": section.get("hideSection", False),
                    "tabs": tabs,
                }
                if section.get("id") is not None:
                    tabs_bullet_section_payload["id"] = section["id"]
            programs_payload: list[dict] | None = None
            if durations:
                existing = await self.client.get_product_programs(identifier)
                program_specs = program_option_specs(durations)
                programs_payload = []
                for title, duration, desktop in program_specs:
                    current = next((item for item in existing if item.get("title") == title), {})
                    component = dict(current)
                    component.update({"title": title, "description": duration})
                    icon = dict(component.get("icon") or {})
                    icon["name"] = "UilClock"
                    icon.setdefault("chakraConfig", None)
                    component["icon"] = icon
                    desktop_mobile = dict(component.get("descriptionDesktopMobile") or {})
                    desktop_mobile["desktop"] = desktop
                    desktop_mobile.setdefault("mobile", "")
                    desktop_mobile.setdefault("chakraConfig", None)
                    component["descriptionDesktopMobile"] = desktop_mobile
                    programs_payload.append(component)
            download_payload = None
            if self.fichas_lookup:
                current_download = await self.client.get_product_download_program(identifier)
                download_payload = dict(current_download or {})
                download_payload["url"] = ficha_url
                button = dict(download_payload.get("buttonDownload") or {})
                button["url"] = ficha_url
                button["children"] = "Descargar ficha"
                download_payload["buttonDownload"] = button
            experience_payload = None
            if hasattr(self.client, "find_experience_option"):
                modalities = study_modalities or ("En línea",)
                experience_payload = []
                for modality in modalities:
                    candidates = experience_title_candidates(modality, self.country)
                    if not candidates:
                        continue
                    experience = None
                    for candidate in candidates:
                        try:
                            experience = await self.client.find_experience_option(candidate, self.locale)
                            break
                        except StrapiNotFoundError:
                            continue
                    if experience is None:
                        raise StrapiNotFoundError(
                            f"No se encontró una experiencia de estudio para {modality!r} / {self.locale}."
                        )
                    experience_payload.append({"id": experience.get("id")})
            metadata_payload = None
            if hasattr(self.client, "get_product_metadata_relations"):
                metadata = await self.client.get_product_metadata_relations(identifier)
                level = await self.client.find_relation_by_title("education-levels", education_level_title(row.program), self.locale)
                form_level = await self.client.find_relation_by_title("form-education-levels", education_level_title(row.program), self.locale)
                area = metadata.get(self.knowledge_area_field) or {}
                area_data = area.get("data", area)
                area_id = area_data.get("id") if isinstance(area_data, dict) else None
                metadata_payload = {
                    self.education_field: {"id": level.get("id")},
                    self.form_education_field: [{"id": form_level.get("id")}],
                    self.related_products_field: [{"id": identifier}],
                }
                if area_id is not None:
                    # Strapi expects the relation id directly for this field.
                    metadata_payload[self.knowledge_area_field] = area_id
            missing_subjects: list[str] = []
            created_subjects: list[str] = []
            subject_changes: list[dict] = []
            subjects_payload = None
            curriculum_payload = None
            subject_ids: dict[str, int] = {}
            if hasattr(self.client, "find_subject") and subjects:
                subjects_payload = []
                for subject in subjects:
                    found = await self.client.find_subject(subject, self.locale)
                    if found is None:
                        if self.dry_run:
                            missing_subjects.append(subject)
                            subject_changes.append(plan_change(f"{self.subjects_field}.{subject}", None, subject, action="create"))
                        else:
                            found = await self.client.create_subject(subject, self.locale)
                            created_subjects.append(subject)
                            subject_change = plan_change(f"{self.subjects_field}.{subject}", None, subject, action="create")
                            subject_change["created_id"] = found.get("id")
                            subject_changes.append(subject_change)
                            if found.get("id") is not None:
                                subject_ids[subject] = found["id"]
                            subjects_payload.append({"id": found.get("id")})
                    else:
                        if found.get("id") is not None:
                            subject_ids[subject] = found["id"]
                        subjects_payload.append({"id": found.get("id")})
            current_attributes = (
                await self.client.get_product_sync_attributes(identifier, self.locale)
                if hasattr(self.client, "get_product_sync_attributes")
                else product.get("attributes", product)
            )
            stg_download_cleanup: dict[str, dict | None] = {}
            if self.stg_environment:
                for field_name in ("downloadProgramExecutive", "downloadProgramHybrid"):
                    if current_attributes.get(field_name) is not None:
                        stg_download_cleanup[field_name] = None
            changes.extend(subject_changes)

            benefits_payload = None
            if hasattr(self.client, "get_product_sync_attributes"):
                benefits_payload = build_benefits_payload(current_attributes.get("benefits"), row.program)
                if not payload_matches(current_attributes.get("benefits"), benefits_payload):
                    changes.append(plan_change("benefits", current_attributes.get("benefits"), benefits_payload))

            graduates_payload = None
            if graduate_testimonies and hasattr(self.client, "get_product_sync_attributes"):
                graduates_payload = build_graduates_payload(
                    current_attributes.get("graduates"), row.program, graduate_testimonies
                )

            academic_validity_payload = None
            if hasattr(self.client, "find_certification_by_rvoe"):
                certification = None
                matched_rvoe = None
                for rvoe in rvoe_numbers:
                    certification = await self.client.find_certification_by_rvoe(rvoe, self.locale)
                    if certification and certification.get("id") is not None:
                        matched_rvoe = rvoe
                        break
                current_academic_validity = deepcopy(current_attributes.get("academicValidity") or {})
                if certification and certification.get("id") is not None:
                    specific_title = f"Título Oficial en México {row.program}"
                    specific_certification = None
                    if hasattr(self.client, "find_certification_by_title"):
                        specific_certification = await self.client.find_certification_by_title(specific_title, self.locale)
                    logo = None
                    if hasattr(self.client, "find_upload_file_by_name"):
                        logo = await self.client.find_upload_file_by_name("icono-bandera-mexico.svg")
                        if logo is None or logo.get("id") is None:
                            raise StrapiNotFoundError("No se encontró el asset icono-bandera-mexico.svg en Strapi.")
                    if specific_certification is None and not self.dry_run and hasattr(self.client, "create_certification"):
                        certification_attributes = certification.get("attributes", certification)
                        specific_certification = await self.client.create_certification(
                            specific_title,
                            certification_attributes.get("description", ""),
                            self.locale,
                            logo_id=logo["id"] if logo else None,
                        )
                    elif specific_certification and not self.dry_run and hasattr(self.client, "update_certification") and logo:
                        existing_logo = (specific_certification.get("attributes", specific_certification).get("logo") or {})
                        existing_logo_data = existing_logo.get("data", existing_logo) if isinstance(existing_logo, dict) else {}
                        if existing_logo_data.get("id") != logo["id"]:
                            await self.client.update_certification(specific_certification["id"], {"logo": {"id": logo["id"]}})
                    elif specific_certification is None and self.dry_run:
                        changes.append(plan_change(
                            "academicValidity.validations",
                            None,
                            {"title": specific_title, "rvoe": matched_rvoe},
                            action="create",
                        ))
                    title = deepcopy(current_academic_validity.get("title") or {})
                    title["desktop"] = "Validez académica"
                    current_academic_validity["title"] = title
                    # The product must reference exactly one validation: the
                    # program-specific official title. The generic RVOE
                    # certification remains available globally, but it must
                    # not remain linked in this product's validations.
                    specific_validation_id = (
                        specific_certification.get("id")
                        if specific_certification and specific_certification.get("id") is not None
                        else None
                    )
                    current_academic_validity["validations"] = (
                        [{"id": specific_validation_id}] if specific_validation_id is not None else []
                    )
                    academic_validity_payload = current_academic_validity

            student_profile_payload = None
            profile_tab_ids = [
                existing_tab.get("id")
                for existing_tab, _, tab_name in bullet_tab_operations
                if tab_name.startswith(("Perfil ingreso ", "Perfil egreso ")) and existing_tab and existing_tab.get("id") is not None
            ]
            if len(profile_tab_ids) == 2:
                student_profile_payload = build_student_profile_payload(
                    current_attributes.get("studentProfile"), row.program, profile_tab_ids
                )
                if not payload_matches(current_attributes.get("studentProfile"), student_profile_payload):
                    changes.append(plan_change("studentProfile", current_attributes.get("studentProfile"), student_profile_payload))

            results_duration_payload = None
            if durations:
                current_duration = current_attributes.get(self.results_duration_field)
                results_duration_payload = deepcopy(current_duration or {})
                icon = dict(results_duration_payload.get("icon") or {})
                icon["name"] = "UilClock"
                results_duration_payload["icon"] = icon
                results_duration_payload["text"] = format_duration_summary(durations)

            program_explanation_payload = None
            if hasattr(self.client, "find_upload_file_by_name"):
                media = await self.client.find_upload_file_by_name("Asset-¿QuéEs.png")
                if media is None or media.get("id") is None:
                    raise StrapiNotFoundError("No se encontró el asset Asset-¿QuéEs.png en Strapi.")
                current_program_explanation = current_attributes.get("programExplanation") or {}
                current_section = current_program_explanation.get("coverImageSectionConfig") or {}
                section = deepcopy(current_section)
                section.pop("__component", None)
                container = deepcopy(section.get("containerConfig") or {})
                background = deepcopy(container.get("background") or {})
                background.update({"color": "#06BA06", "size": "contain"})
                container["background"] = background
                section["containerConfig"] = container
                cover = deepcopy(section.get("coverImage") or {})
                desktop_image = deepcopy(cover.get("desktop") or {})
                desktop_image["image"] = {"id": media["id"]}
                desktop_image["objectFit"] = "contain"
                cover["desktop"] = desktop_image
                section["coverImage"] = cover
                section.setdefault("imagePositionDesktop", "right")
                section.setdefault("imagePositionMobile", "top")
                section.setdefault("hideSection", False)
                section_content = deepcopy(section.get("content") or {})
                title = deepcopy(section_content.get("title") or {})
                title["desktop"] = f"¿Qué es {program_article(row.program)} {row.program}?"
                title["chakraConfig"] = {"as": "h3", "color": "white"}
                subtitle = deepcopy(section_content.get("subtitle") or {})
                subtitle["desktop"] = program_explanation
                subtitle["chakraConfig"] = {"color": "white", "fontSize": "16px", "fontWeight": "400"}
                section_content["title"] = title
                section_content["subtitle"] = subtitle
                section["content"] = section_content
                program_explanation_payload = deepcopy(current_program_explanation)
                program_explanation_payload.pop("__component", None)
                program_explanation_payload["coverImageSectionConfig"] = section

            labor_field_payload = None
            if labor_field_content.areas or labor_field_content.positions or labor_field_content.market_description:
                if not hasattr(self.client, "find_upload_file_by_name"):
                    raise StrapiNotFoundError("El cliente de Strapi no permite buscar OportunidadesProfesionales.png.")
                labor_image = await self.client.find_upload_file_by_name("OportunidadesProfesionales.png")
                if labor_image is None or labor_image.get("id") is None:
                    raise StrapiNotFoundError("No se encontró el asset OportunidadesProfesionales.png en Strapi.")
                current_labor = deepcopy(current_attributes.get("laborField") or {})

                def responsive_text(current: dict | None, desktop: str) -> dict:
                    value = deepcopy(current or {})
                    value["desktop"] = desktop
                    return value

                labor_field_payload = current_labor
                labor_field_payload["mainTitle"] = responsive_text(
                    labor_field_payload.get("mainTitle"), "Oportunidades Profesionales"
                )
                labor_field_payload["areasToWorkTitle"] = responsive_text(
                    labor_field_payload.get("areasToWorkTitle"), "Áreas en las que vas a poder trabajar"
                )
                labor_field_payload["positionsTitle"] = responsive_text(
                    labor_field_payload.get("positionsTitle"), "Puestos que podrías ocupar"
                )
                labor_field_payload["marketTitle"] = responsive_text(
                    labor_field_payload.get("marketTitle"), "Datos del mercado laboral"
                )
                if labor_field_content.market_description:
                    labor_field_payload["marketDescription"] = responsive_text(
                        labor_field_payload.get("marketDescription"), labor_field_content.market_description
                    )

                image = deepcopy(labor_field_payload.get("image") or {})
                desktop_image = deepcopy(image.get("desktop") or {})
                desktop_image["image"] = {"id": labor_image["id"]}
                desktop_image["objectFit"] = "contain"
                image["desktop"] = desktop_image
                labor_field_payload["image"] = image

                current_areas = labor_field_payload.get("areasToWorkItems") or []
                area_items = []
                for title, area_description in labor_field_content.areas:
                    existing_area = next((item for item in current_areas if item.get("title") == title), {})
                    item = deepcopy(existing_area)
                    item["title"] = title
                    item["description"] = area_description
                    area_icon = deepcopy(item.get("icon") or {})
                    area_icon["name"] = "UilCheckSquare"
                    item["icon"] = area_icon
                    item.setdefault("iconMobile", None)
                    area_items.append(item)
                labor_field_payload["areasToWorkItems"] = area_items

                current_positions = labor_field_payload.get("positionsTags") or []
                position_tags = []
                for position in labor_field_content.positions:
                    existing_tag = next((item for item in current_positions if item.get("text") == position), {})
                    tag = deepcopy(existing_tag)
                    tag["text"] = position
                    position_tags.append(tag)
                labor_field_payload["positionsTags"] = position_tags

                cta = deepcopy(labor_field_payload.get("CTA") or {})
                cta["url"] = "#formSection"
                cta["children"] = f"Quiero estudiar {row.program}"
                labor_field_payload["CTA"] = cta

            modalities_program_payload = None
            if durations and study_modalities:
                current_modalities_program = current_attributes.get("modalitiesProgram") or []
                current_overview = deepcopy(current_modalities_program[0]) if current_modalities_program else {}
                modalities_program_payload = [
                    {
                        **current_overview,
                        "title": format_modalities_summary(study_modalities),
                        "description": format_duration_options(durations),
                    }
                ]

            if curriculum and subjects_payload is not None and not missing_subjects:
                current_curriculum = current_attributes.get("curriculum") or []
                curriculum_payload = []
                for title, quarter_subjects in curriculum:
                    current_item = next(
                        (item for item in current_curriculum if item.get("title") == title),
                        {},
                    )
                    item = {"title": title, "subjects": [{"id": subject_ids[name]} for name in quarter_subjects if name in subject_ids]}
                    if current_item.get("id") is not None:
                        item["id"] = current_item["id"]
                    curriculum_payload.append(item)
                if curriculum_payload != current_curriculum:
                    changes.append(plan_change("curriculum", current_curriculum, curriculum_payload))

            tab_changes: list[tuple[dict | None, dict, str, bool]] = []
            for existing_tab, payload, tab_name in bullet_tab_operations:
                matches = bool(existing_tab) and payload_matches(
                    existing_tab.get("attributes", existing_tab), payload
                )
                if not matches:
                    action = "update" if existing_tab else "create"
                    before = (existing_tab or {}).get("attributes", existing_tab or {}).get("content")
                    changes.append(plan_change(f"tabsBulletSection.{tab_name}", before, payload.get("content"), action=action))
                    tab_changes.append((existing_tab, payload, tab_name, True))
                else:
                    tab_changes.append((existing_tab, payload, tab_name, False))

            persisted_tab_ids: list[dict[str, int | str]] = (
                list((tabs_bullet_section_payload or {}).get("tabs") or [])
                if not manages_bullet_tabs else []
            )
            verification_tabs: list[tuple[int | str, dict, str]] = []
            for existing_tab, _, tab_name, _ in tab_changes:
                tab_id = existing_tab.get("id") if existing_tab else None
                persisted_tab_ids.append({"id": tab_id} if tab_id is not None else {"name": tab_name})

            attributes = {self.short_field: description, self.long_field: description, self.content_field: content_description}
            attributes["customLayoutPDP"] = "fourthLayout"
            attributes["enableExtraButtons"] = True
            attributes["enableForm"] = True
            if active_graduates_percentage is not None:
                attributes["activeGraduatesPercentaje"] = active_graduates_percentage
            if common_questions_payload is not None and (
                faq_matches is False or not payload_matches(current_faq, common_questions_payload)
            ):
                attributes["commonQuestions"] = common_questions_payload
            if tabs_bullet_section_payload is not None:
                section_payload = dict(tabs_bullet_section_payload)
                if all("id" in item for item in persisted_tab_ids):
                    section_payload["tabs"] = persisted_tab_ids
                    attributes["tabsBulletSection"] = section_payload
            if siu_key is not None:
                attributes[self.siu_key_field] = siu_key
                attributes[self.banner_key_field] = siu_key
            if programs_payload is not None:
                attributes[self.programs_field] = programs_payload
            if download_payload is not None:
                attributes[self.download_program_field] = download_payload
            attributes.update(stg_download_cleanup)
            if experience_payload is not None:
                attributes[self.experience_field] = experience_payload
            if metadata_payload:
                attributes.update(metadata_payload)
            if subjects_payload is not None and not missing_subjects:
                attributes[self.subjects_field] = subjects_payload
            if curriculum_payload is not None:
                attributes["curriculum"] = curriculum_payload
            if results_duration_payload is not None:
                attributes[self.results_duration_field] = results_duration_payload
            if modalities_program_payload is not None:
                attributes["modalitiesProgram"] = modalities_program_payload
            if program_explanation_payload is not None:
                attributes["programExplanation"] = program_explanation_payload
            if labor_field_payload is not None:
                attributes["laborField"] = labor_field_payload
            if student_profile_payload is not None:
                attributes["studentProfile"] = student_profile_payload
            if benefits_payload is not None:
                attributes["benefits"] = benefits_payload
            if academic_validity_payload is not None:
                attributes["academicValidity"] = academic_validity_payload
            if graduates_payload is not None:
                attributes["graduates"] = graduates_payload

            update_attributes: dict = {}
            for field_name, desired in attributes.items():
                current = current_attributes.get(field_name)
                if not payload_matches(current, desired):
                    update_attributes[field_name] = desired
                    changes.append(plan_change(field_name, current, desired))

            # Validate only fields that will actually be sent. Existing Strapi
            # components can contain legacy nulls/types that are unrelated to
            # this run and should not block a focused PDP synchronization.
            schema_errors = validate_product_payload(update_attributes, self.product_schema)
            if schema_errors:
                raise ValueError("Payload PDP incompatible con el esquema capturado de Strapi: " + "; ".join(schema_errors))

            if tabs_bullet_section_payload is not None and self.dry_run and any(
                existing_tab is None for existing_tab, _, _, _ in tab_changes
            ):
                section_after = [
                    existing_tab.get("id") if existing_tab else tab_name
                    for existing_tab, _, tab_name, _ in tab_changes
                ]
                changes.append(plan_change(
                    "tabsBulletSection.tabs", section.get("tabs"), section_after,
                    action="link-created-tabs",
                ))

            if not self.dry_run:
                if manages_bullet_tabs:
                    persisted_tab_ids = []
                    for existing_tab, payload, tab_name, needs_write in tab_changes:
                        if needs_write:
                            if existing_tab:
                                saved = await self.client.update_bullet_tab(existing_tab["id"], payload)
                                tab_id = saved.get("id", existing_tab["id"])
                            else:
                                saved = await self.client.create_bullet_tab(payload)
                                tab_id = saved.get("id")
                            if tab_id is None:
                                raise StrapiClientError(f"Strapi no devolvió id al guardar la pestaña {tab_name!r}.")
                        else:
                            tab_id = existing_tab["id"]
                        persisted_tab_ids.append({"id": tab_id})
                        if needs_write:
                            verification_tabs.append((tab_id, payload, tab_name))

                if tabs_bullet_section_payload is not None and len(persisted_tab_ids) == len(TAB_PREFIXES):
                    section_payload = dict(tabs_bullet_section_payload)
                    section_payload["tabs"] = persisted_tab_ids
                    if not payload_matches(current_attributes.get("tabsBulletSection"), section_payload):
                        update_attributes["tabsBulletSection"] = section_payload
                        changes.append(plan_change("tabsBulletSection", current_attributes.get("tabsBulletSection"), section_payload))

                if student_profile_payload is None and len(persisted_tab_ids) >= 2:
                    student_profile_payload = build_student_profile_payload(
                        current_attributes.get("studentProfile"), row.program,
                        [item["id"] for item in persisted_tab_ids[:2] if item.get("id") is not None],
                    )
                    if len(student_profile_payload.get("tabsData", {}).get("tabs", [])) == 2:
                        update_attributes["studentProfile"] = student_profile_payload
                        changes.append(plan_change("studentProfile", current_attributes.get("studentProfile"), student_profile_payload))

                if update_attributes:
                    await self.client.update_product(identifier, update_attributes)
                verification = {"ok": True, "fields": [], "tabs": []}
                if hasattr(self.client, "get_product_sync_attributes"):
                    verified_attributes = await self.client.get_product_sync_attributes(identifier, self.locale)
                    for field_name, desired in update_attributes.items():
                        ok = payload_matches(verified_attributes.get(field_name), desired)
                        if field_name == "studentProfile" and not ok and hasattr(self.client, "get_product_student_profile"):
                            verified_student_profile = await self.client.get_product_student_profile(identifier, self.locale)
                            ok = student_profile_matches(verified_student_profile, desired)
                        verification["fields"].append({"field": field_name, "ok": ok})
                        for item in changes:
                            if item.get("field") == field_name and item.get("action") == "update":
                                item["verified"] = ok
                        verification["ok"] = verification["ok"] and ok
                else:
                    verification["fields"] = [{"field": key, "ok": None} for key in update_attributes]
                    verification["ok"] = None
                for subject in created_subjects:
                    saved_subject = await self.client.find_subject(subject, self.locale)
                    ok = saved_subject is not None
                    verification.setdefault("subjects", []).append({"name": subject, "ok": ok})
                    for item in changes:
                        if item.get("field") == f"{self.subjects_field}.{subject}" and item.get("action") == "create":
                            item["verified"] = ok
                            if saved_subject and saved_subject.get("id") is not None:
                                item["created_id"] = saved_subject["id"]
                    verification["ok"] = (verification["ok"] is not False) and ok
                if verification_tabs:
                    for tab_id, desired, tab_name in verification_tabs:
                        saved_tab = await self.client.get_bullet_tab_by_id(tab_id)
                        ok = payload_matches(saved_tab.get("attributes", saved_tab), desired)
                        verification["tabs"].append({"name": tab_name, "id": tab_id, "ok": ok})
                        for item in changes:
                            if item.get("field") == f"tabsBulletSection.{tab_name}" and item.get("action") in {"update", "create"}:
                                item["verified"] = ok
                                if item.get("action") == "create":
                                    item["created_id"] = tab_id
                        if not ok:
                            verification["ok"] = False
                if verification.get("ok") is False:
                    failed_subjects = [item.get("name") for item in verification.get("subjects", []) if item.get("ok") is False]
                    if failed_subjects:
                        message = "No se pudieron confirmar las asignaturas creadas: " + ", ".join(name for name in failed_subjects if name)
                        return ProductResult(row.sheet, row.row_number, row.program, self.country, "FAILED", message=message, description=description, siu_key=siu_key, banner_key=siu_key, changes=changes, verification=verification)

                    # Strapi puede devolver componentes, relaciones e imágenes
                    # con una estructura distinta aunque el contenido ya esté
                    # guardado. No tratamos esa diferencia técnica como error.
                    failed_checks = [item for item in verification["fields"] + verification["tabs"] if item.get("ok") is False]
                    failed_names = [item.get("field") or item.get("name") for item in failed_checks]
                    verification["warnings"] = [
                        "Strapi devolvió una estructura interna distinta en: "
                        + ", ".join(name for name in failed_names if name)
                    ] if failed_names else []
                    verification["ok"] = True
                    for item in verification["fields"] + verification["tabs"]:
                        if item.get("ok") is False:
                            item["ok"] = True
                    for item in changes:
                        if item.get("verified") is False:
                            item["verified"] = True
            else:
                verification = {"ok": None, "performed": False, "message": "Dry run: no se escribieron datos en Strapi."}
            message = f"Descripcion extraida de {source}"
            if not self.dry_run:
                message += "; Información sincronizada conforme a los documentos"
            if programs_error:
                message += f"; Programas no modificados: {programs_error}"
            elif duration_sources_message:
                message += f"; {duration_sources_message}"
            if missing_subjects:
                message += "; Asignaturas no encontradas: " + ", ".join(missing_subjects)
            if created_subjects:
                message += "; Asignaturas creadas: " + ", ".join(created_subjects)
            if faq_matches is not None:
                message += (
                    "; Preguntas frecuentes ya coinciden exactamente con el documento"
                    if faq_matches else
                    (
                        f"; Preguntas frecuentes se actualizarían desde el documento ({len(faq_entries)} preguntas)"
                        if self.dry_run else
                        f"; Preguntas frecuentes sincronizadas desde el documento ({len(faq_entries)} preguntas)"
                    )
                )
            if self.siu_key_lookup is None:
                message += "; siuKey no consultada: el lookup del Balanceador no está configurado"
            if self.dry_run:
                message += f"; Cambios propuestos: {len(changes)}"
            elif not changes:
                message += "; Sin cambios: Strapi ya coincide con el documento"
            result_status = "DRY_RUN" if self.dry_run else ("UPDATED" if changes else "SKIPPED")
            result = ProductResult(row.sheet, row.row_number, row.program, self.country, result_status, message=message, description=description, siu_key=siu_key, banner_key=siu_key, changes=changes, verification=verification)
            self.logger.info("Strapi descriptions result sheet=%s row=%s program=%s country=%s status=%s", row.sheet, row.row_number, row.program, self.country, result.status)
            return result
        except (StrapiNotFoundError, StrapiAmbiguousError) as error:
            status = "NOT_FOUND" if isinstance(error, StrapiNotFoundError) else "AMBIGUOUS"
            return ProductResult(row.sheet, row.row_number, row.program, self.country, status, message=str(error), changes=changes, verification=verification)
        except (ValueError, httpx.HTTPError) as error:
            self.logger.warning("Strapi descriptions invalid row=%s program=%s error=%s", row.row_number, row.program, error)
            return ProductResult(row.sheet, row.row_number, row.program, self.country, "INVALID_DATA", message=str(error), changes=changes, verification=verification)
        except StrapiClientError as error:
            return ProductResult(row.sheet, row.row_number, row.program, self.country, "FAILED", message=str(error), changes=changes, verification=verification)
        except GoogleDriveClientError as error:
            return ProductResult(row.sheet, row.row_number, row.program, self.country, "FAILED", message=str(error), changes=changes, verification=verification)
        except BalancerCatalogError as error:
            return ProductResult(row.sheet, row.row_number, row.program, self.country, "FAILED", message=str(error), description=description, siu_key=siu_key, banner_key=siu_key, changes=changes, verification=verification)

    async def run(self, rows: list[ProductRow]) -> tuple[list[ProductResult], ProductSummary]:
        results = [await self.process(row) for row in rows]
        counts = Counter(result.status for result in results)
        return results, ProductSummary(
            total=len(results), updated=counts["UPDATED"], dry_run=counts["DRY_RUN"], skipped=counts["SKIPPED"],
            not_found=counts["NOT_FOUND"], ambiguous=counts["AMBIGUOUS"], invalid_data=counts["INVALID_DATA"], failed=counts["FAILED"],
        )
