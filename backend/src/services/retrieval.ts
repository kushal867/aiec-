import { getDb } from "./db";
import { embedQuery } from "./embeddings";
import { config } from "../config";
import type { RetrievedChunk } from "../types";

interface VecRow {
  id: number;
  text: string;
  document: string;
  page: number;
  chunk_index: number;
  distance: number;
}

/**
 * Retrieves the top-k most relevant chunks for a query, filtered by a
 * similarity threshold. Returning an empty array signals "nothing relevant
 * found" to the caller, which is the core anti-hallucination safeguard —
 * the chat prompt is built to admit uncertainty rather than improvise.
 */
export async function retrieveRelevantChunks(query: string): Promise<RetrievedChunk[]> {
  const db = getDb();
  const queryEmbedding = await embedQuery(query);
  const serialized = Buffer.from(new Float32Array(queryEmbedding).buffer);

  const rows = db
    .prepare(
      `SELECT c.id as id, c.text as text, c.document as document, c.page as page,
              c.chunk_index as chunk_index, v.distance as distance
       FROM vec_chunks v
       JOIN chunks c ON c.id = v.rowid
       WHERE v.embedding MATCH ? AND k = ?
       ORDER BY v.distance`,
    )
    .all(serialized, config.topK) as VecRow[];

  return rows
    .map((row) => ({
      id: row.id,
      text: row.text,
      document: row.document,
      page: row.page,
      chunkIndex: row.chunk_index,
      similarity: 1 - row.distance,
    }))
    .filter((chunk) => chunk.similarity >= config.similarityThreshold);
}
