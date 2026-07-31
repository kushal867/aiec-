const CHUNK_SIZE = 1200;
const CHUNK_OVERLAP = 150;
const BOUNDARY_LOOKAHEAD = 200;

/**
 * Splits text into overlapping chunks, preferring to break on sentence
 * boundaries near the target size rather than mid-sentence.
 */
export function chunkText(text: string, chunkSize = CHUNK_SIZE, overlap = CHUNK_OVERLAP): string[] {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (normalized.length === 0) return [];
  if (normalized.length <= chunkSize) return [normalized];

  const chunks: string[] = [];
  let start = 0;

  while (start < normalized.length) {
    let end = Math.min(start + chunkSize, normalized.length);

    if (end < normalized.length) {
      const searchWindow = normalized.slice(end, Math.min(end + BOUNDARY_LOOKAHEAD, normalized.length));
      const sentenceBreak = searchWindow.search(/[.!?]\s/);
      if (sentenceBreak !== -1) {
        end += sentenceBreak + 2;
      }
    }

    const chunk = normalized.slice(start, end).trim();
    if (chunk.length > 0) chunks.push(chunk);

    if (end >= normalized.length) break;
    start = end - overlap;
  }

  return chunks;
}
