from dataclasses import dataclass
from pathlib import Path

from app.config import config
from app.db import get_db, reset_schema, serialize_embedding
from app.ingestion.chunker import chunk_text
from app.ingestion.pdf_parser import parse_pdf_pages
from app.services.embeddings import embed_texts


@dataclass
class PendingChunk:
    text: str
    document: str
    page: int
    chunk_index: int


def _collect_chunks(pdf_dir: Path) -> list[PendingChunk]:
    files = sorted(p for p in pdf_dir.glob("*.pdf"))
    if not files:
        print(f"No PDFs found in {pdf_dir}. Add source PDFs and re-run.")

    pending: list[PendingChunk] = []
    for file_path in files:
        pages = parse_pdf_pages(file_path.read_bytes())
        for parsed_page in pages:
            chunks = chunk_text(parsed_page.text)
            for chunk_index, chunked_text in enumerate(chunks):
                pending.append(PendingChunk(text=chunked_text, document=file_path.name, page=parsed_page.page, chunk_index=chunk_index))
        print(f"Parsed {file_path.name}: {len(pages)} pages")

    return pending


def main() -> None:
    pdf_dir = config.database_path.parent / "pdfs"
    chunks = _collect_chunks(pdf_dir)

    if not chunks:
        print("No chunks produced — skipping database rebuild.")
        return

    print(f"Embedding {len(chunks)} chunks locally ({config.embedding_model})...")
    embeddings = embed_texts([c.text for c in chunks], "document")

    reset_schema()
    conn = get_db()

    with conn:
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings), start=1):
            conn.execute(
                "INSERT INTO chunks (id, text, document, page, chunk_index) VALUES (?, ?, ?, ?, ?)",
                (i, chunk.text, chunk.document, chunk.page, chunk.chunk_index),
            )
            conn.execute(
                "INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
                (i, serialize_embedding(embedding)),
            )

    db_size_kb = config.database_path.stat().st_size / 1024
    documents = {c.document for c in chunks}
    print(f"Ingestion complete: {len(chunks)} chunks from {len(documents)} document(s).")
    print(f"Database: {config.database_path} ({db_size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
