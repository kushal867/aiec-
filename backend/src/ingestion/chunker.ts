const CHUNK_SIZE = 1200;
const CHUNK_OVERLAP = 150;
const BOUNDARY_LOOKAHEAD = 200;

// Matches the start of a numbered FAQ entry ("14. Which English language
// tests are accepted?") once whitespace has been collapsed to single spaces.
// The capital-letter lookahead keeps this from matching a decimal number
// ("6.0 to 7.5") — the digit after the period there isn't a capital letter.
const FAQ_QUESTION_START = /(?<!\d)(\d{1,3})\.\s+(?=[A-Z])/g;

// Require several matches, not just one — a single numbered legal clause in
// an otherwise normal policy PDF shouldn't force FAQ-style splitting.
const MIN_FAQ_MATCHES = 3;

/**
 * A real enumerated list (1, 2, 3, ...) is monotonically increasing.
 * Coincidental digit-period-capital matches in ordinary prose (a page full
 * of "$50. Universities require...", "$30. Other institutions...") mostly
 * aren't. Allows a little noise (e.g. one out-of-order figure) rather than
 * requiring a perfect run, since PDF text extraction is occasionally messy.
 */
function isSequentialNumbering(matches: RegExpMatchArray[]): boolean {
  const numbers = matches.map((m) => Number(m[1]));
  let ascending = 0;
  for (let i = 0; i < numbers.length - 1; i++) {
    if (numbers[i + 1] > numbers[i]) ascending++;
  }
  return ascending >= numbers.length - 2;
}

/**
 * Splits FAQ-formatted text into one chunk per numbered Q&A pair instead of
 * a fixed-size sliding window. Generic chunking on a document like a
 * 500-question FAQ PDF lumps 6-8 unrelated questions into a single
 * 1200-char chunk — e.g. IELTS score requirements ended up in the same
 * chunk as intake months and a scholarships intro, so a student asking
 * "what IELTS score do I need" got a paragraph of noise back instead of the
 * one line that actually answers it. This system grounds Claude's answer in
 * whichever chunk retrieval finds — chunk boundaries need to match the
 * document's real structure for that grounding to be precise. Returns null
 * (defer to the generic chunker) when the text doesn't look like a numbered
 * FAQ.
 */
function splitFaqQuestions(text: string): string[] | null {
  const matches = Array.from(text.matchAll(FAQ_QUESTION_START));
  if (matches.length < MIN_FAQ_MATCHES || !isSequentialNumbering(matches)) return null;

  const segments: string[] = [];
  const lead = text.slice(0, matches[0].index).trim();
  if (lead) segments.push(lead);

  for (let i = 0; i < matches.length; i++) {
    const start = matches[i].index!;
    const end = i + 1 < matches.length ? matches[i + 1].index! : text.length;
    const segment = text.slice(start, end).trim();
    if (segment) segments.push(segment);
  }

  return segments;
}

function chunkBySlidingWindow(normalized: string, chunkSize: number, overlap: number): string[] {
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

/**
 * Splits text into chunks. FAQ-formatted text (numbered Q&A pairs) is split
 * one-chunk-per-question (see splitFaqQuestions); anything else falls back
 * to overlapping sliding-window chunks, preferring to break on sentence
 * boundaries near the target size rather than mid-sentence.
 */
export function chunkText(text: string, chunkSize = CHUNK_SIZE, overlap = CHUNK_OVERLAP): string[] {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (normalized.length === 0) return [];

  const faqSegments = splitFaqQuestions(normalized);
  if (faqSegments !== null) {
    const chunks: string[] = [];
    for (const segment of faqSegments) {
      if (segment.length <= chunkSize) {
        chunks.push(segment);
      } else {
        chunks.push(...chunkBySlidingWindow(segment, chunkSize, overlap));
      }
    }
    return chunks;
  }

  if (normalized.length <= chunkSize) return [normalized];

  return chunkBySlidingWindow(normalized, chunkSize, overlap);
}
