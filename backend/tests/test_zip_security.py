import zipfile
import pytest

from zip_utils import safe_extract, validate_zip_limits


def build_zip(path, files):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def test_safe_extract_blocks_path_traversal(tmp_path):
    zip_path = tmp_path / "attack.zip"
    build_zip(zip_path, {"../evil.txt": b"x"})

    with zipfile.ZipFile(zip_path, "r") as archive:
        with pytest.raises(Exception, match="Path Traversal"):
            safe_extract(archive, str(tmp_path / "out"))


def test_validate_zip_limits_accepts_small_archive(tmp_path):
    zip_path = tmp_path / "ok.zip"
    build_zip(zip_path, {"a.pdf": b"123", "b.pdf": b"456"})
    assert validate_zip_limits(str(zip_path)) is True
