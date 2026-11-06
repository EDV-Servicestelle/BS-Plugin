#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Erzeugt aus einem fertigen Plugin-ZIP das Plugin-Repository fuer QGIS.

QGIS braucht fuer ein eigenes Repository nur eine statische plugins.xml und
die ZIP-Datei. Die Angaben fuer plugins.xml werden aus der metadata.txt
IM ZIP gelesen - also aus genau dem Paket, das ausgeliefert wird. Damit
koennen Version im Repository und installierte Version nicht auseinander-
laufen (sonst meldet QGIS dauerhaft ein Update oder nie eines).

Aufruf:
    python3 tools/build_plugins_xml.py --zip dist/paket.zip \
        --out site --base-url https://edv-servicestelle.github.io/BS-Plugin

Ergebnis in --out:
    plugins.xml     die Adresse, die die Stationen in QGIS eintragen
    <paket>.zip     Kopie des Pakets (download_url zeigt hierhin)
    index.html      kurze Anleitung fuer alle, die die Adresse im Browser oeffnen
"""

import argparse
import configparser
import datetime
import html
import os
import shutil
import sys
import zipfile
from xml.sax.saxutils import escape, quoteattr


def metadata_aus_zip(zip_pfad):
    """(Ordnername im ZIP, Abschnitt [general] der metadata.txt)."""
    with zipfile.ZipFile(zip_pfad) as z:
        kandidaten = [n for n in z.namelist()
                      if n.count("/") == 1 and n.endswith("/metadata.txt")]
        if len(kandidaten) != 1:
            sys.exit(f"Erwartet genau eine <ordner>/metadata.txt im ZIP, "
                     f"gefunden: {kandidaten}")
        ordner = kandidaten[0].split("/")[0]
        text = z.read(kandidaten[0]).decode("utf-8")
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str  # Schluessel wie qgisMinimumVersion nicht kleinschreiben
    cp.read_string(text)
    return ordner, cp["general"]


def wahr(wert):
    return "True" if str(wert).strip().lower() in ("true", "1", "yes") \
        else "False"


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", required=True, help="fertiges Plugin-ZIP")
    ap.add_argument("--out", default="site")
    ap.add_argument("--base-url", required=True,
                    help="oeffentliche Adresse des Ausgabeordners")
    args = ap.parse_args()

    ordner, md = metadata_aus_zip(args.zip)
    for pflicht in ("name", "version", "qgisMinimumVersion", "description"):
        if not md.get(pflicht):
            sys.exit(f"metadata.txt im ZIP ohne '{pflicht}'")

    os.makedirs(args.out, exist_ok=True)
    version = md["version"].strip()
    # QGIS leitet die Plugin-ID aus dem Dateinamen ab (alles vor dem ersten
    # Punkt) und erwartet einen gleichnamigen Ordner im ZIP. Deshalb heisst
    # die Datei im Repository <ordner>.<version>.zip - wie im offiziellen
    # QGIS-Repository -, unabhaengig vom Namen der Release-Datei.
    datei = f"{ordner}.{version}.zip"
    shutil.copy2(args.zip, os.path.join(args.out, datei))

    base = args.base_url.rstrip("/")
    jetzt = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")

    felder = [
        ("description", md.get("description", "")),
        ("about", md.get("about", "")),
        ("version", version),
        ("qgis_minimum_version", md.get("qgisMinimumVersion", "")),
        ("qgis_maximum_version", md.get("qgisMaximumVersion", "3.99")),
        ("supports_qt6", wahr(md.get("supportsQt6", "False"))),
        ("homepage", md.get("homepage", "")),
        ("file_name", datei),
        ("author_name", md.get("author", "")),
        ("download_url", f"{base}/{datei}"),
        ("uploaded_by", md.get("author", "")),
        ("create_date", jetzt),
        ("update_date", jetzt),
        ("experimental", wahr(md.get("experimental", "False"))),
        ("deprecated", wahr(md.get("deprecated", "False"))),
        ("tracker", md.get("tracker", "")),
        ("repository", md.get("repository", "")),
        ("tags", md.get("tags", "")),
        ("server", "False"),
    ]
    zeilen = ['<?xml version="1.0" encoding="UTF-8"?>', "<plugins>",
              f"  <pyqgis_plugin name={quoteattr(md['name'])} "
              f"version={quoteattr(version)} plugin_id={quoteattr(ordner)}>"]
    for tag, wert in felder:
        zeilen.append(f"    <{tag}>{escape(str(wert).strip())}</{tag}>")
    zeilen += ["  </pyqgis_plugin>", "</plugins>", ""]
    with open(os.path.join(args.out, "plugins.xml"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(zeilen))

    name = html.escape(md["name"])
    with open(os.path.join(args.out, "index.html"), "w",
              encoding="utf-8") as fh:
        fh.write(f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<title>{name} – Plugin-Repository</title>
<style>body{{font-family:sans-serif;max-width:46em;margin:3em auto;
line-height:1.5;padding:0 1em}}code{{background:#eee;padding:.1em .3em}}</style>
</head><body>
<h1>{name} – Plugin-Repository für QGIS</h1>
<p>Aktuelle Version: <strong>{html.escape(version)}</strong></p>
<p>Diese Adresse ist für QGIS gedacht, nicht für den Browser. Tragen Sie sie
einmal in QGIS ein, danach meldet QGIS neue Versionen selbst:</p>
<p><code>{html.escape(base)}/plugins.xml</code></p>
<ol>
<li>QGIS: <em>Erweiterungen → Erweiterungen verwalten und installieren
→ Einstellungen</em></li>
<li><em>Hinzufügen …</em>, Name <code>BioSt-GIS</code>, URL wie oben, OK</li>
<li>Unter <em>Alle</em> nach „{name}“ suchen und installieren</li>
</ol>
<p>Direkter Download: <a href="{html.escape(datei)}">{html.escape(datei)}</a></p>
</body></html>
""")

    print(f"Repository erzeugt in {args.out}: {md['name']} {version} "
          f"(plugin_id {ordner})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
