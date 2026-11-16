"""The store of reference files: their content, beside the database and never in it (P-161).

Each content is kept once, whatever the number of references that hold it, in a file
named for its SHA-256 checksum under a directory of its first two characters:
`files/9f/9f86d081...`. An upload is written as it arrives into `files/.incoming/`,
counted and checksummed on the way, so that a large file is never held in memory, and
is moved into place once it has been checked. Content is never changed in place.

The content and the database agree because content is put in place before the record
that names it is stored, and is removed only after the last record that names it is
gone, both under `LOCK`: a change that puts content in place stores its record before it
lets the lock go, and a removal looks again, under the lock, at what the database
names. There is one server process for one database, so one lock of the process is
enough.
"""

import hashlib
import logging
import os
import threading
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import ReferenceFile
from hirdir.domain import file_kinds
from hirdir.ids import new_hid

log = logging.getLogger("hirdir.store")

LOCK = threading.RLock()
INCOMING = ".incoming"
PART = ".part"
# Content that no record names is removed when the server starts once it is this old:
# younger, it may be an upload that is still being stored.
STRAY_AFTER_SECONDS = 24 * 3600
CHUNK = 1024 * 1024


class OverLimit(Exception):
    """The content of an upload is over the limit."""


def path_in(root: Path, sha256: str) -> Path:
    """Return where content with this checksum is kept under root."""
    return root / sha256[:2] / sha256


def is_checksum(text: str) -> bool:
    """Say whether text is a SHA-256 checksum as the store names content."""
    return len(text) == 64 and all(c in "0123456789abcdef" for c in text)


@dataclass
class Incoming:
    """An upload being written into the store's incoming directory."""

    path: Path
    limit: int
    size: int = 0
    head: bytes = b""
    _digest: Any = field(default_factory=hashlib.sha256)
    _handle: BinaryIO | None = None
    kept: bool = False

    def write(self, piece: bytes) -> None:
        """Add a piece of the content. Over the limit, raise OverLimit and keep nothing."""
        if self._handle is None:
            raise ValueError("the upload is finished")
        self.size += len(piece)
        if self.size > self.limit:
            self.discard()
            raise OverLimit(self.limit)
        if len(self.head) < file_kinds.HEAD_BYTES:
            self.head = (self.head + piece)[: file_kinds.HEAD_BYTES]
        self._digest.update(piece)
        self._handle.write(piece)

    def finish(self) -> str:
        """Close what was written, flushed to the disk, and return its checksum."""
        if self._handle is not None:
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._handle.close()
            self._handle = None
        return self._digest.hexdigest()

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()

    def discard(self) -> None:
        """Throw away what was written, unless it was kept."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        if not self.kept:
            self.path.unlink(missing_ok=True)


@dataclass(frozen=True)
class Store:
    """The content of reference files under one directory."""

    root: Path

    def path_of(self, sha256: str) -> Path:
        """Return where content with this checksum is kept."""
        return path_in(self.root, sha256)

    def has(self, sha256: str) -> bool:
        """Say whether the store holds content with this checksum."""
        return self.path_of(sha256).is_file()

    def receive(self, limit: int) -> Incoming:
        """Begin an upload of at most limit bytes."""
        incoming = self.root / INCOMING
        incoming.mkdir(parents=True, exist_ok=True)
        path = incoming / f"{new_hid()}{PART}"
        upload = Incoming(path=path, limit=limit)
        upload._handle = path.open("xb")
        return upload

    def receive_bytes(self, content: bytes, limit: int) -> Incoming:
        """Take content that is already in memory as an upload, finished."""
        upload = self.receive(limit)
        upload.write(content)
        upload.finish()
        return upload

    def keep(self, upload: Incoming) -> str:
        """Put a finished upload in place under its checksum, and return the checksum.

        Call it holding LOCK, and store the record that names the content before
        letting the lock go. Content that is there already is left as it is.
        """
        sha256 = upload.finish()
        target = self.path_of(sha256)
        if target.is_file():
            upload.discard()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(upload.path, target)
            os.chmod(target, 0o640)
        upload.kept = True
        return sha256

    def open(self, sha256: str) -> BinaryIO:
        """Open content for reading. A missing one raises FileNotFoundError."""
        return self.path_of(sha256).open("rb")

    def read_in_pieces(self, sha256: str) -> Iterator[bytes]:
        """Yield content a piece at a time."""
        with self.open(sha256) as handle:
            while piece := handle.read(CHUNK):
                yield piece

    def contents(self) -> Iterator[str]:
        """Yield the checksum of each content the store holds."""
        if not self.root.is_dir():
            return
        for directory in sorted(self.root.iterdir()):
            if directory.name == INCOMING or not directory.is_dir():
                continue
            for path in sorted(directory.iterdir()):
                if is_checksum(path.name) and path.is_file():
                    yield path.name

    def size(self) -> tuple[int, int]:
        """Return how many contents the store holds, and how many bytes they take."""
        count = total = 0
        for sha256 in self.contents():
            count += 1
            total += self.path_of(sha256).stat().st_size
        return count, total

    def remove_unnamed(self, db: Session, checksums: Iterable[str]) -> list[str]:
        """Remove each content of checksums that no record names any more, and return
        those removed. Call it after the change that let them go is committed."""
        removed = []
        with LOCK:
            for sha256 in set(checksums):
                named = db.scalar(
                    select(ReferenceFile.hid).where(ReferenceFile.sha256 == sha256).limit(1)
                )
                if named is None and self.has(sha256):
                    self.path_of(sha256).unlink(missing_ok=True)
                    removed.append(sha256)
        return removed

    def sweep(self, db: Session, now: float | None = None) -> tuple[int, int]:
        """Remove what an upload cut short left behind, and content that no record names
        and that is older than a day. Return how many of each were removed."""
        now = time.time() if now is None else now
        parts = strays = 0
        with LOCK:
            incoming = self.root / INCOMING
            if incoming.is_dir():
                for path in incoming.iterdir():
                    if path.name.endswith(PART):
                        path.unlink(missing_ok=True)
                        parts += 1
            named = named_by(db)
            for sha256 in list(self.contents()):
                path = self.path_of(sha256)
                if sha256 not in named and now - path.stat().st_mtime > STRAY_AFTER_SECONDS:
                    path.unlink(missing_ok=True)
                    strays += 1
        if parts or strays:
            log.info("store: removed %d unfinished uploads and %d unnamed contents", parts, strays)
        return parts, strays


def named_by(db: Session) -> set[str]:
    """Return the checksum of every content a record of the database names."""
    found = db.scalars(select(ReferenceFile.sha256).where(ReferenceFile.sha256.is_not(None)))
    return {sha256 for sha256 in found if sha256}
