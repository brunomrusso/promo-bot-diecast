import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import db

ROOT = Path(__file__).parent
BACKUP_DIR = ROOT / "backups"
RETENTION = 7


@contextmanager
def _lock():
    BACKUP_DIR.mkdir(mode=0o700, exist_ok=True)
    handle = (BACKUP_DIR / ".backup.lock").open("w")
    try:
        try:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            pass
        yield
    finally:
        handle.close()


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy(source, destination):
    if source.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        os.chmod(destination, 0o600)
        return True
    return False


def create_backup():
    started = datetime.utcnow()
    with _lock():
        BACKUP_DIR.mkdir(mode=0o700, exist_ok=True)
        stamp = started.strftime("%Y%m%d-%H%M%S")
        final_path = BACKUP_DIR / f"promo-bot-{stamp}.tar.gz"
        temporary_archive = BACKUP_DIR / f".{final_path.name}.tmp"
        try:
            with tempfile.TemporaryDirectory() as temp:
                stage = Path(temp) / "promo-bot-backup"
                stage.mkdir()
                database = stage / "database" / "deals.db"
                database.parent.mkdir()
                source = sqlite3.connect(db.DB_PATH, timeout=30)
                destination = sqlite3.connect(database)
                try:
                    source.backup(destination)
                finally:
                    destination.close()
                    source.close()
                check = sqlite3.connect(database)
                try:
                    integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
                finally:
                    check.close()
                if integrity != "ok":
                    raise RuntimeError(f"Falha de integridade do SQLite: {integrity}")
                included = ["database/deals.db"]
                for relative in [".env", "keywords.txt", "AGENTS.md"]:
                    if _copy(ROOT / relative, stage / "config" / relative):
                        included.append(f"config/{relative}")
                profile = ROOT / "chrome_profile_ml"
                browser_files = [
                    "Local State", "Default/Cookies", "Default/Cookies-journal",
                    "Default/Network/Cookies", "Default/Network/Cookies-journal",
                    "Default/Preferences",
                    "Default/Secure Preferences",
                ]
                for relative in browser_files:
                    if _copy(profile / relative, stage / "browser" / relative):
                        included.append(f"browser/{relative}")
                manifest = {
                    "created_at": started.isoformat(timespec="seconds") + "Z",
                    "database_integrity": integrity,
                    "files": included,
                    "database_sha256": _hash(database),
                    "version": 1,
                }
                (stage / "manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                with tarfile.open(temporary_archive, "w:gz") as archive:
                    archive.add(stage, arcname="promo-bot-backup")
            temporary_archive.replace(final_path)
            os.chmod(final_path, 0o600)
            archives = sorted(BACKUP_DIR.glob("promo-bot-*.tar.gz"),
                              key=lambda path: path.stat().st_mtime, reverse=True)
            for old in archives[RETENTION:]:
                old.unlink()
            result = {
                "status": "success", "created_at": started.isoformat(timespec="seconds") + "Z",
                "file": final_path.name, "size": final_path.stat().st_size,
                "database_integrity": integrity, "retained": min(len(archives), RETENTION),
            }
        except Exception as exc:
            temporary_archive.unlink(missing_ok=True)
            result = {"status": "error", "created_at": started.isoformat(timespec="seconds") + "Z",
                      "error": str(exc)}
        (BACKUP_DIR / "status.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(BACKUP_DIR / "status.json", 0o600)
        if result["status"] == "error":
            raise RuntimeError(result["error"])
        return result


def backup_status():
    BACKUP_DIR.mkdir(mode=0o700, exist_ok=True)
    status_file = BACKUP_DIR / "status.json"
    status = json.loads(status_file.read_text(encoding="utf-8")) if status_file.exists() else None
    archives = sorted(BACKUP_DIR.glob("promo-bot-*.tar.gz"),
                      key=lambda path: path.stat().st_mtime, reverse=True)
    return {"last": status, "count": len(archives),
            "total_size": sum(path.stat().st_size for path in archives),
            "retention": RETENTION}


if __name__ == "__main__":
    print(json.dumps(create_backup(), ensure_ascii=False))
