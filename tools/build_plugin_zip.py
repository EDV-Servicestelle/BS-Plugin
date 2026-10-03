#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paketiert das Plugin als installierbares ZIP.

Die Version kommt aus dem Git-Tag (z. B. v2.7.8), ersatzweise aus
metadata.txt. Sie wird in metadata.txt des Pakets geschrieben, damit
Dateiname und Plugin-Metadaten nicht auseinanderlaufen.

Aufruf:
    python3 tools/build_plugin_zip.py --plugin qgis_plugin --out dist
    python3 tools/build_plugin_zip.py --plugin qgis_plugin --out dist \
        --ordner qgis_new_project_plugin

Hinweis zum Innenordner: Bisher trug er die Version im Namen
(qgis_new_project_plugin_v277). Im Repository ist das unguenstig, weil der
Name bei jeder Version zu aendern waere. Voreinstellung ist deshalb ein
versionsfreier Ordnername; mit --ordner laesst sich die alte Schreibweise
weiter erzwingen.
"""

import argparse
import os
import re
import subprocess
import sys
import zipfile

AUSGESCHLOSSEN_ORDNER = {"__pycache__", ".git", ".idea", ".vscode"}
AUSGESCHLOSSEN_ENDUNG = (".pyc", ".pyo", ".gpkg-wal", ".gpkg-shm", ".log")


def version_aus_git():
    """Letzter Git-Tag ohne fuehrendes 'v', oder None."""
    try:
        tag = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, timeout=10)
        if tag.returncode == 0 and tag.stdout.strip():
            return tag.stdout.strip().lstrip("vV")
    except Exception:
        pass
    return None


def version_aus_metadata(plugin_dir):
    pfad = os.path.join(plugin_dir, "metadata.txt")
    if not os.path.isfile(pfad):
        return None
    with open(pfad, encoding="utf-8") as fh:
        for zeile in fh:
            if zeile.strip().startswith("version="):
                return zeile.split("=", 1)[1].strip()
    return None


def metadata_mit_version(plugin_dir, version):
    """metadata.txt als Text, mit auf `version` gesetzter Versionszeile."""
    pfad = os.path.join(plugin_dir, "metadata.txt")
    with open(pfad, encoding="utf-8") as fh:
        text = fh.read()
    neu, anzahl = re.subn(r"(?m)^version\s*=.*$", f"version={version}", text)
    if anzahl == 0:
        neu = text.rstrip("\n") + f"\nversion={version}\n"
    return neu


def dateien_sammeln(plugin_dir):
    for wurzel, dirs, dateien in os.walk(plugin_dir):
        dirs[:] = [d for d in dirs if d not in AUSGESCHLOSSEN_ORDNER]
        for d in sorted(dateien):
            if d.endswith(AUSGESCHLOSSEN_ENDUNG):
                continue
            yield os.path.join(wurzel, d)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plugin", required=True)
    ap.add_argument("--out", default="dist")
    ap.add_argument("--ordner", default="qgis_new_project_plugin",
                    help="Name des Ordners IM ZIP (Voreinstellung "
                         "versionsfrei)")
    ap.add_argument("--version", default=None,
                    help="Version erzwingen statt aus Tag/metadata.txt")
    args = ap.parse_args()

    version = (args.version or version_aus_git()
               or version_aus_metadata(args.plugin))
    if not version:
        sys.exit("Keine Version ermittelbar (weder Git-Tag noch metadata.txt).")

    os.makedirs(args.out, exist_ok=True)
    kurz = args.ordner
    ziel = os.path.join(args.out, f"{kurz}_v{version.replace('.', '')}.zip")

    anzahl = 0
    with zipfile.ZipFile(ziel, "w", zipfile.ZIP_DEFLATED) as z:
        for pfad in dateien_sammeln(args.plugin):
            rel = os.path.relpath(pfad, args.plugin)
            im_zip = os.path.join(kurz, rel).replace(os.sep, "/")
            if rel == "metadata.txt":
                z.writestr(im_zip, metadata_mit_version(args.plugin, version))
            else:
                z.write(pfad, im_zip)
            anzahl += 1

    mb = os.path.getsize(ziel) / 1024 / 1024
    print(f"Paket:   {ziel}")
    print(f"Version: {version}   Dateien: {anzahl}   Groesse: {mb:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
