"""Read source data without modifying it; normalize only in memory."""
import csv
import hashlib
import json
import math
from pathlib import Path
from .models import Contractor, iso_date

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = ROOT / "data" / "contractors.csv"


def items(value):
    if value is None:
        return ()
    parts = value.split("|") if isinstance(value, str) else value
    if not isinstance(parts, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(v.strip() for v in parts if isinstance(v, str) and v.strip()))


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def flag(value):
    return value is True or str(value).strip().casefold() in ("true", "1", "yes")


def normalize(row):
    raw_busy = row.get("busy_dates")
    # Only an explicitly empty string/list means an empty calendar. Do not drop
    # empty elements from a nonempty calendar before validating its structure.
    if isinstance(raw_busy, str):
        parts = raw_busy.split("|") if raw_busy.strip() else []
    elif isinstance(raw_busy, (list, tuple)):
        parts = raw_busy
    else:
        parts = None
    known = parts is not None and all(isinstance(v, str) and bool(v.strip()) for v in parts)
    busy = items(raw_busy)
    try:
        for day in busy:
            iso_date(day)
    except ValueError:
        known = False
    raw_hours = row.get("max_hours")
    hours = number(raw_hours)
    explicitly_empty = "max_hours" in row and (raw_hours is None or isinstance(raw_hours, str) and not raw_hours.strip())
    duration_valid = explicitly_empty or hours is not None
    return Contractor(
        id=str(row.get("id") or "").strip(),
        anon_name=str(row.get("anon_name") or row.get("id") or "Без имени").strip(),
        categories=items(row.get("categories")), city=str(row.get("city") or "").strip(),
        price_from_kzt=number(row.get("price_from_kzt")),
        event_formats=items(row.get("event_formats")), languages=items(row.get("languages")),
        max_hours=hours, busy_dates=busy,
        description=str(row.get("description") or "").strip(),
        synthetic=flag(row.get("synthetic")), city_imputed=flag(row.get("city_imputed")),
        price_imputed=flag(row.get("price_imputed")), availability_known=known,
        duration_data_valid=duration_valid,
    )


class Dataset:
    def __init__(self, path=DEFAULT_DATASET):
        self.path = Path(path)
        raw = self.path.read_bytes()
        self.fingerprint = hashlib.sha256(raw).hexdigest()
        text = raw.decode("utf-8-sig")
        if self.path.suffix.lower() == ".csv":
            import io
            rows = list(csv.DictReader(io.StringIO(text, newline="")))
        elif self.path.suffix.lower() == ".jsonl":
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        elif self.path.suffix.lower() == ".json":
            rows = json.loads(text)
        else:
            raise ValueError("Dataset must be CSV, JSON or JSONL.")
        if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) for r in rows):
            raise ValueError("Dataset must contain a nonempty list of objects.")
        self.contractors = tuple(normalize(row) for row in rows)
        ids = [c.id for c in self.contractors]
        if any(not id_ for id_ in ids) or len(ids) != len(set(ids)):
            raise ValueError("Dataset IDs must be present and unique.")

    def metadata(self):
        from .models import CALENDAR_START, CALENDAR_END
        candidates = self.contractors
        return {
            "total": len(candidates), "sha256": self.fingerprint,
            "cities": sorted({c.city for c in candidates if c.city}),
            "categories": sorted({v for c in candidates for v in c.categories}),
            "event_formats": sorted({v for c in candidates for v in c.event_formats}),
            "languages": sorted({v for c in candidates for v in c.languages}),
            "calendar_start": CALENDAR_START, "calendar_end": CALENDAR_END,
            "synthetic": sum(c.synthetic for c in candidates),
            "city_imputed": sum(c.city_imputed for c in candidates),
            "price_imputed": sum(c.price_imputed for c in candidates),
        }
