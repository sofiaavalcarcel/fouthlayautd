"""Extracción de contenido visible de una página sin depender de una clase CSS."""

from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from .models import SemanticDocument, SemanticNode
from .normalizer import display_text


class WebPageParser:
    """Obtiene elementos relevantes mediante etiquetas, texto y jerarquía."""

    async def parse(self, page: Page, url: str) -> SemanticDocument:
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        try:
            await page.wait_for_function(
                """() => [...document.querySelectorAll('button,a,[role="button"],summary')].some((element) => /ver\\s+m[aá]s|mostrar\\s+m[aá]s|cargar\\s+m[aá]s/i.test(element.innerText || element.textContent || ''))""",
                timeout=3_000,
            )
        except Exception:  # noqa: BLE001 - algunas páginas no tienen controles de expansión
            await page.wait_for_timeout(800)
        expanded_controls = await self._expand_relevant_content(page)
        records = await page.evaluate(
            """() => {
              const ignored = 'script,style,noscript,template,nav,footer,aside,[hidden],[aria-hidden="true"]';
              const selectors = 'h1,h2,h3,h4,h5,h6,p,li,dt,dd,table tr,button,a,label,summary,div';
              const normalize = (value) => (value || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase().replace(/\\s+/g, ' ').trim();
              const disclosurePatterns = ['ver mas', 'ver todas', 'mostrar mas', 'cargar mas'];
              const expandedRoots = [...document.querySelectorAll('button,a,[role="button"],summary')]
                .filter((element) => disclosurePatterns.some((pattern) => normalize(element.innerText || element.textContent).includes(pattern)))
                .map((element) => {
                  let cursor = element;
                  for (let depth = 0; depth < 6 && cursor; depth += 1, cursor = cursor.parentElement) {
                    const candidate = cursor.querySelector('[data-type]');
                    if (candidate) return candidate;
                  }
                  return null;
                }).filter(Boolean);
              const semanticExpandedRoots = [...document.querySelectorAll('[data-type]')]
                .filter((root) => root.dataset.qaExpanded === 'true' || /subject|materia|asignatura/i.test(normalize(`${root.getAttribute('data-type') || ''} ${root.textContent || ''}`)));
              expandedRoots.push(...semanticExpandedRoots);
              expandedRoots.push(...document.querySelectorAll('[role="tabpanel"][data-qa-expanded="true"]'));
              const visible = (element) => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                const insideExpandedRoot = expandedRoots.some((root) => root.contains(element));
                const isTextOnlyDiv = element.tagName !== 'DIV' || !element.querySelector('div,p,h1,h2,h3,h4,h5,h6,li,table,button,a,input,select');
                return isTextOnlyDiv && (insideExpandedRoot || !element.closest(ignored)) && (insideExpandedRoot || (style.display !== 'none' && style.visibility !== 'hidden'
                  && rect.width > 0 && rect.height > 0)) && (element.innerText?.trim() || element.textContent?.trim());
              };
              const nodes = [...document.querySelectorAll(selectors)].filter(visible);
              const heading = (element) => { const value = element.closest('section,article,main,div')?.querySelector('h1,h2,h3,h4,h5,h6'); return value?.innerText || value?.textContent || ''; };
              return nodes.map((element, index) => ({
                id: `web-${index + 1}`,
                tag: element.tagName.toLowerCase(),
                text: (element.tagName === 'DIV' ? (element.innerHTML || '').replace(/<br[^>]*>/gi, '\\n').replace(/<[^>]+>/g, ' ') : (element.innerText || element.textContent || '')).trim(),
                section: heading(element).trim(),
                order: index + 1,
                source: { tag: element.tagName.toLowerCase(), role: element.getAttribute('role') || '', testid: element.getAttribute('data-testid') || '' },
                metadata: { href: element.getAttribute('href') || '', type: element.getAttribute('type') || '', expanded_collection: expandedRoots.some((root) => root.contains(element)) }
              }));
            }"""
        )
        nodes: list[SemanticNode] = []
        for record in records:
            text = record.get("text", "")
            parts = [display_text(part) for part in text.splitlines() if display_text(part)]
            if record.get("tag") == "div" and len(parts) > 1:
                for part_index, part in enumerate(parts, start=1):
                    item = {**record, "id": f"{record['id']}-{part_index}", "text": part, "order": record["order"] + part_index / 1000}
                    nodes.append(self._record_to_node(item))
            else:
                nodes.append(self._record_to_node(record))
        title = next((node.text for node in nodes if node.type == "title"), "")
        return SemanticDocument("web", title, nodes, {"url": url, "format": "html", "expanded_controls": expanded_controls})

    @staticmethod
    async def _expand_relevant_content(page: Page) -> int:
        """Abre controles de contenido adicional sin accionar CTAs comerciales."""

        total_clicked = 0
        for _ in range(4):
            clicked = await page.evaluate(
                """() => {
                  const normalize = (value) => (value || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase().replace(/\\s+/g, ' ').trim();
                  const patterns = [
                    'ver mas', 'ver todas', 'mostrar mas', 'cargar mas'
                  ];
                  const elements = [...document.querySelectorAll('button,a,[role="button"],summary,h1,h2,h3,h4,h5,h6')];
                  let count = 0;
                  for (const element of elements) {
                    const text = normalize(element.innerText || element.textContent);
                    const isMoreContent = patterns.some((pattern) => text === pattern || text.includes(pattern));
                    const isTab = element.getAttribute('role') === 'tab';
                    if ((isMoreContent || isTab) && element.dataset.qaExpanded !== 'true') {
                      element.click();
                      element.dataset.qaExpanded = 'true';
                      let cursor = element;
                      for (let depth = 0; depth < 6 && cursor; depth += 1, cursor = cursor.parentElement) {
                        const collection = cursor.querySelector('[data-type]');
                        if (collection) { collection.dataset.qaExpanded = 'true'; break; }
                      }
                      const controlledPanel = element.getAttribute('aria-controls') && document.getElementById(element.getAttribute('aria-controls'));
                      if (controlledPanel) controlledPanel.dataset.qaExpanded = 'true';
                      count += 1;
                    }
                  }
                  document.querySelectorAll('[role="tabpanel"]').forEach((panel) => { panel.dataset.qaExpanded = 'true'; });
                  return count;
                }"""
            )
            if not clicked:
                break
            total_clicked += clicked
            await page.wait_for_timeout(500)
        headings = page.locator("h1,h2,h3,h4,h5,h6")
        for index in range(await headings.count()):
            heading = headings.nth(index)
            text = (await heading.inner_text()).strip()
            if text.endswith("?") and len(text) > 20:
                try:
                    await heading.click(force=True, timeout=3_000)
                    total_clicked += 1
                    await page.wait_for_timeout(200)
                    answer = await heading.evaluate(
                        """(element) => {
                          let cursor = element;
                          for (let depth = 0; depth < 6 && cursor; depth += 1, cursor = cursor.parentElement) {
                            const paragraph = [...cursor.querySelectorAll('p')].find((item) => item !== element && item.innerText?.trim());
                            if (paragraph) return paragraph.innerText.trim();
                          }
                          return '';
                        }"""
                    )
                    if answer:
                        await page.evaluate(
                            """(text) => {
                              const container = document.querySelector('[data-qa-captured-faq]') || (() => { const node = document.createElement('div'); node.dataset.qaCapturedFaq = 'true'; document.body.appendChild(node); return node; })();
                              const paragraph = document.createElement('p');
                              paragraph.textContent = text;
                              container.appendChild(paragraph);
                            }""",
                            answer,
                        )
                except Exception:  # noqa: BLE001 - algunos headings son informativos y no interactivos
                    continue
        return total_clicked

    @staticmethod
    def _record_to_node(record: dict[str, Any]) -> SemanticNode:
        tag = record["tag"]
        node_type = {
            "h1": "title", "h2": "section", "h3": "subsection", "h4": "subsection",
            "h5": "subsection", "h6": "subsection", "li": "list_item", "tr": "table_row",
            "dt": "label", "dd": "value", "button": "cta", "a": "cta", "label": "label",
            "summary": "section",
        }.get(tag, "paragraph")
        if record.get("metadata", {}).get("expanded_collection") and tag in {"h3", "h4", "h5", "h6"}:
            node_type = "list_item"
        if record["text"].rstrip().endswith("?"):
            node_type = "question"
        return SemanticNode(record["id"], node_type, display_text(record["text"]), display_text(record.get("section", "")), record["order"], record.get("source", {}), record.get("metadata", {}))
