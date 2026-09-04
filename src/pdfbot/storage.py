"""Per-job scratch directories on the volume shared by the bot and the workers.

Files never travel through the broker -- only paths do. The bot writes the upload into a workspace,
the worker reads it and writes ``output.*`` alongside, the bot uploads that and deletes the
directory. :func:`sweep_stale` is the backstop for jobs that died before cleanup.
"""

import logging
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


logger = logging.getLogger(__name__)

#: Job ids are generated, never user-supplied -- but they arrive back from the broker as strings,
#: so they are re-validated before being joined onto a path.
_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def new_job_id() -> str:
    return uuid.uuid4().hex


class UnsafeJobIdError(ValueError):
    """A job id that could escape the jobs directory."""


@dataclass(frozen=True, slots=True)
class JobWorkspace:
    """A directory holding one job's inputs and outputs."""

    job_id: str
    root: Path

    @staticmethod
    def _validate(job_id: str) -> str:
        if not _JOB_ID_RE.match(job_id):
            raise UnsafeJobIdError(f"malformed job id: {job_id!r}")
        return job_id

    @classmethod
    def create(cls, jobs_dir: Path, job_id: str | None = None) -> JobWorkspace:
        """Make a fresh workspace. Called by the bot when a job is accepted."""
        job_id = cls._validate(job_id or new_job_id())
        root = jobs_dir / job_id
        root.mkdir(parents=True, exist_ok=True)
        return cls(job_id=job_id, root=root)

    @classmethod
    def attach(cls, jobs_dir: Path, job_id: str) -> JobWorkspace:
        """Open an existing workspace by id. Called by the worker.

        Raises:
            UnsafeJobIdError: id is not a bare uuid hex, so it could contain path traversal.
            FileNotFoundError: the workspace is gone (cancelled, or swept).
        """
        job_id = cls._validate(job_id)
        root = jobs_dir / job_id
        if not root.is_dir():
            raise FileNotFoundError(f"workspace {job_id} does not exist")
        return cls(job_id=job_id, root=root)

    def input_path(self, index: int = 0, suffix: str = ".pdf") -> Path:
        """Path for the ``index``-th uploaded document."""
        return self.root / f"input_{index:03d}{suffix}"

    def output_path(self, suffix: str = ".pdf") -> Path:
        return self.root / f"output{suffix}"

    def inputs(self) -> list[Path]:
        """Every uploaded document, in upload order."""
        return sorted(self.root.glob("input_*"))

    def cleanup(self) -> None:
        """Remove the whole workspace. Safe to call twice."""
        shutil.rmtree(self.root, ignore_errors=True)


def sweep_stale(jobs_dir: Path, ttl_seconds: int) -> int:
    """Delete workspaces older than ``ttl_seconds``.

    Cancelled and crashed jobs leave directories behind; without this the shared volume grows
    without bound. Returns the number of directories removed.
    """
    if not jobs_dir.is_dir():
        return 0
    cutoff = time.time() - ttl_seconds
    removed = 0
    for entry in jobs_dir.iterdir():
        if not entry.is_dir():
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        except OSError:
            logger.warning("could not sweep %s", entry, exc_info=True)
    if removed:
        logger.info("swept %d stale job workspaces", removed)
    return removed
