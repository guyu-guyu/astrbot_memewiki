"""Persistent storage and matching helpers for the Meme Wiki plugin.

The store deliberately uses a small JSON document instead of AstrBot's KV API so
that the data remains inspectable and can be migrated independently of plugin
configuration. Writes are atomic, which prevents a process interruption from
leaving a partially written wiki.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_WHITESPACE_RE = re.compile(r"\s+")
_MAX_TERM_LENGTH = 120
_MAX_TEXT_LENGTH = 4000


def normalize_text(value: str) -> str:
    """Normalize text for matching while preserving the original display value."""

    value = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return _WHITESPACE_RE.sub(" ", value)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: str, limit: int) -> str:
    value = str(value or "").strip()
    return value[:limit]


def _clean_list(values: Any, limit: int = 20) -> list[str]:
    if isinstance(values, str):
        values = re.split(r"[\n,，、;；]+", values)
    if not isinstance(values, (list, tuple, set)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _clean_text(str(value), _MAX_TEXT_LENGTH)
        key = normalize_text(item)
        if item and key not in seen:
            result.append(item)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


@dataclass
class MemeEntry:
    """A single meme/slang explanation stored by the plugin."""

    term: str
    meaning: str
    usage: str
    examples: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    source: str = "chat"
    confidence: float = 0.7
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    lookup_count: int = 0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MemeEntry | None":
        term = _clean_text(raw.get("term", ""), _MAX_TERM_LENGTH)
        meaning = _clean_text(raw.get("meaning", ""), _MAX_TEXT_LENGTH)
        usage = _clean_text(raw.get("usage", ""), _MAX_TEXT_LENGTH)
        if not term or not meaning:
            return None
        try:
            confidence = min(1.0, max(0.0, float(raw.get("confidence", 0.7))))
        except (TypeError, ValueError):
            confidence = 0.7
        try:
            lookup_count = max(0, int(raw.get("lookup_count", 0)))
        except (TypeError, ValueError):
            lookup_count = 0
        return cls(
            term=term,
            meaning=meaning,
            usage=usage,
            examples=_clean_list(raw.get("examples", [])),
            aliases=_clean_list(raw.get("aliases", [])),
            source=_clean_text(raw.get("source", "chat"), 80) or "chat",
            confidence=confidence,
            created_at=str(raw.get("created_at") or _now()),
            updated_at=str(raw.get("updated_at") or _now()),
            lookup_count=lookup_count,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MemeWikiStore:
    """Thread-safe JSON-backed store with exact and fuzzy matching."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_entries: int = 1000,
    ) -> None:
        self.path = Path(path)
        self.max_entries = max(1, int(max_entries))
        self._entries: dict[str, MemeEntry] = {}
        self._loaded = False
        self._lock = threading.RLock()

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return
            except (OSError, UnicodeError, json.JSONDecodeError):
                # A malformed file should not prevent AstrBot from starting.
                return
            entries = raw.get("entries", raw) if isinstance(raw, dict) else {}
            if not isinstance(entries, dict):
                return
            for key, value in entries.items():
                if not isinstance(value, dict):
                    continue
                entry = MemeEntry.from_dict(value)
                if entry:
                    self._entries[normalize_text(key or entry.term)] = entry

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": _now(),
            "entries": {key: entry.to_dict() for key, entry in self._entries.items()},
        }
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.stem}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as temp_file:
                json.dump(payload, temp_file, ensure_ascii=False, indent=2)
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_name, self.path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def count(self) -> int:
        self._ensure_loaded()
        with self._lock:
            return len(self._entries)

    def all(self, limit: int | None = None) -> list[MemeEntry]:
        self._ensure_loaded()
        with self._lock:
            values = sorted(
                self._entries.values(),
                key=lambda entry: (entry.updated_at, entry.term),
                reverse=True,
            )
            return values[:limit] if limit else values

    def search(self, query: str, limit: int = 5) -> list[MemeEntry]:
        self._ensure_loaded()
        needle = normalize_text(query)
        if not needle:
            return []
        scored: list[tuple[int, MemeEntry]] = []
        with self._lock:
            for entry in self._entries.values():
                candidates = [entry.term, *entry.aliases]
                normalized = [normalize_text(candidate) for candidate in candidates]
                score = 0
                if needle == normalized[0]:
                    score = 100
                elif needle in normalized:
                    score = 90
                elif any(needle in candidate for candidate in normalized):
                    score = 70
                elif any(candidate in needle and len(candidate) >= 2 for candidate in normalized):
                    score = 50
                if score:
                    scored.append((score, entry))
        scored.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
        return [entry for _, entry in scored[: max(1, limit)]]

    def find_in_text(self, text: str, limit: int = 5) -> list[MemeEntry]:
        """Return entries whose term or alias appears in a message."""

        self._ensure_loaded()
        haystack = normalize_text(text)
        if not haystack:
            return []
        matches: list[tuple[int, MemeEntry]] = []
        with self._lock:
            for entry in self._entries.values():
                candidates = [entry.term, *entry.aliases]
                lengths = [len(normalize_text(candidate)) for candidate in candidates]
                if any(
                    length >= 2 and normalize_text(candidate) in haystack
                    for candidate, length in zip(candidates, lengths)
                ):
                    matches.append((max(lengths, default=0), entry))
        matches.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in matches[: max(1, limit)]]

    def upsert(
        self,
        term: str,
        meaning: str,
        usage: str = "",
        *,
        examples: Any = None,
        aliases: Any = None,
        source: str = "chat",
        confidence: float = 0.7,
    ) -> MemeEntry:
        term = _clean_text(term, _MAX_TERM_LENGTH)
        meaning = _clean_text(meaning, _MAX_TEXT_LENGTH)
        usage = _clean_text(usage, _MAX_TEXT_LENGTH)
        if not term or not meaning:
            raise ValueError("term and meaning are required")
        key = normalize_text(term)
        if not key:
            raise ValueError("term cannot be empty")
        try:
            confidence = min(1.0, max(0.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.7
        with self._lock:
            self._ensure_loaded()
            previous = self._entries.get(key)
            entry = MemeEntry(
                term=term,
                meaning=meaning,
                usage=usage,
                examples=_clean_list(examples or []),
                aliases=_clean_list(aliases or []),
                source=_clean_text(source, 80) or "chat",
                confidence=confidence,
                created_at=previous.created_at if previous else _now(),
                updated_at=_now(),
                lookup_count=previous.lookup_count if previous else 0,
            )
            self._entries[key] = entry
            if len(self._entries) > self.max_entries:
                oldest_key = min(
                    self._entries,
                    key=lambda item: self._entries[item].updated_at,
                )
                del self._entries[oldest_key]
            self._write_locked()
            return entry

    def touch(self, term: str) -> None:
        key = normalize_text(term)
        if not key:
            return
        with self._lock:
            self._ensure_loaded()
            entry = self._entries.get(key)
            if entry is None:
                matches = self.search(term, limit=1)
                entry = matches[0] if matches else None
            if entry is None:
                return
            entry.lookup_count += 1
            entry.updated_at = _now()
            self._write_locked()

    def delete(self, term: str) -> bool:
        key = normalize_text(term)
        with self._lock:
            self._ensure_loaded()
            if key not in self._entries:
                matches = self.search(term, limit=1)
                if not matches:
                    return False
                key = normalize_text(matches[0].term)
            del self._entries[key]
            self._write_locked()
            return True
