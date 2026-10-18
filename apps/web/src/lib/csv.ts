export type RunCsvRow = {
  code: string;
  rawCode: string;
  name: string | null;
  instrumentType: string;
  matchedNames: string[];
  diff: "new" | "kept";
  price: number | null;
  changeRate: string | null;
};

export function escapeCsvText(value: string | null): string {
  let text = value ?? "";
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return /[,"\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function formatCsvNumber(value: number | string | null): string {
  return value === null ? "" : String(value);
}

export function buildRunCsv(rows: RunCsvRow[]): string {
  const lines = ["종목코드,원본코드,종목명,유형,충족조건,변화,현재가,등락률"];
  for (const row of rows) {
    lines.push([
      ...[row.code, row.rawCode, row.name, row.instrumentType, row.matchedNames.join(" | "), row.diff === "new" ? "신규" : "유지"].map(escapeCsvText),
      formatCsvNumber(row.price), formatCsvNumber(row.changeRate),
    ].join(","));
  }
  return `\uFEFF${lines.join("\r\n")}\r\n`;
}
