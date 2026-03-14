import logging
import os
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_FILES = 1000
MAX_TOTAL_SIZE = 500 * 1024 * 1024


def safe_extract(zip_ref: zipfile.ZipFile, extract_path: str):
    base_path = Path(extract_path).resolve()

    for member in zip_ref.infolist():
        target_path = (base_path / member.filename).resolve()

        if not str(target_path).startswith(str(base_path)):
            raise Exception(f"Intento de Path Traversal detectado: {member.filename}")

        if member.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)

        with zip_ref.open(member) as source, open(target_path, "wb") as target:
            target.write(source.read())


def validate_zip_limits(zip_path: str):
    total_size = 0

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        file_list = zip_ref.infolist()

        if len(file_list) > MAX_FILES:
            raise Exception("ZIP contiene demasiados archivos (Límite: 1000)")

        for file_info in file_list:
            if file_info.is_dir():
                continue

            total_size += file_info.file_size

            if total_size > MAX_TOTAL_SIZE:
                raise Exception(
                    "El contenido del ZIP excede el límite de seguridad (500MB)"
                )

    return True


def process_zip_upload(zip_path: str, destination_folder: str):
    extracted_files = []

    try:
        validate_zip_limits(zip_path)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            safe_extract(zip_ref, destination_folder)

        for root, _, files in os.walk(destination_folder):
            for name in files:
                extracted_files.append(str(Path(root) / name))

        return extracted_files

    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)
            logger.info("Limpieza exitosa: %s eliminado.", zip_path)
