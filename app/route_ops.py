from datetime import datetime, timezone
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename

from app.models import Route


def parse_distance(value: str):
    try:
        distance = float(value)
    except (TypeError, ValueError):
        return None
    if distance < 0:
        return None
    return distance


def next_available_filename(upload_folder: Path, source_name: str) -> str:
    stem = Path(source_name).stem
    suffix = Path(source_name).suffix
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    candidate = f"{stamp}_{source_name}"
    counter = 1
    while (upload_folder / candidate).exists() or Route.query.filter_by(gpx_filename=candidate).first():
        candidate = f"{stamp}_{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def save_gpx_file(file_storage):
    safe_name = secure_filename(file_storage.filename or "")
    if not safe_name or not safe_name.lower().endswith(".gpx"):
        return None, None

    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    save_name = next_available_filename(upload_folder, safe_name)
    save_path = upload_folder / save_name
    file_storage.save(save_path)
    return save_name, save_path


def allowed_file(filename: str, allowed_suffixes: set[str]) -> bool:
    safe_name = secure_filename(filename or "")
    if not safe_name:
        return False
    suffix = Path(safe_name).suffix.lower()
    return suffix in allowed_suffixes


def file_size_ok(file_storage, max_bytes: int) -> bool:
    if max_bytes <= 0:
        return True
    current_pos = file_storage.stream.tell()
    file_storage.stream.seek(0, 2)
    size = file_storage.stream.tell()
    file_storage.stream.seek(current_pos)
    return size <= max_bytes
