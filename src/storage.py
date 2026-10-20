"""SQLite persistence for processing runs and human reviews.

Request text is deliberately NOT stored: only ids, labels and review decisions.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional, Sequence

import pandas as pd

from .triage import CATEGORIES, PRIORITIES, TEAMS, TriageResult

REVIEW_FIELDS = ("category", "priority", "team")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL,          -- 'inbox' or 'replay'
    dataset TEXT NOT NULL,
    engine TEXT NOT NULL,
    created_at TEXT NOT NULL,
    n_requests INTEGER NOT NULL,
    n_flagged INTEGER NOT NULL,
    metrics_json TEXT
);
CREATE TABLE IF NOT EXISTS processed (
    run_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    category TEXT, priority TEXT, team TEXT,
    needs_review INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    processed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    onboarded INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS queue_items (
    request_id TEXT PRIMARY KEY,
    requester TEXT,
    request_text TEXT NOT NULL,
    source TEXT NOT NULL,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS queue_results (
    request_id TEXT PRIMARY KEY,
    run_id TEXT,
    result_json TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    sender TEXT NOT NULL,
    recipient TEXT NOT NULL,         -- a team name or 'All teams'
    priority TEXT NOT NULL,          -- 'Normal' or 'Urgent'
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    request_id TEXT
);
CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY,
    run_id TEXT,
    request_id TEXT NOT NULL,
    engine TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    decision TEXT NOT NULL,          -- 'approved' or 'corrected'
    proposed_category TEXT, proposed_priority TEXT, proposed_team TEXT,
    final_category TEXT, final_priority TEXT, final_team TEXT,
    fields_changed TEXT NOT NULL,
    note TEXT,
    reviewer TEXT
);
"""


PBKDF2_ITERATIONS = 240_000
MIN_PASSWORD_LENGTH = 8


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS).hex()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Storage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(reviews)")}
            if "reviewer" not in columns:  # databases created before reviewer attribution existed
                conn.execute("ALTER TABLE reviews ADD COLUMN reviewer TEXT")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- users (local accounts; passwords are salted PBKDF2 hashes, never stored or logged in clear) ----
    def create_user(self, email: str, name: str, role: str, password: str) -> None:
        email = email.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1] or len(email) > 120:
            raise ValueError("Enter a valid email address.")
        if not name.strip():
            raise ValueError("Enter your name.")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        salt = secrets.token_bytes(16)
        try:
            with self._connect() as conn:
                conn.execute("INSERT INTO users (email, name, role, salt, password_hash, created_at) VALUES (?,?,?,?,?,?)",
                             (email, name.strip()[:60], role, salt.hex(), _hash_password(password, salt), _now()))
        except sqlite3.IntegrityError as exc:
            raise ValueError("An account with this email already exists.") from exc

    def authenticate(self, email: str, password: str) -> Optional[dict]:
        """Return the user dict if the credentials match, otherwise None (same result for unknown email)."""
        with self._connect() as conn:
            row = conn.execute("SELECT email, name, role, salt, password_hash, onboarded FROM users WHERE email = ?",
                               (email.strip().lower(),)).fetchone()
        salt = bytes.fromhex(row[3]) if row else bytes(16)
        candidate = _hash_password(password, salt)
        if row and hmac.compare_digest(candidate, row[4]):
            return {"email": row[0], "name": row[1], "role": row[2], "onboarded": bool(row[5])}
        return None

    # ---- working queue: requests, their latest result and review status (fictional data, kept locally) ----
    def upsert_request(self, item: dict) -> None:
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO queue_items VALUES (?,?,?,?,?)",
                         (item["request_id"], item.get("requester", ""), item["text"], item["source"], _now()))

    def load_queue(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT request_id, requester, request_text, source FROM queue_items "
                                "ORDER BY added_at DESC, rowid ASC").fetchall()
        return [{"request_id": r[0], "requester": r[1] or "", "text": r[2], "source": r[3]} for r in rows]

    def save_result(self, result: TriageResult, run_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO queue_results VALUES (?,?,?,?)",
                         (result.request_id, run_id, result.model_dump_json(), status))

    def set_status(self, request_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE queue_results SET status = ? WHERE request_id = ?", (status, request_id))

    def load_results(self) -> tuple[dict, dict, dict]:
        """Return (results, run_ids, statuses) keyed by request id."""
        with self._connect() as conn:
            rows = conn.execute("SELECT request_id, run_id, result_json, status FROM queue_results").fetchall()
        return ({r[0]: TriageResult.model_validate_json(r[2]) for r in rows},
                {r[0]: r[1] for r in rows}, {r[0]: r[3] for r in rows})

    # ---- internal messages (stored locally; nothing is emailed or sent to an external system) ----
    def send_message(self, sender: str, recipient: str, subject: str, body: str,
                     priority: str = "Normal", request_id: Optional[str] = None, at: Optional[str] = None) -> str:
        if recipient != "All teams" and recipient not in TEAMS:
            raise ValueError("Choose a team or 'All teams'.")
        if priority not in ("Normal", "Urgent"):
            raise ValueError("Priority must be Normal or Urgent.")
        if not subject.strip() or not body.strip():
            raise ValueError("Add a subject and a message.")
        message_id = _new_id("msg")
        with self._connect() as conn:
            conn.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)",
                         (message_id, at or _now(), sender.strip()[:60], recipient, priority,
                          subject.strip()[:120], body.strip()[:2000], request_id))
        return message_id

    def messages(self, recipient: Optional[str] = None, limit: int = 100) -> pd.DataFrame:
        if recipient and recipient != "All":
            return self._frame("SELECT * FROM messages WHERE recipient IN (?, 'All teams') "
                               "ORDER BY created_at DESC, rowid DESC LIMIT ?", (recipient, limit))
        return self._frame("SELECT * FROM messages ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))

    def users_overview(self) -> pd.DataFrame:
        """Accounts with how many reviews each person has saved (no password data)."""
        return self._frame(
            "SELECT u.name, u.role, u.email, u.created_at, COUNT(r.review_id) AS reviews, "
            "COALESCE(SUM(r.decision = 'approved'), 0) AS approved "
            "FROM users u LEFT JOIN reviews r ON r.reviewer = u.name GROUP BY u.email ORDER BY u.created_at, u.name")

    def mark_onboarded(self, email: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE users SET onboarded = 1 WHERE email = ?", (email.strip().lower(),))

    def save_run(
        self,
        run_type: str,
        engine: str,
        dataset: str,
        *,
        results: Sequence[TriageResult] = (),
        n_requests: Optional[int] = None,
        n_flagged: Optional[int] = None,
        metrics: Optional[dict] = None,
        at: Optional[str] = None,
    ) -> str:
        """Record one processing run (and, for inbox runs, per-request labels). Returns run_id."""
        if run_type not in ("inbox", "replay"):
            raise ValueError("run_type must be 'inbox' or 'replay'.")
        run_id = _new_id("run")
        n = len(results) if n_requests is None else n_requests
        flagged = sum(r.needs_review for r in results) if n_flagged is None else n_flagged
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)",
                (run_id, run_type, dataset, engine, at or _now(), n, int(flagged),
                 json.dumps(metrics) if metrics is not None else None),
            )
            conn.executemany(
                "INSERT INTO processed VALUES (?,?,?,?,?,?,?,?)",
                [(run_id, r.request_id, r.category, r.priority, r.team, int(r.needs_review),
                  int(r.error is not None), r.processed_at) for r in results],
            )
        return run_id

    def save_review(
        self,
        result: TriageResult,
        final: dict[str, str],
        *,
        run_id: Optional[str] = None,
        note: str = "",
        reviewer: str = "",
        at: Optional[str] = None,
    ) -> str:
        """Store a reviewer decision. 'approved' if nothing changed, otherwise 'corrected'."""
        allowed = {"category": CATEGORIES, "priority": PRIORITIES, "team": TEAMS}
        for field in REVIEW_FIELDS:
            if final.get(field) not in allowed[field]:
                raise ValueError(f"Invalid {field}: {final.get(field)!r}.")
        changed = [f for f in REVIEW_FIELDS if final[f] != getattr(result, f)]
        review_id = _new_id("rev")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (review_id, run_id, result.request_id, result.engine, at or _now(),
                 "corrected" if changed else "approved",
                 result.category, result.priority, result.team,
                 final["category"], final["priority"], final["team"],
                 ",".join(changed), note.strip()[:500], reviewer.strip()[:60]),
            )
        return review_id

    # ---- reads -------------------------------------------------------------
    def _frame(self, sql: str, params: tuple = ()) -> pd.DataFrame:
        with self._connect() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def runs(self, limit: int = 20, month: Optional[str] = None) -> pd.DataFrame:
        return self._frame("SELECT * FROM runs WHERE created_at LIKE ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                           ((month or "") + "%", limit))

    def reviews(self, limit: int = 200) -> pd.DataFrame:
        return self._frame("SELECT * FROM reviews ORDER BY reviewed_at DESC, rowid DESC LIMIT ?", (limit,))

    def reviews_for(self, request_id: str) -> pd.DataFrame:
        return self._frame("SELECT * FROM reviews WHERE request_id = ? ORDER BY rowid DESC", (request_id,))

    def processed(self) -> pd.DataFrame:
        return self._frame("SELECT * FROM processed")

    def months(self) -> list[str]:
        """Months (YYYY-MM, newest first) that have any recorded run or review."""
        frame = self._frame("SELECT substr(created_at, 1, 7) AS m FROM runs UNION "
                            "SELECT substr(reviewed_at, 1, 7) FROM reviews ORDER BY m DESC")
        return [m for m in frame["m"].tolist() if m]

    def latest_replay(self, month: Optional[str] = None) -> Optional[dict]:
        frame = self._frame("SELECT * FROM runs WHERE run_type='replay' AND metrics_json IS NOT NULL "
                            "AND created_at LIKE ? ORDER BY created_at DESC, rowid DESC LIMIT 1", ((month or "") + "%",))
        if frame.empty:
            return None
        row = frame.iloc[0].to_dict()
        row["metrics"] = json.loads(row.pop("metrics_json"))
        return row

    def review_summary(self, month: Optional[str] = None) -> dict:
        """Adoption view: how often reviewers accept the proposal unchanged."""
        frame = self._frame("SELECT decision, fields_changed FROM reviews WHERE reviewed_at LIKE ?", ((month or "") + "%",))
        total = len(frame)
        corrected = int((frame["decision"] == "corrected").sum()) if total else 0
        by_field = {f: int(frame["fields_changed"].str.contains(f).sum()) if total else 0 for f in REVIEW_FIELDS}
        return {
            "total": total,
            "approved": total - corrected,
            "corrected": corrected,
            "acceptance_rate": (total - corrected) / total if total else None,
            "corrections_by_field": by_field,
        }
