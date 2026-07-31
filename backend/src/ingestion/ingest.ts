import fs from "node:fs";
import path from "node:path";
import { config } from "../config";
import { resetSchema, getDb } from "../services/db";
import { embedTexts } from "../services/embeddings";
import { parsePdfPages } from "./pdfParser";
import { chunkText } from "./chunker";

interface PendingChunk {
  text: string;
  document: string;
  page: number;
  chunkIndex: number;
}

async function collectChunks(pdfDir: string): Promise<PendingChunk[]> {
  const files = fs.readdirSync(pdfDir).filter((f) => f.toLowerCase().endsWith(".pdf"));
  if (files.length === 0) {
    console.warn(`No PDFs found in ${pdfDir}. Add source PDFs and re-run.`);
  }

  const pending: PendingChunk[] = [];

  for (const file of files) {
    const filePath = path.join(pdfDir, file);
    const buffer = fs.readFileSync(filePath);
    const pages = await parsePdfPages(buffer);

    for (const { page, text } of pages) {
      const chunks = chunkText(text);
      chunks.forEach((chunkedText, chunkIndex) => {
        pending.push({ text: chunkedText, document: file, page, chunkIndex });
      });
    }

    console.log(`Parsed ${file}: ${pages.length} pages`);
  }

  return pending;
}

async function main() {
  const pdfDir = path.join(path.dirname(config.databasePath), "pdfs");
  const chunks = await collectChunks(pdfDir);

  if (chunks.length === 0) {
    console.warn("No chunks produced — skipping database rebuild.");
    return;
  }

  console.log(`Embedding ${chunks.length} chunks locally (${config.embeddingModel})...`);
  const embeddings = await embedTexts(
    chunks.map((c) => c.text),
    "document",
  );

  resetSchema();
  const db = getDb();

  const insertChunk = db.prepare(
    `INSERT INTO chunks (id, text, document, page, chunk_index) VALUES (?, ?, ?, ?, ?)`,
  );
  const insertVec = db.prepare(`INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)`);

  const insertAll = db.transaction(() => {
    chunks.forEach((chunk, i) => {
      const id = i + 1;
      insertChunk.run(id, chunk.text, chunk.document, chunk.page, chunk.chunkIndex);
      // sqlite-vec's vec0 rejects a plain bound JS number for rowid ("Only
      // integers are allowed for primary key values") — must bind as BigInt.
      insertVec.run(BigInt(id), Buffer.from(new Float32Array(embeddings[i]).buffer));
    });
  });
  insertAll();

  const dbSizeBytes = fs.statSync(config.databasePath).size;
  console.log(`Ingestion complete: ${chunks.length} chunks from ${new Set(chunks.map((c) => c.document)).size} document(s).`);
  console.log(`Database: ${config.databasePath} (${(dbSizeBytes / 1024).toFixed(1)} KB)`);
}

main().catch((err) => {
  console.error("Ingestion failed:", err);
  process.exit(1);
});
