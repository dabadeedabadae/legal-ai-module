import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _PROJECT_ROOT / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = _DATA_DIR / "query_history.jsonl"
MAX_RECORDS = 1000

_history: list[dict] = []
_lock = Lock()
_loaded = False


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not HISTORY_FILE.exists():
        return
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    _history.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if len(_history) > MAX_RECORDS:
            del _history[: len(_history) - MAX_RECORDS]
    except Exception:
        pass


def _append_to_disk(record: dict) -> None:
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _rotate_locked() -> None:
    if len(_history) <= MAX_RECORDS:
        return
    keep = _history[-MAX_RECORDS:]
    try:
        tmp = HISTORY_FILE.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for rec in keep:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp, HISTORY_FILE)
    except Exception:
        return
    _history.clear()
    _history.extend(keep)


def save_query(
    question: str,
    result: dict,
    db_available: bool = True,
    source: str = "api",
    user_id: Optional[int] = None,
    error: Optional[str] = None,
) -> str:
    with _lock:
        _load()
        query_id = str(uuid.uuid4())
        record = {
            "id": query_id,
            "question": question,
            "result": result,
            "db_available": db_available,
            "source": source,
            "user_id": user_id,
            "error": error,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _history.append(record)
        _append_to_disk(record)
        _rotate_locked()
        return query_id


def all_queries() -> list[dict]:
    with _lock:
        _load()
        return list(_history)


def get_query(query_id: str) -> Optional[dict]:
    with _lock:
        _load()
        for q in _history:
            if q["id"] == query_id:
                return q
    return None
