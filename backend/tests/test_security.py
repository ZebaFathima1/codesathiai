"""Tests for safe archive extraction."""

import os
import zipfile

import pytest

from app.errors import UploadError
from app.security import inspect_upload, safe_extract_zip
from tests.conftest import make_zip_bytes, make_zip_with_raw_entries


def _write(tmp_path, data: bytes) -> str:
    p = tmp_path / "archive.zip"
    p.write_bytes(data)
    return str(p)


def test_extracts_text_files(tmp_path):
    data = make_zip_bytes({"src/app.py": "print('hi')\n", "README.md": "# hi\n"})
    result = safe_extract_zip(_write(tmp_path, data), str(tmp_path / "out"))
    assert sorted(result.files) == ["README.md", "src/app.py"]
    assert (tmp_path / "out" / "src" / "app.py").read_text() == "print('hi')\n"


def test_rejects_path_traversal(tmp_path):
    data = make_zip_with_raw_entries([("../../evil.py", b"bad"), ("ok.py", b"fine")])
    result = safe_extract_zip(_write(tmp_path, data), str(tmp_path / "out"))
    assert result.files == ["ok.py"]
    assert result.skip_reasons.get("unsafe_path") == 1
    assert not (tmp_path / "evil.py").exists()


def test_rejects_absolute_paths(tmp_path):
    data = make_zip_with_raw_entries([("/etc/passwd.py", b"x"), ("ok.py", b"y")])
    result = safe_extract_zip(_write(tmp_path, data), str(tmp_path / "out"))
    assert result.files == ["ok.py"]


def test_rejects_windows_drive_paths(tmp_path):
    data = make_zip_with_raw_entries([("C:/windows/system32/a.py", b"x"), ("ok.py", b"y")])
    result = safe_extract_zip(_write(tmp_path, data), str(tmp_path / "out"))
    assert result.files == ["ok.py"]


def test_rejects_symlink_entries(tmp_path):
    buf = tmp_path / "sym.zip"
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("link.py")
        info.external_attr = (0o120777 << 16)  # S_IFLNK
        zf.writestr(info, "/etc/passwd")
        zf.writestr("real.py", "print(1)")
    result = safe_extract_zip(str(buf), str(tmp_path / "out"))
    assert result.files == ["real.py"]
    assert result.skip_reasons.get("symlink") == 1


def test_skips_dependency_and_binary_files(tmp_path):
    data = make_zip_bytes({
        "node_modules/react/index.js": "x",
        ".git/config": "x",
        "logo.png": "binary",
        "app.min.js": "minified",
        "app.py": "print(1)",
    })
    result = safe_extract_zip(_write(tmp_path, data), str(tmp_path / "out"))
    assert result.files == ["app.py"]


def test_skips_secret_files(tmp_path):
    data = make_zip_bytes({".env": "SECRET=1", ".env.local": "X=1",
                           "credentials.json": "{}", "app.py": "print(1)"})
    result = safe_extract_zip(_write(tmp_path, data), str(tmp_path / "out"))
    assert result.files == ["app.py"]


def test_enforces_file_count_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("app.security.MAX_ARCHIVE_FILES", 3)
    data = make_zip_bytes({f"f{i}.py": "x" for i in range(10)})
    with pytest.raises(UploadError) as exc:
        safe_extract_zip(_write(tmp_path, data), str(tmp_path / "out"))
    assert exc.value.code == "too_many_files"


def test_enforces_per_file_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("app.security.MAX_FILE_BYTES", 50)
    data = make_zip_bytes({"big.py": "x" * 5000, "small.py": "y"})
    result = safe_extract_zip(_write(tmp_path, data), str(tmp_path / "out"))
    assert result.files == ["small.py"]
    assert result.skip_reasons.get("file_too_large") == 1


def test_enforces_total_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("app.security.MAX_EXTRACTED_BYTES", 100)
    data = make_zip_bytes({"a.py": "x" * 80, "b.py": "y" * 80})
    with pytest.raises(UploadError) as exc:
        safe_extract_zip(_write(tmp_path, data), str(tmp_path / "out"))
    assert exc.value.code == "expanded_too_large"


def test_rejects_compression_bomb(tmp_path, monkeypatch):
    monkeypatch.setattr("app.security.MAX_COMPRESSION_RATIO", 5)
    monkeypatch.setattr("app.security.MIN_RATIO_CHECK_BYTES", 100)
    data = make_zip_bytes({"bomb.py": "a" * 200_000})
    with pytest.raises(UploadError) as exc:
        safe_extract_zip(_write(tmp_path, data), str(tmp_path / "out"))
    assert exc.value.code == "compression_bomb"


def test_rejects_invalid_zip(tmp_path):
    p = tmp_path / "bad.zip"
    p.write_bytes(b"this is not a zip")
    with pytest.raises(UploadError) as exc:
        safe_extract_zip(str(p), str(tmp_path / "out"))
    assert exc.value.code == "bad_zip"


def test_rejects_archive_without_source(tmp_path):
    data = make_zip_bytes({"image.png": "x", "font.woff2": "y"})
    with pytest.raises(UploadError) as exc:
        safe_extract_zip(_write(tmp_path, data), str(tmp_path / "out"))
    assert exc.value.code == "no_source_files"


def test_inspect_upload_validation():
    with pytest.raises(UploadError):
        inspect_upload("", 100)
    with pytest.raises(UploadError):
        inspect_upload("archive.tar.gz", 100)
    with pytest.raises(UploadError):
        inspect_upload("archive.zip", 0)
    with pytest.raises(UploadError) as exc:
        inspect_upload("archive.zip", 10 ** 12)
    assert exc.value.code == "file_too_large"
    inspect_upload("archive.zip", 1024)  # should not raise
