"""Content-addressed raw snapshot store and run history.

Raw bytes are written once under their SHA-256 and never overwritten, so evidence from earlier runs
remains verifiable after a refresh.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable


class SnapshotStore:
    def __init__(self, root: str | Path | None):
        self.root = Path(root) if root else None
        self._lock = threading.Lock()
        self._writing: set[str] = set()
        if self.root:
            (self.root / "snapshots").mkdir(parents=True, exist_ok=True)

    def put(self, sha256: str, body: bytes) -> str | None:
        """Store bytes once; return the store-relative path, or None when storage is disabled."""
        if not self.root or not sha256:
            return None
        relative = f"snapshots/{sha256[:2]}/{sha256}.gz"
        target = self.root / relative
        if target.exists():
            return relative
        with self._lock:  # many companies can cite the same bulk file; write it once
            if sha256 in self._writing or target.exists():
                return relative
            self._writing.add(sha256)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(f".{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp")
            with gzip.open(temporary, "wb", compresslevel=6) as handle:
                handle.write(body)
            try:
                os.replace(temporary, target)
            except OSError:
                temporary.unlink(missing_ok=True)
        finally:
            with self._lock:
                self._writing.discard(sha256)
        return relative

    def get(self, relative: str) -> bytes | None:
        if not self.root:
            return None
        path = self.root / relative
        if not path.exists():
            return None
        with gzip.open(path, "rb") as handle:
            return handle.read()

    # ---- run history ------------------------------------------------------------------------
    def latest_envelopes_path(self) -> Path | None:
        if not self.root:
            return None
        path = self.root / "latest" / "envelopes.jsonl"
        return path if path.exists() else None

    def archive_run(self, run_id: str, envelopes_path: Path) -> Path | None:
        """Copy the finished run into history and make it the latest previous snapshot."""
        if not self.root:
            return None
        safe_run = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in run_id)
        history = self.root / "runs" / safe_run
        history.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(envelopes_path, history / "envelopes.jsonl")
        latest = self.root / "latest"
        latest.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(envelopes_path, latest / "envelopes.jsonl")
        return history


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl_atomic(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n")
    os.replace(temporary, target)
