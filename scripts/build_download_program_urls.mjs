import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const projectRoot = "C:/Users/EdnaSofiaValcarcelFo/Desktop/fouthlayaut";
const outputDir = path.join(projectRoot, "outputs", "descargar_programas_urls");
const outputPath = path.join(outputDir, "urls_descargar_programa.xlsx");

const targets = [
  ["Licenciaturas", "Licenciatura en Administración de Negocios"],
  ["Licenciaturas", "Licenciatura en Ingeniería en Energías Renovables"],
  ["Maestría y Máster", "Maestría en Administración Pública con CIFAL Málaga y UNITAR"],
  ["Maestría y Máster", "Máster en Administración Pública con CIFAL Málaga y UNITAR"],
  ["Maestría y Máster", "Máster en Administración en Mercadotecnia Empresarial"],
  ["Másteres Internacionales", "Máster Internacional en Análisis de Datos"],
  ["Másteres Internacionales", "Máster Internacional en Ciencia de Datos"],
  ["Másteres Internacionales", "Máster Internacional en Desarrollo de Software y Estructuras de Datos"],
  ["Másteres Internacionales", "Máster Internacional en Dirección de Proyectos y Liderazgo"],
  ["Másteres Internacionales", "Máster Internacional en Gestión en Hotelería y Turismo"],
  ["Másteres Internacionales", "Máster Internacional en Machine Learning"],
  ["Másteres Internacionales", "Máster Internacional en Neurociencia Médica"],
  ["Másteres Internacionales", "Máster Internacional en Pensamiento Crítico para la Toma de Decisiones"],
  ["Másteres Internacionales", "Máster Internacional en Psicología de la Ansiedad, la Depresión y las Conductas Adictivas"],
  ["Másteres Internacionales", "Máster Internacional en Soluciones Avanzadas en Ciberseguridad"],
  ["Diplomados híbridos", "Diplomado en Acompañamiento en Duelo y Pérdida"],
  ["Diplomados híbridos", "Diplomado en Bienestar Integral y Coach en Nutrición"],
  ["Diplomados híbridos", "Diplomado en Consejería para la prevención del suicidio"],
  ["Diplomados híbridos", "Diplomado en Consultoría de imagen y proyección profesional"],
  ["Diplomados híbridos", "Diplomado en Cuidados Paliativos y Humanización en Salud"],
  ["Diplomados híbridos", "Diplomado en Gamificación y Estrategias Lúdicas para el Aprendizaje"],
  ["Diplomados híbridos", "Diplomado en IA, herramientas, datos y liderazgo digital"],
  ["Diplomados híbridos", "Diplomado en Influencer Marketing y Estrategia de Marca"],
  ["Diplomados híbridos", "Diplomado en Mindfulness para entornos organizacionales"],
  ["Bootcamps", "Bootcamp Fundamento de Ciencias de Datos + Proyectos ágiles con SCRUM"],
  ["Bootcamps", "Bootcamp Fundamentos de Desarrollo Web + Proyectos ágiles con SCRUM"],
  ["Bootcamps", "Bootcamp Fundamentos de Python + Proyectos ágiles con SCRUM"],
  ["Bootcamps", "Fundamento de Ciencias de Datos"],
  ["Bootcamps", "Fundamentos de Desarrollo Web"],
  ["Bootcamps", "Fundamentos de Python"],
  ["Bachillerato", "Bachillerato en línea"],
  ["Bachillerato", "Curso Acredita-Bach"],
  ["Diplomados", "Diplomado en Actualización en Gineco-obstetricia para el primer y segundo nivel de atención"],
  ["Diplomados", "Diplomado en Actualización en urgencias"],
  ["Diplomados", "Diplomado en Administración de los servicios de salud"],
  ["Diplomados", "Diplomado en Administración de proyectos"],
  ["Diplomados", "Diplomado en Administración financiera"],
  ["Diplomados", "Diplomado en Animación Digital y Creación de Contenidos"],
  ["Diplomados", "Diplomado en Análisis Económico Integral"],
  ["Diplomados", "Diplomado en Atención del adulto mayor"],
  ["Diplomados", "Diplomado en Ciencia de datos e inteligencia artificial"],
  ["Diplomados", "Diplomado en Coaching organizacional"],
  ["Diplomados", "Diplomado en Contabilidad y Gestión financiera"],
  ["Diplomados", "Diplomado en Creatividad visual y comunicación digital"],
  ["Diplomados", "Diplomado en Desarrollo de Medios Interactivos"],
  ["Diplomados", "Diplomado en Desarrollo e-learning"],
  ["Diplomados", "Diplomado en Dirección de operaciones"],
  ["Diplomados", "Diplomado en Diseño y Desarrollo de Software"],
  ["Diplomados", "Diplomado en Diseño y Evaluación en Entornos Digitales"],
  ["Diplomados", "Diplomado en Diversidad y equidad de género"],
  ["Diplomados", "Diplomado en Educación en Ciencias de la Salud"],
  ["Diplomados", "Diplomado en Educación en ciencias de la salud"],
  ["Diplomados", "Diplomado en Estrategia e innovacción de negocios"],
  ["Diplomados", "Diplomado en Estrategias y Operaciones de Transporte"],
  ["Diplomados", "Diplomado en Fuentes y tecnologías de energías renovables"],
  ["Diplomados", "Diplomado en Gestión Sostenible de la Cadena de Suministro"],
  ["Diplomados", "Diplomado en Gestión curricular en educación a distancia"],
  ["Diplomados", "Diplomado en Gestión de Calidad y Mantenimiento de Software"],
  ["Diplomados", "Diplomado en Gestión de Experiencias de Aprendizaje en Ambientes Virtuales"],
  ["Diplomados", "Diplomado en Gestión y eficiencia de sistemas energéticos"],
  ["Diplomados", "Diplomado en Inteligencia artificial aplicada"],
  ["Diplomados", "Diplomado en Mindfulness para los individuos y familias"],
  ["Diplomados", "Diplomado en Métodos Cuantitativos para la Toma de Decisiones"],
  ["Diplomados", "Diplomado en Nutrición especial en enfermedades metabólicas"],
  ["Diplomados", "Diplomado en Pensamiento crítico e innovación"],
  ["Diplomados", "Diplomado en Principios en el Arte Digital y Animación"],
  ["Diplomados", "Diplomado en Programación y Tecnologías de Redes"],
  ["Diplomados", "Diplomado en Project Management"],
  ["Diplomados", "Diplomado en Pruebas Psicológicas para Adultos"],
  ["Diplomados", "Diplomado en Rehabilitación del adulto mayor"],
  ["Diplomados", "Diplomado en Soft skills y habilidades gerenciales"],
  ["Diplomados", "Diplomado en Tanatología"],
  ["Diplomados", "Diplomado en Tecnologías de la Información Aplicadas a la Logística y el Transporte"],
  ["Diplomados", "Diplomado en Transición y energía sostenible"],
];

function parseEnv(text) {
  const values = {};
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
    if (!match) continue;
    let value = match[2].trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    values[match[1]] = value;
  }
  return values;
}

function firstUrl(value) {
  if (!value) return "";
  if (typeof value === "string" && /^https?:\/\//i.test(value)) return value;
  if (Array.isArray(value)) {
    for (const item of value) {
      const url = firstUrl(item);
      if (url) return url;
    }
    return "";
  }
  if (typeof value === "object") {
    if (typeof value.url === "string" && /^https?:\/\//i.test(value.url)) return value.url;
    for (const child of Object.values(value)) {
      const url = firstUrl(child);
      if (url) return url;
    }
  }
  return "";
}

function titleVariants(name) {
  const variants = [name];
  if (name.startsWith("Máster Internacional en ")) {
    variants.push(name.replace("Máster Internacional en ", ""));
  }
  if (name.startsWith("Máster en ")) {
    variants.push(name.replace("Máster en ", ""));
  }
  if (name.startsWith("Maestría en ")) {
    variants.push(name.replace("Maestría en ", ""));
  }
  return [...new Set(variants)];
}

async function fetchJson(baseUrl, token, endpoint, params) {
  const url = new URL(endpoint, `${baseUrl.replace(/\/$/, "")}/`);
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, value);
  const response = await fetch(url, {
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  });
  const text = await response.text();
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${text.slice(0, 240)}`);
  return text ? JSON.parse(text) : {};
}

async function findProduct(baseUrl, token, endpoint, title) {
  for (const candidate of titleVariants(title)) {
    for (const status of ["draft", "published"]) {
      for (const includeLocale of [true, false]) {
        const params = {
          "filters[title][$eq]": candidate,
          status,
          "pagination[pageSize]": "10",
        };
        if (includeLocale) params.locale = "es-MX";
        const payload = await fetchJson(baseUrl, token, endpoint, params);
        const entries = payload.data || [];
        if (entries.length === 1) return { entry: entries[0], status, candidate };
      }
    }
  }
  return null;
}

async function getDownload(baseUrl, token, endpoint, id, status) {
  const payload = await fetchJson(baseUrl, token, `${endpoint}/${id}`, {
    status,
    "populate[downloadProgram][populate]": "*",
  });
  const data = payload.data || {};
  const attributes = data.attributes || data;
  const download = attributes.downloadProgram || null;
  return { download, url: firstUrl(download) };
}

async function main() {
  const env = parseEnv(await fs.readFile(path.join(projectRoot, ".env"), "utf8"));
  const baseUrl = env.STRAPI_URL;
  const token = env.STRAPI_TOKEN;
  const endpoint = env.STRAPI_PRODUCT_ENDPOINT || "/api/products";
  if (!baseUrl || !token) throw new Error("Faltan STRAPI_URL o STRAPI_TOKEN en .env");

  const records = [];
  for (const [category, requestedName] of targets) {
    try {
      const found = await findProduct(baseUrl, token, endpoint, requestedName);
      if (!found) {
        records.push({ category, requestedName, url: "", cmsTitle: "", status: "Producto no encontrado", sourceStatus: "", note: "No se encontró el producto en Strapi con el nombre solicitado." });
        continue;
      }
      const data = found.entry.attributes || found.entry;
      const id = found.entry.id || found.entry.documentId;
      const download = await getDownload(baseUrl, token, endpoint, id, found.status);
      records.push({
        category,
        requestedName,
        url: download.url,
        cmsTitle: data.title || found.candidate,
        status: download.url ? "URL encontrada" : "Sin URL en downloadProgram",
        sourceStatus: found.status,
        note: found.candidate === requestedName ? "" : `Coincidencia encontrada con: ${found.candidate}`,
      });
    } catch (error) {
      records.push({ category, requestedName, url: "", cmsTitle: "", status: "Error de consulta", sourceStatus: "", note: error instanceof Error ? error.message : String(error) });
    }
  }

  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("URLs Descargar programa");
  sheet.showGridLines = false;
  sheet.getRange("A1:F1").merge();
  sheet.getRange("A1").values = [["URLs de Descargar programa"]];
  sheet.getRange("A2:F2").merge();
  sheet.getRange("A2").values = [["URLs consultadas en Strapi para productos de México; se conserva el nombre solicitado y se reportan productos o descargas faltantes."]];
  const headers = [["Categoría", "Programa solicitado", "URL Descargar programa", "Título en CMS", "Estado", "Entorno / nota"]];
  sheet.getRange("A4:F4").values = headers;
  sheet.getRange(`A5:F${records.length + 4}`).values = records.map((record) => [record.category, record.requestedName, record.url, record.cmsTitle, record.status, record.sourceStatus ? record.sourceStatus : record.note]);
  const endRow = records.length + 4;
  sheet.tables.add(`A4:F${endRow}`, true, "DownloadProgramsTable");
  sheet.freezePanes.freezeRows(4);
  sheet.getRange("A1:F1").format = { font: { name: "Arial", size: 15, bold: true, color: "#1F3A2E" } };
  sheet.getRange("A2:F2").format = { font: { name: "Arial", size: 10, italic: true, color: "#52605A" }, wrapText: true };
  sheet.getRange("A4:F4").format = { fill: "#1F4E3D", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
  sheet.getRange(`A5:F${endRow}`).format = { font: { name: "Arial", size: 10, color: "#17231E" }, verticalAlignment: "center", wrapText: true };
  sheet.getRange(`A4:F${endRow}`).format.borders = { preset: "all", style: "thin", color: "#D9E2DC" };
  sheet.getRange(`E5:E${endRow}`).conditionalFormats.add("containsText", { text: "Producto no encontrado", format: { fill: "#FDECEC", font: { color: "#B42318", bold: true } } });
  sheet.getRange(`E5:E${endRow}`).conditionalFormats.add("containsText", { text: "Sin URL", format: { fill: "#FFF4CC", font: { color: "#8A5A00", bold: true } } });
  sheet.getRange(`E5:E${endRow}`).conditionalFormats.add("containsText", { text: "Error", format: { fill: "#FDECEC", font: { color: "#B42318", bold: true } } });
  sheet.getRange("A:A").format.columnWidth = 22;
  sheet.getRange("B:B").format.columnWidth = 54;
  sheet.getRange("C:C").format.columnWidth = 78;
  sheet.getRange("D:D").format.columnWidth = 54;
  sheet.getRange("E:E").format.columnWidth = 26;
  sheet.getRange("F:F").format.columnWidth = 28;
  sheet.getRange(`A1:F${endRow}`).format.verticalAlignment = "center";
  sheet.getRange(`A5:F${endRow}`).format.rowHeight = 30;

  const summary = workbook.worksheets.add("Resumen");
  summary.showGridLines = false;
  summary.getRange("A1:C1").merge();
  summary.getRange("A1").values = [["Resumen de URLs consultadas"]];
  summary.getRange("A3:C3").values = [["Estado", "Cantidad", "Descripción"]];
  const statusCounts = records.reduce((acc, item) => { acc[item.status] = (acc[item.status] || 0) + 1; return acc; }, {});
  summary.getRange("A4:C7").values = [
    ["URL encontrada", statusCounts["URL encontrada"] || 0, "Producto encontrado y downloadProgram contiene una URL."],
    ["Sin URL en downloadProgram", statusCounts["Sin URL en downloadProgram"] || 0, "Producto encontrado, pero el campo no contiene URL."],
    ["Producto no encontrado", statusCounts["Producto no encontrado"] || 0, "No se encontró el producto en Strapi."],
    ["Error de consulta", statusCounts["Error de consulta"] || 0, "La consulta al CMS devolvió un error."],
  ];
  summary.getRange("A1:C1").format = { font: { name: "Arial", size: 15, bold: true, color: "#1F3A2E" } };
  summary.getRange("A3:C3").format = { fill: "#1F4E3D", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
  summary.getRange("A4:C7").format = { font: { name: "Arial", size: 10, color: "#17231E" }, wrapText: true, verticalAlignment: "center" };
  summary.getRange("A3:C7").format.borders = { preset: "all", style: "thin", color: "#D9E2DC" };
  summary.getRange("A:A").format.columnWidth = 30;
  summary.getRange("B:B").format.columnWidth = 12;
  summary.getRange("C:C").format.columnWidth = 70;

  workbook.recalculate();
  const inspection = await workbook.inspect({ kind: "table", sheetId: "URLs Descargar programa", range: `A1:F${Math.min(endRow, 12)}`, include: "values", tableMaxRows: 12, tableMaxCols: 6, maxChars: 5000 });
  console.log(inspection.ndjson);
  await fs.mkdir(outputDir, { recursive: true });
  const preview = await workbook.render({ sheetName: "URLs Descargar programa", autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(outputDir, "preview.png"), new Uint8Array(await preview.arrayBuffer()));
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
  console.log(JSON.stringify({ outputPath, total: records.length, statusCounts }, null, 2));
}

await main();
