/** Which files the import screen accepts, checked before anything is sent to the engine. */

/** Extensions banks use for statement downloads. The engine decides the format by content. */
export const STATEMENT_EXTENSIONS = [".csv", ".ofx", ".qfx", ".txt"] as const;

/** For the file input's `accept` attribute. */
export const STATEMENT_ACCEPT = STATEMENT_EXTENSIONS.join(",");

export type FileCheck = { ok: true; file: File } | { ok: false; message: string };

/** Accept exactly one non-empty file with a statement extension. */
export function checkStatementFiles(files: readonly File[]): FileCheck {
  const [file] = files;
  if (file === undefined) {
    return { ok: false, message: "No file was chosen. Choose a statement to import." };
  }
  if (files.length > 1) {
    return {
      ok: false,
      message: `That's ${String(files.length)} files. Import one statement at a time.`,
    };
  }
  const name = file.name.toLowerCase();
  if (!STATEMENT_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    return {
      ok: false,
      message: `"${file.name}" isn't a file Monelyth can read. Choose a CSV, OFX or QFX statement downloaded from your bank.`,
    };
  }
  if (file.size === 0) {
    return { ok: false, message: `"${file.name}" is empty. Download the statement again.` };
  }
  return { ok: true, file };
}
