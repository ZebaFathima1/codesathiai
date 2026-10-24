"""Project persistence.

Replaces the old in-memory store. Everything a project needs — its name, its
stats, and the exact text of every indexed file — lives in the database, so a
stateless serverless function can serve any request.

The code index itself is *derived*: it is rebuilt from the stored file rows on
demand. Indexing is deterministic, so the rebuilt index is identical to the one
produced from the filesystem (there is a test asserting exactly that). A small
in-process cache avoids repeating the work within a warm instance.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import config
from .errors import ForbiddenError, NotFoundError, UploadError, ValidationError
from .indexer import CodeIndex, index_content
from .models import Project, ProjectFile, User
from .security import IGNORED_DIRS

log = logging.getLogger(__name__)

SAMPLE_NAME = "ShopEasy API (sample)"
SAMPLE_SOURCE = "sample"

# Bounded cache of rebuilt indexes, keyed by (project_id, file_count).
_CACHE: "OrderedDict[tuple[str, int], CodeIndex]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 8


def _cache_get(key: tuple[str, int]) -> CodeIndex | None:
    with _CACHE_LOCK:
        index = _CACHE.get(key)
        if index is not None:
            _CACHE.move_to_end(key)
        return index


def _cache_put(key: tuple[str, int], index: CodeIndex) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = index
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def invalidate_cache(project_id: str) -> None:
    with _CACHE_LOCK:
        for key in [k for k in _CACHE if k[0] == project_id]:
            _CACHE.pop(key, None)


# ---------------------------------------------------------------------------
# Index rebuild
# ---------------------------------------------------------------------------
def build_index(db: Session, project: Project) -> CodeIndex:
    """Rebuild the code index for a project from its stored files."""
    key = (project.id, project.file_count)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    rows = db.execute(
        select(ProjectFile.path, ProjectFile.content)
        .where(ProjectFile.project_id == project.id)
        .order_by(ProjectFile.path)
    ).all()
    index = CodeIndex.from_records([(path, content) for path, content in rows])
    _cache_put(key, index)
    return index


def _stats_for(index: CodeIndex) -> dict:
    return index.stats()


# ---------------------------------------------------------------------------
# Creating and filling projects
# ---------------------------------------------------------------------------
def _normalise_entries(entries) -> list[tuple[str, str]]:
    """Validate an incoming batch of ``{path, content}`` items."""
    if not isinstance(entries, list) or not entries:
        raise ValidationError("No files were provided.", code="no_files")

    cleaned: list[tuple[str, str]] = []
    for item in entries:
        if not isinstance(item, dict):
            raise ValidationError("Each file must be an object.", code="bad_file_entry")
        path = str(item.get("path") or "").replace("\\", "/")
        # Absolute paths and parent traversal are refused rather than quietly
        # rewritten, matching the server-side ZIP extraction rules. The browser
        # strips the archive root before sending, so this is defence in depth.
        if (not path or path.startswith("/") or ".." in path.split("/")
                or ":" in path.split("/")[0]):
            raise UploadError(f"Unsafe file path: {path!r}", code="unsafe_path")
        if len(path) > 500:
            raise UploadError("A file path was too long.", code="unsafe_path")
        content = item.get("content")
        if not isinstance(content, str):
            content = "" if content is None else str(content)
        if len(content.encode("utf-8")) > config.MAX_INDEXED_FILE_BYTES:
            continue  # oversized file, silently skipped like the server-side path
        cleaned.append((path, content))

    if not cleaned:
        raise UploadError(
            "None of the submitted files could be indexed.",
            code="no_indexable_files",
        )
    return cleaned


def create_project(db: Session, *, name: str, user_id: str | None,
                   source: str = "upload") -> Project:
    project = Project(
        name=(name or "untitled-project")[:120],
        user_id=user_id,
        source=source,
        status="uploading",
    )
    db.add(project)
    db.flush()
    return project


def add_files(db: Session, project: Project, entries) -> int:
    """Add a batch of files to a project. Returns how many were stored."""
    cleaned = _normalise_entries(entries)

    existing = {
        row for (row,) in db.execute(
            select(ProjectFile.path).where(ProjectFile.project_id == project.id)
        ).all()
    }

    stored_bytes = db.execute(
        select(func.coalesce(func.sum(ProjectFile.size), 0))
        .where(ProjectFile.project_id == project.id)
    ).scalar_one() or 0

    added = 0
    for path, content in cleaned:
        if path in existing:
            continue
        size = len(content.encode("utf-8"))
        if stored_bytes + size > config.MAX_STORED_BYTES:
            raise UploadError(
                "This repository exceeds the storage limit for a project.",
                code="project_too_large",
                details={"max_bytes": config.MAX_STORED_BYTES},
            )
        indexed = index_content(path, content, size)
        if indexed is None:
            continue  # unsupported language: not stored
        db.add(ProjectFile(
            project_id=project.id,
            path=path,
            language=indexed.language,
            line_count=indexed.line_count,
            size=size,
            content=content,
        ))
        existing.add(path)
        stored_bytes += size
        added += 1

    project.file_count = len(existing)
    project.total_bytes = stored_bytes
    db.flush()
    invalidate_cache(project.id)
    return added


def finalize_project(db: Session, project: Project) -> Project:
    """Mark an upload complete and record the derived statistics."""
    index = build_index(db, project)
    project.stats_json = json.dumps(_stats_for(index))
    project.file_count = len(index.files)
    project.total_bytes = sum(f.size for f in index.files.values())
    project.status = "ready"
    db.flush()
    return project


def project_summary(project: Project) -> dict:
    try:
        stats = json.loads(project.stats_json or "{}")
    except json.JSONDecodeError:
        stats = {}
    payload = {
        "project_id": project.id,
        "name": project.name,
        "source": project.source,
        "status": project.status,
        "created_at": project.created_at.timestamp() if project.created_at else None,
        "stats": stats,
    }
    try:
        reasons = json.loads(project.skip_reasons_json or "{}")
    except json.JSONDecodeError:
        reasons = {}
    if project.skipped_entries:
        payload["skipped_entries"] = project.skipped_entries
        payload["skip_reasons"] = reasons
    return payload


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
def get_project(db: Session, project_id: str, *, user: User | None = None,
                require_owner: bool = False) -> Project:
    """Fetch a project, enforcing who may see it.

    The bundled sample project is public: anyone may browse it. An uploaded
    project is private to the account that uploaded it. Callers that need to
    change a project pass ``require_owner=True``.
    """
    if not project_id or not isinstance(project_id, str):
        raise ValidationError("A project id is required.", code="missing_project_id")
    try:
        import uuid as _uuid
        _uuid.UUID(project_id)
    except (ValueError, AttributeError):
        raise ValidationError("That project id is not valid.", code="bad_project_id")

    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError(
            "That project is not loaded. It may have expired or been deleted — "
            "upload it again.",
            code="project_not_found",
        )

    if project.is_public():
        return project  # the sample project is browsable by anyone

    if user is None or project.user_id != user.id:
        # Do not reveal whether someone else's project exists.
        raise NotFoundError(
            "That project is not loaded. It may have expired or been deleted — "
            "upload it again.",
            code="project_not_found",
        )
    return project


def get_owned_project(db: Session, project_id: str, user: User) -> Project:
    """Fetch a project the caller owns, for mutation."""
    project = get_project(db, project_id, user=user)
    if project.is_public():
        raise ForbiddenError(
            "The bundled sample project cannot be changed.", code="sample_is_protected"
        )
    if not project.owned_by(user.id):
        raise ForbiddenError(
            "You can only change projects you uploaded.", code="not_project_owner"
        )
    return project


def delete_project(db: Session, project: Project) -> None:
    # Callers go through get_owned_project(), which already refuses the public
    # sample project, so this only handles a real, owned project.
    db.execute(delete(ProjectFile).where(ProjectFile.project_id == project.id))
    db.delete(project)
    db.flush()
    invalidate_cache(project.id)


def list_projects(db: Session, user: User) -> list[dict]:
    rows = db.execute(
        select(Project).where(Project.user_id == user.id)
        .order_by(Project.created_at.desc()).limit(50)
    ).scalars().all()
    return [project_summary(p) for p in rows]


# ---------------------------------------------------------------------------
# Sample project
# ---------------------------------------------------------------------------
def sample_dir() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "sample_project")


def _bundled_sample_files() -> list[tuple[str, str]]:
    """Read the bundled sample repository from disk (read-only is fine)."""
    root = sample_dir()
    records: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in IGNORED_DIRS and not d.startswith(".")]
        for fname in sorted(filenames):
            abspath = os.path.join(dirpath, fname)
            rel = os.path.relpath(abspath, root).replace(os.sep, "/")
            try:
                with open(abspath, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            if index_content(rel, text) is None:
                continue
            records.append((rel, text))
    return records


def get_or_create_sample_project(db: Session) -> Project:
    """The bundled sample, seeded once and shared by every visitor."""
    project = db.execute(
        select(Project).where(Project.source == SAMPLE_SOURCE)
    ).scalars().first()
    if project is not None and project.status == "ready":
        return project

    if project is None:
        project = Project(name=SAMPLE_NAME, user_id=None,
                          source=SAMPLE_SOURCE, status="uploading")
        db.add(project)
        db.flush()

    records = _bundled_sample_files()
    if not records:
        raise UploadError("The bundled sample project could not be read.",
                          code="sample_unavailable", status_code=500)

    add_files(db, project, [{"path": p, "content": c} for p, c in records])
    finalize_project(db, project)
    log.info("Seeded the sample project with %d files", project.file_count)
    return project


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------
def cleanup_expired(db: Session) -> int:
    """Drop projects that have not been used recently."""
    cutoff = time.time() - config.PROJECT_TTL_SECONDS
    rows = db.execute(
        select(Project).where(Project.source != SAMPLE_SOURCE)
    ).scalars().all()
    removed = 0
    for project in rows:
        if project.last_used_at and project.last_used_at.timestamp() < cutoff:
            db.execute(delete(ProjectFile).where(ProjectFile.project_id == project.id))
            db.delete(project)
            invalidate_cache(project.id)
            removed += 1
    return removed


def touch(project: Project) -> None:
    from datetime import datetime, timezone
    project.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
