FROM python:3.12-slim

# tesseract-ocr + the Nepali language pack are needed for document OCR
# (citizenship documents can be in Devanagari) — see
# .github/workflows/backend-tests.yml for the same requirement in CI.
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-nep \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model weights at build time. Without this, the
# first real chat request after every deploy pays a cold-start network
# download (see app/services/embeddings.py's lru_cache), and the app hard
# fails outright in any environment with restricted outbound network access.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

COPY app ./app

# Static seed assets (course catalog SQL, knowledge-base PDFs, partner
# university JSON) — checked into git, needed by the one-time seed/ingest
# scripts. Everything else under data/ (the SQLite DB, uploads, JWT secret)
# is git-ignored and generated at runtime, so a fresh clone's data/ directory
# only ever contains these static files at build time.
COPY data ./data

# Real data lives here: the SQLite database (every student record), uploaded
# student documents (citizenship, marksheets, IELTS certificates), the JWT
# signing secret, and the trained conversion-prediction model.
#
# THIS MUST BE BACKED BY A PERSISTENT VOLUME IN PRODUCTION. Without one,
# this directory is whatever the container's writable layer holds, which is
# wiped on every redeploy/restart — meaning every student record and every
# uploaded document is permanently lost, and a new JWT secret is generated
# each time (logging out every staff session). See docker-compose.yml, which
# wires this correctly.
#
# Docker seeds a fresh NAMED volume from whatever the image already has at
# the mount path on first container start — so the COPY above (seed SQL,
# PDFs, university JSON) ends up inside the volume automatically, while
# subsequent runs/redeploys keep whatever the volume already accumulated
# (the real database, uploads, etc.) instead of overwriting it.
VOLUME ["/app/data"]

EXPOSE 3001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3001"]
