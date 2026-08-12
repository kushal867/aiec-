import os
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _resolve_jwt_secret(database_path: Path) -> str:
    """Mirrors config.ts's resolveJwtSecret: generate + persist locally if unset,
    so tokens survive restarts but a real deployment should set JWT_SECRET explicitly
    (otherwise a redeploy invalidates every session)."""
    env_secret = os.environ.get("JWT_SECRET")
    if env_secret:
        return env_secret

    secret_path = database_path.parent / ".jwt-secret"
    if secret_path.exists():
        return secret_path.read_text().strip()

    print(
        "[config] WARNING: JWT_SECRET is not set — generating one and persisting it to "
        f"{secret_path}. This is fine for local dev. In production, if this directory "
        "isn't on a persistent volume, every redeploy generates a NEW secret and logs out "
        "every staff session. Set JWT_SECRET explicitly to avoid this.",
        file=sys.stderr,
    )
    generated = secrets.token_hex(48)
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(generated)
    secret_path.chmod(0o600)
    return generated


class Config:
    def __init__(self) -> None:
        # Runs locally via sentence-transformers (ONNX/CPU) — no API key, no cost.
        self.embedding_model = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        self.database_path = Path(os.environ.get("DATABASE_PATH", "./data/knowledge.db")).resolve()
        self.port = int(os.environ.get("PORT", "3001"))
        self.allowed_origin = os.environ.get("ALLOWED_ORIGIN", "*")
        # Separate from allowed_origin: the CRM dashboard is a different internal
        # app on its own origin (not the client's public site), so it needs its
        # own CORS allowance rather than sharing the public widget's origin.
        self.admin_allowed_origin = os.environ.get("ADMIN_ALLOWED_ORIGIN", "http://localhost:3002")
        self.top_k = int(os.environ.get("TOP_K", "5"))
        self.similarity_threshold = float(os.environ.get("SIMILARITY_THRESHOLD", "0.5"))
        self.rate_limit_max = int(os.environ.get("RATE_LIMIT_MAX", "20"))
        self.profile_rate_limit_max = int(os.environ.get("PROFILE_RATE_LIMIT_MAX", "5"))
        self.document_rate_limit_max = int(os.environ.get("DOCUMENT_RATE_LIMIT_MAX", "8"))
        self.uploads_dir = Path(os.environ.get("UPLOADS_DIR", "./data/uploads")).resolve()
        self.jwt_secret = _resolve_jwt_secret(self.database_path)
        self.jwt_expires_in_hours = int(os.environ.get("JWT_EXPIRES_IN_HOURS", "12"))
        # Self-training conversion model (see services/conversion_model.py): below
        # this many real terminal-outcome rows (enrolled/rejected), predictions
        # fall back to the rule-based rubric in conversion_prediction.py — there
        # isn't enough signal yet to trust a trained classifier.
        self.conversion_model_min_training_rows = int(os.environ.get("CONVERSION_MODEL_MIN_TRAINING_ROWS", "30"))
        self.conversion_model_path = Path(
            os.environ.get("CONVERSION_MODEL_PATH", str(self.database_path.parent / "conversion_model.joblib"))
        ).resolve()


config = Config()
