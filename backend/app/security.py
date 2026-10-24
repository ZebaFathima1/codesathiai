"""Safe ZIP handling.

The single most dangerous operation in this application is unpacking an
archive that an untrusted user uploaded. This module is deliberately strict:

* paths are normalised and rejected if absolute, containing ``..`` segments,
  Windows drive letters, or NUL bytes;
* symbolic links and other non-regular entries are refused outright;
* file count, per-file size, total extracted size and compression ratio are
  all bounded *before* a single byte is written;
* extraction streams through a hard byte budget so a lying header cannot
  exhaust the disk;
* dependency, build and binary artefacts are skipped because they add no
  value to a code-understanding tool;
* uploaded code is never imported or executed.
"""
from __future__ import annotations

import os
import re
import stat
import zipfile
from dataclasses import dataclass, field

from .config import (
    MAX_ARCHIVE_FILES,
    MAX_COMPRESSION_RATIO,
    MAX_EXTRACTED_BYTES,
    MAX_FILE_BYTES,
    MAX_UPLOAD_BYTES,
    MIN_RATIO_CHECK_BYTES,
)

# Directories that never help explain a project and are frequently enormous.
IGNORED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "bower_components", "vendor",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "venv", ".venv", "env", ".env", "dist", "build", "out", "target",
    ".next", ".nuxt", ".cache", "coverage", ".idea", ".vscode", ".gradle",
    "site-packages", ".terraform", "Pods", "bin", "obj",
}

# Extensions we index. Anything else is dropped at extraction time.
TEXT_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".java", ".kt", ".kts", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh",
    ".cs", ".go", ".rb", ".php", ".rs", ".swift", ".scala", ".sh", ".bash",
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".properties",
    ".xml", ".md", ".markdown", ".rst", ".txt", ".sql", ".env.example",
    ".dockerfile", ".gitignore", ".editorconfig",
}

# Explicitly refused extensions: binaries, archives, media, secrets, data.
BINARY_EXTENSIONS = {
    ".exe", ".dll", ".so", ".dylib", ".bin", ".class", ".jar", ".war", ".o",
    ".a", ".lib", ".obj", ".pdb", ".wasm", ".pyc", ".pyo",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svgz",
    ".tiff", ".psd", ".ai", ".eps", ".pdf", ".zip", ".tar", ".gz", ".bz2",
    ".xz", ".7z", ".rar", ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".wav",
    ".ogg", ".flac", ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".db", ".sqlite", ".sqlite3", ".mdb", ".dat", ".pkl", ".npy", ".npz",
    ".h5", ".pt", ".onnx", ".pem", ".key", ".p12", ".pfx", ".keystore",
    ".lock", ".map",
}

# Files whose contents should never be shipped into a prompt.
SECRET_FILENAMES = {
    ".env", ".env.local", ".env.production", "id_rsa", "id_dsa",
    "credentials", "credentials.json", "secrets.json", "secrets.yaml",
    ".netrc", ".htpasswd",
}

_DRIVE_RE = re.compile(r"^[a-zA-Z]:")


@dataclass
class ExtractionResult:
    """What was written to disk, and what was deliberately left out."""

    root: str
    files: list[str] = field(default_factory=list)
    total_bytes: int = 0
    skipped_entries: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)

    def _note(self, reason: str) -> None:
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1
        self.skipped_entries += 1


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """True when the entry's Unix mode marks it a symbolic link."""
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _safe_member_path(name: str) -> str | None:
    """Return a safe relative POSIX path, or None if the name is hostile."""
    if not name or "\x00" in name:
        return None
    # Normalise separators and strip any leading "./".
    cleaned = name.replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if cleaned.startswith("/") or _DRIVE_RE.match(cleaned):
        return None
    parts = [p for p in cleaned.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    if not parts:
        return None
    return "/".join(parts)


def _extension_of(path: str) -> str:
    base = os.path.basename(path).lower()
    if base in SECRET_FILENAMES:
        return ""
    if base.startswith(".env"):
        return ""
    root, ext = os.path.splitext(base)
    if ext == "" and base.startswith("."):
        # Dotfiles such as .gitignore are handled by the allow-list check.
        return base
    if ext == ".example" and root.startswith(".env"):
        return ""
    return ext


def _should_skip(path: str) -> str | None:
    """Return a reason string if ``path`` should not be extracted."""
    parts = path.split("/")
    for part in parts[:-1]:
        if part in IGNORED_DIRS:
            return "ignored_directory"
    base = parts[-1].lower()
    if base in SECRET_FILENAMES or base.startswith(".env"):
        return "secret_file"
    if base.endswith(".min.js") or base.endswith(".min.css"):
        return "minified"
    ext = _extension_of(path)
    if ext in BINARY_EXTENSIONS:
        return "binary_extension"
    if ext in TEXT_EXTENSIONS:
        return None
    if base in {"dockerfile", "makefile", "procfile", "license", "licence"}:
        return None
    return "unsupported_extension"


def inspect_upload(filename: str, size: int) -> None:
    """Validate the raw upload before it is touched."""
    from .errors import UploadError

    if not filename:
        raise UploadError("No file was provided.", code="missing_filename")
    if not filename.lower().endswith(".zip"):
        raise UploadError("Only .zip archives are supported.", code="unsupported_filetype")
    if size <= 0:
        raise UploadError("The uploaded file is empty.", code="empty_file")
    if size > MAX_UPLOAD_BYTES:
        raise UploadError(
            f"Archive is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
            code="file_too_large",
            details={"max_bytes": MAX_UPLOAD_BYTES, "received_bytes": size},
        )


def safe_extract_zip(zip_path: str, dest_dir: str) -> ExtractionResult:
    """Extract ``zip_path`` into ``dest_dir`` applying every safety rule.

    Raises :class:`UploadError` when the archive is hostile, malformed, or
    exceeds a configured limit.
    """
    from .errors import UploadError

    os.makedirs(dest_dir, exist_ok=True)
    dest_real = os.path.realpath(dest_dir)
    result = ExtractionResult(root=dest_real)

    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise UploadError("That file is not a valid ZIP archive.",
                          code="bad_zip") from exc

    with zf:
        infos = zf.infolist()
        if not infos:
            raise UploadError("The archive is empty.", code="empty_archive")

        planned_total = 0
        planned_count = 0
        planned: list[tuple[zipfile.ZipInfo, str]] = []

        for info in infos:
            if info.is_dir():
                continue

            rel = _safe_member_path(info.filename)
            if rel is None:
                result._note("unsafe_path")
                continue

            if _is_symlink(info):
                result._note("symlink")
                continue

            reason = _should_skip(rel)
            if reason is not None:
                result._note(reason)
                continue

            if info.file_size > MAX_FILE_BYTES:
                result._note("file_too_large")
                continue

            # Compression-ratio guard: a small archive that claims to expand
            # enormously is the classic zip bomb.
            if (info.file_size > MIN_RATIO_CHECK_BYTES
                    and info.compress_size > 0
                    and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO):
                raise UploadError(
                    "The archive looks like a decompression bomb and was rejected.",
                    code="compression_bomb",
                )

            planned_count += 1
            if planned_count > MAX_ARCHIVE_FILES:
                raise UploadError(
                    f"Archive contains more than {MAX_ARCHIVE_FILES} files.",
                    code="too_many_files",
                    details={"max_files": MAX_ARCHIVE_FILES},
                )

            planned_total += info.file_size
            if planned_total > MAX_EXTRACTED_BYTES:
                raise UploadError(
                    f"Archive expands beyond the {MAX_EXTRACTED_BYTES // (1024 * 1024)} MB limit.",
                    code="expanded_too_large",
                    details={"max_bytes": MAX_EXTRACTED_BYTES},
                )

            planned.append((info, rel))

        if not planned:
            raise UploadError(
                "No indexable source files were found in the archive.",
                code="no_source_files",
                details={"skipped": result.skip_reasons},
            )

        written = 0
        for info, rel in planned:
            target = os.path.realpath(os.path.join(dest_real, rel))
            # Belt and braces: the resolved path must stay inside dest.
            if not (target == dest_real or target.startswith(dest_real + os.sep)):
                result._note("unsafe_path")
                continue

            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                with zf.open(info) as src, open(target, "wb") as dst:
                    while True:
                        chunk = src.read(65536)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > MAX_EXTRACTED_BYTES:
                            raise UploadError(
                                "Extraction exceeded the allowed size and was aborted.",
                                code="expanded_too_large",
                            )
                        dst.write(chunk)
            except UploadError:
                raise
            except (OSError, zipfile.BadZipFile) as exc:
                result._note("read_error")
                continue

            result.files.append(rel)
            result.total_bytes += info.file_size

    return result
