"""
debug_log.py – Zentrales Debug-Logging für NRW Naturschutz-Toolbox
===================================================================
Schreibt in ~/naturschutz_debug.log und ins QGIS-Meldungsprotokoll.
Wird bei jedem Plugin-Start rotiert (max 500 KB).

Verwendung:
    from .debug_log import log, log_exc
    log("Nachricht")
    log("Fehler", level="ERROR", context="WizardBuild")
    try: ...
    except Exception: log_exc("LayerLaden")
"""
import os
import traceback
from datetime import datetime
from pathlib import Path

_LOG_FILE  = Path.home() / "naturschutz_debug.log"
_MAX_BYTES = 500_000


def _write(line: str):
    try:
        if _LOG_FILE.exists() and _LOG_FILE.stat().st_size > _MAX_BYTES:
            _LOG_FILE.rename(_LOG_FILE.with_suffix(".log.bak"))
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def start_session(version: str = ""):
    sep = "=" * 60
    _write(f"\n{sep}")
    _write(f"{datetime.now().isoformat()}  START  v{version}")
    _write(sep)


def log(msg: str, level: str = "INFO", context: str = ""):
    ts  = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    ctx = f"[{context}] " if context else ""
    _write(f"{ts}  {level:<5}  {ctx}{msg}")
    try:
        from qgis.core import QgsMessageLog
        _write_qgis(f"{ctx}{msg}", level)
    except Exception:
        pass


def log_exc(context: str = ""):
    tb  = traceback.format_exc()
    ts  = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    ctx = f"[{context}] " if context else ""
    _write(f"{ts}  ERROR  {ctx}Traceback:")
    for l in tb.splitlines():
        _write(f"          {l}")
    try:
        _write_qgis(f"{ctx}{tb}", "ERROR")
    except Exception:
        pass


def _write_qgis(msg: str, level: str):
    from qgis.core import QgsMessageLog
    lvl = {"INFO": 0, "WARN": 1, "ERROR": 2}.get(level, 0)
    QgsMessageLog.logMessage(msg, "NRW Naturschutz", lvl)


def path() -> str:
    return str(_LOG_FILE)
