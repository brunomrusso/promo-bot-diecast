import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import backup
import db

ROOT = Path(__file__).parent


def _bytes(value):
    size = float(value)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024


def _memory():
    path = Path("/proc/meminfo")
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text().splitlines():
        key, raw = line.split(":", 1)
        values[key] = int(raw.strip().split()[0]) * 1024
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    swap_total = values.get("SwapTotal", 0)
    swap_free = values.get("SwapFree", 0)
    return {
        "total": _bytes(total), "used": _bytes(total - available),
        "percent": round((total - available) / total * 100) if total else 0,
        "swap_total": _bytes(swap_total), "swap_used": _bytes(swap_total - swap_free),
        "swap_percent": round((swap_total - swap_free) / swap_total * 100)
        if swap_total else 0,
    }


def _services():
    result = {}
    for name in ["promobot", "dashboard", "dashboard-tunnel"]:
        try:
            check = subprocess.run(
                ["systemctl", "is-active", name], capture_output=True,
                text=True, timeout=3, check=False)
            result[name] = check.stdout.strip() or "unknown"
        except (OSError, subprocess.SubprocessError):
            result[name] = "unknown"
    return result


def bot_indicator():
    heartbeat = db.get_system_state().get("heartbeat")
    age = None
    if heartbeat:
        try:
            age = (datetime.utcnow() - datetime.fromisoformat(
                heartbeat["updated_at"])).total_seconds()
        except ValueError:
            pass
    return {"online": age is not None and age < 180,
            "age": round(age) if age is not None else None,
            "phase": heartbeat["value"].get("phase") if heartbeat else None}


def snapshot():
    states = db.get_system_state()
    heartbeat = states.get("heartbeat")
    indicator = bot_indicator()
    age = indicator["age"]
    bot_online = indicator["online"]
    disk = shutil.disk_usage(ROOT)
    db_size = sum(path.stat().st_size for path in [
        db.DB_PATH, Path(str(db.DB_PATH) + "-wal"), Path(str(db.DB_PATH) + "-shm")]
                  if path.exists())
    profile = ROOT / "chrome_profile_ml" / "Default" / "Cookies"
    uptime = None
    if Path("/proc/uptime").exists():
        uptime = float(Path("/proc/uptime").read_text().split()[0])
    try:
        load = [round(value, 2) for value in os.getloadavg()]
    except (AttributeError, OSError):
        load = []
    backup_info = backup.backup_status()
    backup_info["total_size_display"] = _bytes(backup_info["total_size"])
    if backup_info["last"] and backup_info["last"].get("size"):
        backup_info["last"]["size_display"] = _bytes(backup_info["last"]["size"])
    return {
        "bot_online": bot_online, "heartbeat_age": round(age) if age is not None else None,
        "heartbeat": heartbeat, "cycle": states.get("cycle"),
        "stores": db.list_store_health(), "memory": _memory(),
        "disk": {"total": _bytes(disk.total), "used": _bytes(disk.used),
                 "free": _bytes(disk.free), "percent": round(disk.used / disk.total * 100)},
        "database_size": _bytes(db_size), "services": _services(),
        "uptime_hours": round(uptime / 3600, 1) if uptime is not None else None,
        "load": load, "backup": backup_info, "audit": db.job_audit(), "ml_profile": {
            "exists": profile.exists(),
            "updated_at": datetime.fromtimestamp(profile.stat().st_mtime).isoformat(
                sep=" ", timespec="seconds") if profile.exists() else None,
            "session": states.get("ml_session", {}).get("value", {"status": "unknown"}),
        },
    }
