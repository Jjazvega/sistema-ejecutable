import os
import zipfile

import pytest

from zip_utils import process_zip_upload


def create_zip(zip_path: str, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def test_process_zip_upload_extracts_files_and_deletes_original(tmp_path):
    zip_path = tmp_path / "docs.zip"
    destination = tmp_path / "extract"

    create_zip(
        str(zip_path),
        {
            "folder/a.pdf": b"file-a",
            "folder/b.pdf": b"file-b",
        },
    )

    extracted = process_zip_upload(str(zip_path), str(destination))

    assert len(extracted) == 2
    assert os.path.exists(destination / "folder" / "a.pdf")
    assert os.path.exists(destination / "folder" / "b.pdf")
    assert not zip_path.exists()


def test_process_zip_upload_rejects_path_traversal_and_deletes_original(tmp_path):
    zip_path = tmp_path / "unsafe.zip"
    destination = tmp_path / "extract"

    create_zip(
        str(zip_path),
        {
            "../escape.pdf": b"bad",
        },
    )

    with pytest.raises(Exception, match="Path Traversal"):
        process_zip_upload(str(zip_path), str(destination))

    assert not zip_path.exists()


def test_process_zip_upload_rejects_too_many_files_and_deletes_original(tmp_path, monkeypatch):
    zip_path = tmp_path / "many.zip"
    destination = tmp_path / "extract"

    create_zip(
        str(zip_path),
        {f"doc_{i}.pdf": b"x" for i in range(3)},
    )

    import zip_utils
    monkeypatch.setattr(zip_utils, "MAX_FILES", 2)

    with pytest.raises(Exception, match="demasiados archivos"):
        process_zip_upload(str(zip_path), str(destination))

    assert not zip_path.exists()


def test_process_zip_upload_rejects_too_large_archive_and_deletes_original(tmp_path, monkeypatch):
    zip_path = tmp_path / "large.zip"
    destination = tmp_path / "extract"

    create_zip(
        str(zip_path),
        {
            "doc.pdf": b"12345",
        },
    )

    import zip_utils
    monkeypatch.setattr(zip_utils, "MAX_TOTAL_SIZE", 4)

    with pytest.raises(Exception, match="límite de seguridad"):
        process_zip_upload(str(zip_path), str(destination))

    assert not zip_path.exists()
