"""Paths, limits and environment-based settings. Secrets are read here and never logged."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SAMPLE_PATH = DATA_DIR / "sample_requests.csv"
HOLDOUT_PATH = DATA_DIR / "holdout_requests.csv"

# Local .env (git-ignored) is optional; real environment variables win.
load_dotenv(ROOT / ".env", override=False)

MAX_UPLOAD_BYTES = 1_000_000
MAX_UPLOAD_ROWS = 100
MAX_REQUEST_CHARS = 2000
DEFAULT_MODEL = "gpt-4o-mini"


def db_path() -> Path:
    """SQLite file location; override with OPSFLOW_DB_PATH."""
    override = os.getenv("OPSFLOW_DB_PATH", "").strip()
    return Path(override) if override else DATA_DIR / "opsflow.db"


def llm_model() -> str:
    return os.getenv("OPSFLOW_MODEL", "").strip() or DEFAULT_MODEL


def llm_api_key() -> str | None:
    """Return the API key, or None when it is missing or still a placeholder."""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or key.lower().startswith(("your", "sk-your", "changeme", "<")):
        return None
    return key


def llm_available() -> bool:
    return llm_api_key() is not None


# Built-in demo account (shown prefilled on the sign-in page). Not a secret: it only unlocks fictional demo data.
DEMO_EMAIL = os.getenv("OPSFLOW_DEMO_EMAIL", "demo@opsflow.lab").strip()
DEMO_PASSWORD = os.getenv("OPSFLOW_DEMO_PASSWORD", "opsflow-demo-2026")
DEMO_NAME = "Demo Reviewer"
DEMO_ROLE = "Operations reviewer"

EXTRA_DEMO_USERS = [
    ("maria.keller@opsflow.lab", "Maria Keller", "Operations lead"),
    ("sam.ortiz@opsflow.lab", "Sam Ortiz", "AI analyst"),
]


def autoseed() -> bool:
    """On first launch (demo mode) process the built-in sample queue so no page starts empty."""
    return os.getenv("OPSFLOW_AUTOSEED", "1").strip() != "0"
