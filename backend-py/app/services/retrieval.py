from dataclasses import dataclass

from app.config import config
from app.db import get_db, serialize_embedding
from app.services.embeddings import embed_query


@dataclass
class RetrievedChunk:
    id: int
    text: str
    document: str
    page: int
    chunkIndex: int
    similarity: float


def retrieve_relevant_chunks(query: str) -> list[RetrievedChunk]:
    """Retrieves the top-k most relevant chunks for a query, filtered by a
    similarity threshold. Returning an empty list signals "nothing relevant
    found" to the caller, which is the core anti-hallucination safeguard —
    the chat prompt is built to admit uncertainty rather than improvise."""
    conn = get_db()
    query_embedding = embed_query(query)
    serialized = serialize_embedding(query_embedding)

    rows = conn.execute(
        """
        SELECT c.id as id, c.text as text, c.document as document, c.page as page,
               c.chunk_index as chunk_index, v.distance as distance
        FROM vec_chunks v
        JOIN chunks c ON c.id = v.rowid
        WHERE v.embedding MATCH ? AND k = ?
        ORDER BY v.distance
        """,
        (serialized, config.top_k),
    ).fetchall()

    results = [
        RetrievedChunk(
            id=row["id"],
            text=row["text"],
            document=row["document"],
            page=row["page"],
            chunkIndex=row["chunk_index"],
            similarity=1 - row["distance"],
        )
        for row in rows
    ]
    return [r for r in results if r.similarity >= config.similarity_threshold]
