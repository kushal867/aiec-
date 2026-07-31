import path from "node:path";

export interface ParsedPage {
  page: number;
  text: string;
}

const STANDARD_FONT_DATA_URL = path.join(
  path.dirname(require.resolve("pdfjs-dist/package.json")),
  "standard_fonts/",
) + path.sep;

/**
 * Parses a PDF buffer into per-page text, needed later for citations
 * (e.g. "see page 4 of the Canada Study Permit Guide"). Uses pdfjs-dist's
 * per-document API directly rather than pdf-parse's pagerender hook — the
 * latter shares broken state across sequential calls in one process (fails
 * from the 3rd PDF onward with "bad XRef entry" even on well-formed files).
 */
export async function parsePdfPages(buffer: Buffer): Promise<ParsedPage[]> {
  const { getDocument } = await import("pdfjs-dist/legacy/build/pdf.mjs");

  const doc = await getDocument({
    data: new Uint8Array(buffer),
    standardFontDataUrl: STANDARD_FONT_DATA_URL,
  }).promise;

  try {
    const pages: ParsedPage[] = [];
    for (let pageNumber = 1; pageNumber <= doc.numPages; pageNumber++) {
      const page = await doc.getPage(pageNumber);
      const textContent = await page.getTextContent();
      const text = textContent.items
        .map((item) => ("str" in item ? item.str : ""))
        .join(" ");
      pages.push({ page: pageNumber, text });
    }
    return pages;
  } finally {
    await doc.destroy();
  }
}
