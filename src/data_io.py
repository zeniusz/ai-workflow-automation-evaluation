"""Loading and validating request data (built-in datasets and user uploads)."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from .config import HOLDOUT_PATH, MAX_REQUEST_CHARS, MAX_UPLOAD_BYTES, MAX_UPLOAD_ROWS, SAMPLE_PATH
from .triage import CATEGORIES, PRIORITIES, TEAMS

REQUEST_COLUMNS = ["request_id", "requester", "request_text"]
LABEL_COLUMNS = ["expected_category", "expected_priority", "expected_team"]


class DataValidationError(ValueError):
    """Raised with a user-readable message when a CSV cannot be used."""


def _read_csv(source: bytes | str | Path) -> pd.DataFrame:
    try:
        if isinstance(source, bytes):
            if len(source) > MAX_UPLOAD_BYTES:
                raise DataValidationError(f"File is larger than {MAX_UPLOAD_BYTES // 1000} KB.")
            text = source.decode("utf-8-sig")
            frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
        else:
            frame = pd.read_csv(source, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DataValidationError("File is not UTF-8 text. Save the CSV as 'CSV UTF-8' and try again.") from exc
    except pd.errors.EmptyDataError as exc:
        raise DataValidationError("The CSV file is empty.") from exc
    except pd.errors.ParserError as exc:
        raise DataValidationError("The file could not be parsed as CSV. Check quotes and delimiters.") from exc
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    return frame


def _check_columns(frame: pd.DataFrame, required: list[str]) -> None:
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise DataValidationError(
            f"Missing required column(s): {', '.join(missing)}. Found: {', '.join(frame.columns) or 'none'}."
        )


def _normalise_requests(frame: pd.DataFrame, *, id_prefix: str) -> pd.DataFrame:
    """Shared checks: text present and not too long, unique ids, row limit."""
    if frame.empty:
        raise DataValidationError("The CSV has a header but no data rows.")
    if len(frame) > MAX_UPLOAD_ROWS:
        raise DataValidationError(f"The CSV has {len(frame)} rows; the limit is {MAX_UPLOAD_ROWS}.")
    frame = frame.copy()
    for col in ("request_id", "requester"):
        if col not in frame.columns:
            frame[col] = ""
        frame[col] = frame[col].astype(str).str.strip()
    frame["request_text"] = frame["request_text"].astype(str).str.strip()

    blank = frame.index[frame["request_text"] == ""].tolist()
    if blank:
        raise DataValidationError("Empty request_text in row(s): " + ", ".join(str(i + 2) for i in blank[:10]) + ".")
    long = frame.index[frame["request_text"].str.len() > MAX_REQUEST_CHARS].tolist()
    if long:
        raise DataValidationError(
            f"request_text longer than {MAX_REQUEST_CHARS} characters in row(s): "
            + ", ".join(str(i + 2) for i in long[:10]) + "."
        )
    generated = frame["request_id"] == ""
    frame.loc[generated, "request_id"] = [f"{id_prefix}-{i + 1:04d}" for i in frame.index[generated]]
    dupes = frame.loc[frame["request_id"].duplicated(), "request_id"].unique().tolist()
    if dupes:
        raise DataValidationError("Duplicate request_id value(s): " + ", ".join(dupes[:5]) + ".")
    return frame


def load_requests_csv(data: bytes) -> pd.DataFrame:
    """Validate an uploaded request CSV. Needs request_text; request_id and requester are optional."""
    frame = _read_csv(data)
    _check_columns(frame, ["request_text"])
    return _normalise_requests(frame, id_prefix="UP")[REQUEST_COLUMNS].reset_index(drop=True)


def load_labelled_csv(source: bytes | str | Path) -> pd.DataFrame:
    """Load a labelled evaluation set; labels must use the fixed category/priority/team vocabulary."""
    frame = _read_csv(source)
    _check_columns(frame, ["request_text", *LABEL_COLUMNS])
    frame = _normalise_requests(frame, id_prefix="LB")
    for col, allowed in zip(LABEL_COLUMNS, (CATEGORIES, PRIORITIES, TEAMS)):
        frame[col] = frame[col].astype(str).str.strip()
        bad = sorted(set(frame[col]) - set(allowed))
        if bad:
            raise DataValidationError(f"Unknown value(s) in {col}: {', '.join(bad)}. Allowed: {', '.join(allowed)}.")
    return frame[REQUEST_COLUMNS + LABEL_COLUMNS].reset_index(drop=True)


def load_sample() -> pd.DataFrame:
    return load_labelled_csv(SAMPLE_PATH)


def load_holdout() -> pd.DataFrame:
    return load_labelled_csv(HOLDOUT_PATH)


def template_csv() -> bytes:
    """Downloadable upload template with two fictional example rows."""
    example = pd.DataFrame(
        {
            "request_id": ["EX-001", "EX-002"],
            "requester": ["Alex Example", "Sam Sample"],
            "request_text": [
                "The printer in Radiology is not working. Contact: alex@clinic.example",
                "Please order 10 boxes of gloves for the Pharmacy.",
            ],
        }
    )
    return example.to_csv(index=False).encode("utf-8")
