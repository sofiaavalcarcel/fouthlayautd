import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const projectRoot = "C:/Users/EdnaSofiaValcarcelFo/Desktop/fouthlayaut";
const sourcePath = `${projectRoot}/outputs/descargar_programas_urls/urls_descargar_programa.xlsx`;
const outputDir = `${projectRoot}/outputs/descargar_programas_urls`;
const outputPath = `${outputDir}/urls_descargar_programa_solo_encontradas.xlsx`;
const previewPath = `${outputDir}/preview_solo_encontradas.png`;

const sourceBlob = await FileBlob.load(sourcePath);
const sourceWorkbook = await SpreadsheetFile.importXlsx(sourceBlob);
const sourceSheet = sourceWorkbook.worksheets.getItem("URLs Descargar programa");
const sourceValues = sourceSheet.getUsedRange().values;

const dataRows = sourceValues
  .slice(4)
  .filter((row) => row?.[4] === "URL encontrada" && typeof row?.[2] === "string" && row[2].trim())
  .map((row) => [row[0], row[1], row[2], row[3], row[5]]);

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("URLs encontradas");
sheet.showGridLines = false;
sheet.tabColor = "#1F4E78";

sheet.getRange("A1:E1").merge();
sheet.getRange("A1").values = [["URLs de Descargar programa encontradas"]];
sheet.getRange("A2:E2").merge();
sheet.getRange("A2").values = [[`${dataRows.length} URLs encontradas en Strapi para los productos solicitados.`]];
sheet.getRange("A4:E4").values = [[
  "Categoría",
  "Programa solicitado",
  "URL Descargar programa",
  "Título en CMS",
  "Entorno",
]];

if (dataRows.length) {
  sheet.getRange(`A5:E${4 + dataRows.length}`).values = dataRows;
}

sheet.getRange("A1:E1").format = {
  font: { name: "Arial", size: 15, bold: true, color: "#1F2937" },
  verticalAlignment: "center",
};
sheet.getRange("A2:E2").format = {
  font: { name: "Arial", size: 10, italic: true, color: "#5B6472" },
  verticalAlignment: "center",
};
sheet.getRange("A4:E4").format = {
  fill: "#1F4E78",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};

if (dataRows.length) {
  const bodyRange = sheet.getRange(`A5:E${4 + dataRows.length}`);
  bodyRange.format = {
    font: { name: "Arial", size: 10, color: "#1F2937" },
    verticalAlignment: "center",
    wrapText: true,
  };
  bodyRange.format.borders = {
    insideHorizontal: { style: "thin", color: "#D9E2EC" },
    bottom: { style: "thin", color: "#D9E2EC" },
  };

  const table = sheet.tables.add(`A4:E${4 + dataRows.length}`, true, "FoundDownloadProgramUrls");
  table.style = "TableStyleMedium2";
  table.showFilterButton = true;
}

sheet.getRange("A:A").format.columnWidth = 25;
sheet.getRange("B:B").format.columnWidth = 43;
sheet.getRange("C:C").format.columnWidth = 62;
sheet.getRange("D:D").format.columnWidth = 43;
sheet.getRange("E:E").format.columnWidth = 12;
sheet.getRange("A1:E2").format.rowHeight = 22;
sheet.getRange("A4:E4").format.rowHeight = 30;
sheet.freezePanes.freezeRows(4);

workbook.recalculate();

const inspection = await workbook.inspect({
  kind: "table",
  range: `URLs encontradas!A1:E${Math.min(12, 4 + dataRows.length)}`,
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 5,
});
console.log(inspection.ndjson);

const preview = await workbook.render({
  sheetName: "URLs encontradas",
  range: `A1:E${Math.min(18, 4 + dataRows.length)}`,
  scale: 1,
  format: "png",
});

await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

console.log(JSON.stringify({ outputPath, previewPath, rows: dataRows.length }));
