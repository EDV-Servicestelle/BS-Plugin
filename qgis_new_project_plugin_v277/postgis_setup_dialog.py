"""
postgis_setup_dialog.py – PostGIS-Datenbank aus lokalen Quellen anlegen
=======================================================================
Überträgt alle lokalen GPKGs, Referenzlisten und Styles in eine
PostgreSQL/PostGIS-Datenbank und legt die public.fachschalen_config-Tabelle
an, die der FachschalenLoader und der Fachschalen-Wizard verwenden.
"""

import os, sqlite3, subprocess, shutil
from pathlib import Path

# Alten .pyc-Cache löschen damit Änderungen sofort wirken
try:
    _self_dir = Path(__file__).parent
    for _d in _self_dir.rglob("__pycache__"):
        shutil.rmtree(_d, ignore_errors=True)
except Exception:
    pass

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QPushButton, QLineEdit, QSpinBox, QTextEdit,
    QProgressBar, QCheckBox, QTreeWidget, QTreeWidgetItem,
    QTabWidget, QWidget,
)
from qgis.PyQt.QtCore import QThread, pyqtSignal
from qgis.PyQt.QtGui import QFont

PLUGIN_DIR = Path(__file__).parent
DATA_DIR   = PLUGIN_DIR / "data"


# ── Fachschalen-Mapping ─────────────────────────────────────────────────────
# schema_name und ref_schema exakt wie in fachschalen_config.py
# damit FachschalenLoader + Wizard direkt darauf zugreifen.
FACHSCHALEN = {
    "brutvogel": {
        "label":       "Brutvogel-Kartierung",
        "code":        "brutvogel",
        "bezeichnung": "Brutvogel-Kartierung",
        "schema":      "brutvogel",
        "ref_schema":  "referenz",
        "gpkgs": [
            DATA_DIR / "brutvogel" / "QFS_bv.gpkg",
            DATA_DIR / "brutvogel" / "Untersuchungsgebiet.gpkg",
        ],
    },
    "biotopbaum": {
        "label":       "Biotopbäume",
        "code":        "biotopbaum",
        "bezeichnung": "Biotopbaum",
        "schema":      "biotopbaum",
        "ref_schema":  "referenz_bt",
        "gpkgs": [
            DATA_DIR / "biotopbaum" / "Erfassung.gpkg",
            # Grenzen1.gpkg entfällt: FFH+Kreise kommen aus Grundlagendaten
            DATA_DIR / "biotopbaum" / "Referenzlisten.gpkg",
        ],
    },
    "fundpunkte_tiere": {
        "label":       "Fundpunkte Tiere",
        "code":        "fundpunkte_tiere",
        "bezeichnung": "Fundpunkte Tiere",
        "schema":      "fundpunkte_tiere",
        "ref_schema":  "referenz",
        "gpkgs": [
            DATA_DIR / "fundpunkte_tiere" / "Fundpunkte.gpkg",
            DATA_DIR / "fundpunkte_tiere" / "Referenzen.gpkg",
        ],
    },
    "grundlagen": {
        "label":       "Grundlagendaten / ATKIS",
        "code":        "grundlagen",
        "bezeichnung": "Grundlagendaten",
        "schema":      "grundlagen",
        "ref_schema":  "grundlagen",
        "gpkgs": [
            DATA_DIR / "Nutzung.gpkg",
            DATA_DIR / "untersuchungsgebiet.gpkg",
        ],
    },
}


# ── Worker ──────────────────────────────────────────────────────────────────
class _SetupWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, cfg: dict):
        super().__init__()
        self._cfg = cfg

    def run(self):
        try:
            self._setup()
        except Exception as e:
            self.finished.emit(False, str(e))

    def _setup(self):
        cfg  = self._cfg
        host = cfg["host"]; port = cfg["port"]
        db   = cfg["db"];   user = cfg["user"]; pw = cfg["password"]
        srid = cfg.get("srid", 25832)
        create_db = cfg.get("create_db", True)
        schemas   = cfg.get("schemas", list(FACHSCHALEN.keys()))

        pgstr_adm = f"postgresql://{user}:{pw}@{host}:{port}/postgres"
        pgstr_db  = f"postgresql://{user}:{pw}@{host}:{port}/{db}"

        try:
            import psycopg2 as _pg
        except ImportError:
            _pg = None

        # 1. Datenbank anlegen
        if create_db:
            self.progress.emit(2, f"Lege Datenbank '{db}' an …")
            self._sql("postgres", f'CREATE DATABASE "{db}" ENCODING \'UTF8\'',
                      _pg, host, port, user, pw)

        # 2. Extensions
        self.progress.emit(5, "Aktiviere PostGIS …")
        for ext in ("postgis", "postgis_topology", "fuzzystrmatch"):
            self._sql(db, f"CREATE EXTENSION IF NOT EXISTS {ext}",
                      _pg, host, port, user, pw)

        # 3. Fachschalen-Schemas + Ref-Schemas + gemeinsam
        self.progress.emit(8, "Lege Schemas an …")
        all_schemas = {"gemeinsam"}  # immer anlegen
        for key in schemas:
            fs = FACHSCHALEN[key]
            all_schemas.add(fs["schema"])
            all_schemas.add(fs["ref_schema"])
        for sch in sorted(all_schemas):
            self._sql(db, f'CREATE SCHEMA IF NOT EXISTS "{sch}"',
                      _pg, host, port, user, pw)
            self.progress.emit(-1, f"  Schema: {sch}")

        # 4. public.fachschalen_config (Grundlage für FachschalenLoader)
        self.progress.emit(12, "Lege public.fachschalen_config an …")
        self._sql(db, """
            CREATE TABLE IF NOT EXISTS public.fachschalen_config (
                id          SERIAL PRIMARY KEY,
                code        TEXT UNIQUE NOT NULL,
                bezeichnung TEXT NOT NULL,
                schema_name TEXT NOT NULL,
                ref_schema  TEXT NOT NULL,
                aktiv       BOOLEAN DEFAULT TRUE,
                created_at  TIMESTAMP DEFAULT now()
            )""", _pg, host, port, user, pw)

        for key in schemas:
            fs = FACHSCHALEN[key]
            self._sql(db, f"""
                INSERT INTO public.fachschalen_config
                    (code, bezeichnung, schema_name, ref_schema, aktiv)
                    VALUES ('{fs["code"]}','{fs["bezeichnung"]}',
                            '{fs["schema"]}','{fs["ref_schema"]}',TRUE)
                    ON CONFLICT (code) DO UPDATE SET
                        bezeichnung = EXCLUDED.bezeichnung,
                        schema_name = EXCLUDED.schema_name,
                        ref_schema  = EXCLUDED.ref_schema,
                        aktiv       = TRUE
            """, _pg, host, port, user, pw)
            self.progress.emit(-1,
                f"  ✓ {fs['bezeichnung']} → schema={fs['schema']}, ref={fs['ref_schema']}")

        # 5a. Gemeinsame Tabellen anlegen
        self.progress.emit(13, "Lege gemeinsame Tabellen an …")
        self._sql(db, """
            CREATE TABLE IF NOT EXISTS gemeinsam.institution (
                gid        SERIAL PRIMARY KEY,
                kuerzel    TEXT UNIQUE NOT NULL,
                name       TEXT,
                parentid   INTEGER,
                listitemid INTEGER,
                entityid   INTEGER
            )""", _pg, host, port, user, pw)
        self._sql(db, """
            CREATE TABLE IF NOT EXISTS gemeinsam.karterer (
                gid            SERIAL PRIMARY KEY,
                uuid           TEXT UNIQUE,
                vorname        TEXT,
                nachname       TEXT,
                email          TEXT,
                telefon        TEXT,
                institution_kuerzel TEXT REFERENCES gemeinsam.institution(kuerzel),
                aktiv          BOOLEAN DEFAULT TRUE
            )""", _pg, host, port, user, pw)
        self._sql(db, """
            CREATE TABLE IF NOT EXISTS gemeinsam.untersuchungsgebiet (
                gid         SERIAL PRIMARY KEY,
                geom        geometry(MultiPolygon,25832),
                kennung     TEXT,
                bezeichnung TEXT,
                fachschale  TEXT,
                created_at  TIMESTAMP DEFAULT now()
            )""", _pg, host, port, user, pw)
        self._sql(db,
            "CREATE INDEX IF NOT EXISTS idx_ug_geom "
            "ON gemeinsam.untersuchungsgebiet USING GIST(geom)",
            _pg, host, port, user, pw)
        self._sql(db,
            "ALTER TABLE public.fachschalen_config "
            "ADD COLUMN IF NOT EXISTS gemeinsam_schema TEXT DEFAULT 'gemeinsam'",
            _pg, host, port, user, pw)
        self.progress.emit(-1,
            "  ✓ gemeinsam: institution, karterer, untersuchungsgebiet")

        # 5b. public.layer_styles (QGIS-Standard)
        self._sql(db, """
            CREATE TABLE IF NOT EXISTS public.layer_styles (
                id                SERIAL PRIMARY KEY,
                f_table_catalog   TEXT,
                f_table_schema    TEXT,
                f_table_name      TEXT,
                f_geometry_column TEXT,
                styleName         TEXT,
                styleQML          TEXT,
                styleSLD          TEXT,
                useAsDefault      BOOLEAN,
                description       TEXT,
                owner             TEXT,
                ui                TEXT,
                update_time       TIMESTAMP DEFAULT now()
            )""", _pg, host, port, user, pw)

        # 6. GPKGs übertragen
        total = sum(len(FACHSCHALEN[k]["gpkgs"]) for k in schemas)
        done  = 0
        for key in schemas:
            fs = FACHSCHALEN[key]
            for gpkg_path in fs["gpkgs"]:
                if not gpkg_path.exists():
                    self.progress.emit(-1, f"  ⚠ {gpkg_path.name} nicht gefunden")
                    done += 1; continue
                pct = 15 + int(70 * done / max(total, 1))
                self.progress.emit(pct, f"► {gpkg_path.name} → {fs['schema']} …")
                self._transfer_gpkg(gpkg_path, fs, db, host, port, user, pw, srid, _pg)
                done += 1

        # 6b. Tabellen-Case reparieren (CamelCase → lowercase)
        self._repair_table_case(db, _pg, host, port, user, pw)

        # 7. Styles migrieren
        self.progress.emit(90, "Migriere QGIS-Styles …")
        self._migrate_styles(schemas, db, _pg, host, port, user, pw)

        self.progress.emit(100, "✓ Fertig")
        self.finished.emit(True,
            f"Datenbank '{db}' bereit.\n\n"
            f"public.fachschalen_config enthält {len(schemas)} Fachschalen.\n"
            f"Der Fachschalen-Wizard liest diese Tabelle automatisch.\n\n"
            f"Verbindung in QGIS:\n"
            f"  Host: {host}  Port: {port}  DB: {db}  User: {user}")

    # ── GPKG → PostGIS ───────────────────────────────────────────────────────

    def _transfer_gpkg(self, gpkg_path: Path, fs: dict,
                       db, host, port, user, pw, srid: int, _pg=None):
        pg_uri = f"PG:host={host} port={port} dbname={db} user={user} password={pw}"
        # Gemeinsame Tabellen → gemeinsam-Schema
        GEMEINSAM_MAP = {
            "referenzliste_mitarbeiter": "gemeinsam.karterer",
            "untersuchungsgebiet":       "gemeinsam.untersuchungsgebiet",
            "institution":               "gemeinsam.institution",
            "adressrollle":              "gemeinsam.institution",
        }
        schema    = fs["schema"]
        ref_sch   = fs["ref_schema"]

        con = sqlite3.connect(str(gpkg_path))
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'gpkg%' AND name NOT LIKE 'rtree%' "
            "AND name NOT LIKE 'sqlite%'"
        ).fetchall()]
        geom_tables = {r[0] for r in con.execute(
            "SELECT table_name FROM gpkg_geometry_columns"
        ).fetchall()}
        con.close()

        for tbl in tables:
            if tbl == "layer_styles":
                continue
            # Referenzlisten → ref_schema, Geodaten → schema
            is_ref = (
                "referenz" in gpkg_path.stem.lower()
                or tbl.lower().startswith("referenzliste")
                or tbl.lower() in ("arten", "artengruppen", "geschlecht",
                                   "stadium", "status", "einheit",
                                   "institution", "bewertung_erhaltungszustand")
            )
            tgt = ref_sch if is_ref else schema

            if tbl in geom_tables:
                cmd = [
                    self._ogr2ogr(), "-overwrite",
                    "-f", "PostgreSQL", pg_uri,
                    str(gpkg_path), tbl,
                    "-nln", f"{tgt}.{tbl.lower()}",
                    "-lco", f"SCHEMA={tgt}",
                    "-lco", "GEOMETRY_NAME=geom",
                    "-lco", f"SRID={srid}",
                    "-lco", "FID=gid",
                    "-lco", "OVERWRITE=YES",
                    "-nlt", "PROMOTE_TO_MULTI",
                    "-t_srs", f"EPSG:{srid}",
                ]
            else:
                cmd = [
                    self._ogr2ogr(), "-overwrite",
                    "-f", "PostgreSQL", pg_uri,
                    str(gpkg_path), tbl,
                    "-nln", f"{tgt}.{tbl.lower()}",
                    "-lco", f"SCHEMA={tgt}",
                    "-lco", "OVERWRITE=YES",
                ]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                icon = "✓" if r.returncode == 0 else "⚠"
                suffix = "" if r.returncode == 0 else f": {r.stderr[:80]}"
                self.progress.emit(-1, f"    {icon} {tgt}.{tbl}{suffix}")
                # Spalten von lowercase → Original-GPKG-Namen umbenennen
                if r.returncode == 0:
                    self._rename_cols_to_original(
                        str(gpkg_path), tbl, tgt, db, _pg, host, port, user, pw)
            except Exception as e:
                self.progress.emit(-1, f"    ✗ {tbl}: {e}")

    # ── Styles migrieren ─────────────────────────────────────────────────────

    def _rename_cols_to_original(self, gpkg_path: str, tbl: str, schema: str,
                                    db, _pg, host, port, user, pw):
        """Benennt Spalten nach dem ogr2ogr-Import zurück auf Original-Groß/Kleinschreibung.
        Nur Spalten die sich wirklich nur in der Gross/Kleinschreibung unterscheiden
        (keine Sonderzeichen wie Bindestriche die ogr2ogr anders behandelt).
        """
        if not _pg:
            return
        try:
            import sqlite3 as _sq3
            con = _sq3.connect(gpkg_path)
            orig_cols = [c[1] for c in con.execute(
                f"PRAGMA table_info(\"{tbl}\")"
            ).fetchall()]
            con.close()
            if not orig_cols:
                return

            # Hole tatsächliche Spaltennamen aus PostgreSQL
            conn = _pg.connect(host=host, port=port, dbname=db,
                               user=user, password=pw)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
            """, (schema, tbl.lower()))
            db_cols = {r[0].lower(): r[0] for r in cur.fetchall()}

            for orig in orig_cols:
                lower = orig.lower()
                if orig == lower:
                    continue   # schon lowercase
                if lower not in db_cols:
                    continue   # Spalte in DB nicht vorhanden (Sonderzeichen etc.)
                if db_cols[lower] == orig:
                    continue   # schon korrekt benannt
                try:
                    cur.execute(
                        f'ALTER TABLE "{schema}"."{tbl.lower()}" ' +
                        f'RENAME COLUMN "{lower}" TO "{orig}"'
                    )
                except Exception:
                    pass   # unkritisch – Spalte hat Sonderzeichen o.ä.
            conn.close()
        except Exception:
            pass   # Import war bereits erfolgreich, Umbenennung ist optional

    def _repair_table_case(self, db, pg, host, port, user, pw):
        """Benennt CamelCase-Tabellen in lowercase um (einmalige Reparatur)."""
        self.progress.emit(-1, "  Prüfe Tabellen-Gross/Kleinschreibung …")
        # Suche Tabellen mit Großbuchstaben in relevanten Schemas
        find_sql = """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema IN ('referenz','referenz_bt','fundpunkte_tiere',
                                   'biotopbaum','brutvogel','grundlagen','gemeinsam')
              AND table_name != LOWER(table_name)
              AND table_type = 'BASE TABLE'
        """
        try:
            if pg:
                conn = pg.connect(host=host, port=port, dbname=db,
                                  user=user, password=pw)
                conn.autocommit = True
                cur = conn.cursor()
                cur.execute(find_sql)
                rows = cur.fetchall()
                for schema, tbl in rows:
                    cur.execute(f'ALTER TABLE "{schema}"."{tbl}" '
                                f'RENAME TO "{tbl.lower()}"')
                    self.progress.emit(-1, f"  ↓ {schema}.{tbl} → {tbl.lower()}")
                conn.close()
        except Exception as e:
            self.progress.emit(-1, f"  Repair: {e}")

    def _migrate_styles(self, schemas, db, pg, host, port, user, pw):
        """
        Migriert Styles in public.layer_styles.
        Priorität: 1. QML-Dateien aus Plugin-Verzeichnis (data/<fachschale>/*.qml)
                   2. layer_styles aus GPKG
        Ersetzt GPKG-Pfade in ValueRelations durch leere Source →
        QGIS findet Layer per LayerName im geladenen Projekt.
        """
        import re as _re

        def _clean_qml(qml_str):
            """Leert LayerSource + lowercase Feldnamen.
            Aliasse sorgen fuer lesbare Formularbeschriftungen.
            """
            # LayerSource leeren
            qml_str = _re.sub(
                r'(<Option\s+value=")[^"]*("(?:\s+name="LayerSource"\s+type="[^"]+")/>)',
                r'\1\2',
                qml_str
            )
            # Feldnamen lowercase (PostGIS speichert ohne Quotes lowercase)
            for pat in ('field="', '<field name="'):
                parts = qml_str.split(pat)
                out = [parts[0]]
                for part in parts[1:]:
                    q = part.find('"')   # Ende des Feldnamens
                    if q > 0:
                        out.append(part[:q].lower() + part[q:])
                    else:
                        out.append(part)
                qml_str = pat.join(out)
            # Leere Aliasse mit originalem Feldnamen fuellen
            def _fill(m):
                if m.group(1) == "":
                    return m.group(0).replace('name=""', 'name="' + m.group(2).replace("_"," ").title() + '"')
                return m.group(0)
            qml_str = _re.sub(
                r'alias name="([^"]*)" index="\d+" field="([^"]+)"',
                _fill, qml_str)
            return qml_str


        for key in schemas:
            fs = FACHSCHALEN[key]
            schema = fs["schema"]

            def esc(s): return (s or "").replace("'", "''")

            # 1. QML-Dateien aus data/<key>/*.qml (höchste Priorität)
            qml_dir = PLUGIN_DIR / "data" / key.replace("fundpunkte_tiere", "fundpunkte_tiere")
            if not qml_dir.exists():
                qml_dir = PLUGIN_DIR / "data" / key.split("_")[0]
            # FT3.qml ist Vorlage - nur fund.qml und andere <tabelle>.qml laden
            qml_files = [f for f in (sorted(qml_dir.glob("*.qml"))
                          if qml_dir.exists() else [])
                         if not f.stem.upper().startswith("FT") or
                            f.stem.lower() in ("fund",)]
            for qml_file in qml_files:
                try:
                    qml_str = _clean_qml(qml_file.read_text(encoding="utf-8"))
                    tbl     = qml_file.stem.lower()
                    self._sql(db,
                        f"DELETE FROM public.layer_styles "
                        f"WHERE LOWER(f_table_schema)=LOWER('{schema}') "
                        f"AND LOWER(f_table_name)='{tbl}'",
                        pg, host, port, user, pw)
                    self._sql(db,
                        f"INSERT INTO public.layer_styles "
                        f"(f_table_schema,f_table_name,styleName,styleQML,useAsDefault) "
                        f"VALUES ('{schema}','{tbl}',"
                        f"'{esc(qml_file.stem)}','{esc(qml_str)}',TRUE)",
                        pg, host, port, user, pw)
                    self.progress.emit(-1, f"  ✓ QML {schema}.{tbl} ← {qml_file.name}")
                except Exception as _e:
                    self.progress.emit(-1, f"  ⚠ {qml_file.name}: {_e}")

            # 2. Styles aus GPKG layer_styles (Fallback für nicht-überschriebene Tabellen)
            for gpkg_path in fs["gpkgs"]:
                if not gpkg_path.exists(): continue
                con = sqlite3.connect(str(gpkg_path))
                try:
                    # Prüfe ob layer_styles Tabelle existiert
                    has_styles = con.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='layer_styles'"
                    ).fetchone()
                    rows = con.execute(
                        "SELECT f_table_name, styleName, styleQML, styleSLD, "
                        "useAsDefault, description, owner FROM layer_styles"
                    ).fetchall() if has_styles else []
                except: rows = []
                con.close()
                n = 0
                for r in rows:
                    tbl = (r[0] or "").lower()
                    qml = _clean_qml(r[2] or "")
                    # Nur wenn noch kein Style vorhanden
                    self._sql(db,
                        f"INSERT INTO public.layer_styles "
                        f"(f_table_schema,f_table_name,styleName,styleQML,"
                        f"styleSLD,useAsDefault,description,owner) "
                        f"SELECT '{schema}','{tbl}','{esc(r[1])}','{esc(qml)}',"
                        f"'{esc(r[3])}',{'true' if r[4] else 'false'},"
                        f"'{esc(r[5] or '')}','{esc(r[6] or '')}' "
                        f"WHERE NOT EXISTS ("
                        f"SELECT 1 FROM public.layer_styles "
                        f"WHERE LOWER(f_table_schema)=LOWER('{schema}') "
                        f"AND LOWER(f_table_name)='{tbl}')",
                        pg, host, port, user, pw)
                    n += 1
                if n:
                    self.progress.emit(-1, f"  ✓ {n} Styles (GPKG) ← {gpkg_path.name}")



    def _sql(self, dbname, sql, pg, host, port, user, pw):
        if pg:
            try:
                con = pg.connect(host=host, port=port, dbname=dbname,
                                 user=user, password=pw)
                con.autocommit = True
                con.cursor().execute(sql)
                con.close()
            except Exception as e:
                if "already exists" not in str(e).lower():
                    self.progress.emit(-1, f"  SQL: {str(e)[:100]}")
        else:
            env = os.environ.copy(); env["PGPASSWORD"] = pw
            subprocess.run([self._psql(), "-h", host, "-p", str(port),
                            "-U", user, "-d", dbname, "-c", sql],
                           env=env, capture_output=True, timeout=30)

    @staticmethod
    def _ogr2ogr():
        for c in [r"C:\OSGeo4W\bin\ogr2ogr.exe",
                  r"C:\Program Files\QGIS 3.44\bin\ogr2ogr.exe", "ogr2ogr"]:
            if os.path.exists(c) or c == "ogr2ogr": return c
        return "ogr2ogr"

    @staticmethod
    def _psql():
        for c in [r"C:\OSGeo4W\bin\psql.exe",
                  r"C:\Program Files\PostgreSQL\16\bin\psql.exe", "psql"]:
            if os.path.exists(c) or c == "psql": return c
        return "psql"


# ── Dialog ───────────────────────────────────────────────────────────────────
class PostgisSetupDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PostGIS-Datenbank einrichten")
        self.setMinimumSize(720, 620)
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        tabs = QTabWidget()
        lo.addWidget(tabs)

        # ── Tab 1: Verbindung ────────────────────────────────────────────────
        cw = QWidget(); cl = QVBoxLayout(cw)
        grp = QGroupBox("PostgreSQL-Verbindung")
        fl  = QFormLayout(grp)
        self.host_edit = QLineEdit("localhost")
        self.port_spin = QSpinBox(); self.port_spin.setRange(1,65535); self.port_spin.setValue(5432)
        self.db_edit   = QLineEdit("naturschutz")
        self.user_edit = QLineEdit("postgres")
        self.pw_edit   = QLineEdit(); self.pw_edit.setEchoMode(QLineEdit.Password)
        self.srid_spin = QSpinBox(); self.srid_spin.setRange(1,999999); self.srid_spin.setValue(25832)
        self.create_cb = QCheckBox("Neue Datenbank anlegen (CREATE DATABASE)")
        self.create_cb.setChecked(True)
        fl.addRow("Host:",      self.host_edit)
        fl.addRow("Port:",      self.port_spin)
        fl.addRow("Datenbank:", self.db_edit)
        fl.addRow("Benutzer:",  self.user_edit)
        fl.addRow("Passwort:",  self.pw_edit)
        fl.addRow("SRID:",      self.srid_spin)
        fl.addRow("",           self.create_cb)
        cl.addWidget(grp)
        info = QLabel(
            "ℹ  Der Setup legt <b>public.fachschalen_config</b> an.\n"
            "Der Fachschalen-Wizard liest diese Tabelle automatisch\n"
            "und zeigt die verfügbaren Fachschalen zur Auswahl.")
        info.setWordWrap(True)
        info.setStyleSheet("color: gray; font-size: 11px; padding: 8px 0;")
        cl.addWidget(info)
        test_btn = QPushButton("Verbindung testen")
        test_btn.clicked.connect(self._test)
        cl.addWidget(test_btn)
        cl.addStretch()
        tabs.addTab(cw, "Verbindung")

        # ── Tab 2: Fachschalen ───────────────────────────────────────────────
        sw = QWidget(); sl = QVBoxLayout(sw)
        sl.addWidget(QLabel("Fachschalen auswählen (werden in PostGIS registriert):"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Fachschale", "schema / ref_schema", "GPKGs"])
        self.tree.setColumnWidth(0, 200); self.tree.setColumnWidth(1, 180)
        self._cbs = {}
        for key, fs in FACHSCHALEN.items():
            item = QTreeWidgetItem(self.tree)
            item.setText(0, fs["label"])
            item.setText(1, f"{fs['schema']} / {fs['ref_schema']}")
            cb = QCheckBox(); cb.setChecked(True)
            self.tree.setItemWidget(item, 0, cb)
            self._cbs[key] = cb
            for gpkg in fs["gpkgs"]:
                ch = QTreeWidgetItem(item)
                ok = gpkg.exists()
                ch.setText(0, f"  {'✓' if ok else '✗'} {gpkg.name}")
                if ok:
                    con = sqlite3.connect(str(gpkg))
                    tbls = [r[0] for r in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name NOT LIKE 'gpkg%' AND name NOT LIKE 'sqlite%'"
                    ).fetchall()]
                    con.close()
                    ch.setText(2, ", ".join(tbls[:5]) + ("…" if len(tbls)>5 else ""))
            item.setExpanded(True)
        sl.addWidget(self.tree)
        tabs.addTab(sw, "Fachschalen")

        # ── Fortschritt + Log ────────────────────────────────────────────────
        self.bar = QProgressBar(); self.bar.setRange(0,100); self.bar.setVisible(False)
        lo.addWidget(self.bar)
        self.log = QTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(200)
        self.log.setFont(QFont("Courier New", 9))
        lo.addWidget(self.log)

        btn_lo = QHBoxLayout()
        self.run_btn = QPushButton("Datenbank einrichten"); self.run_btn.setDefault(True)
        self.run_btn.clicked.connect(self._start)
        close_btn = QPushButton("Schließen"); close_btn.clicked.connect(self.accept)
        btn_lo.addWidget(self.run_btn); btn_lo.addWidget(close_btn)
        lo.addLayout(btn_lo)

    def _test(self):
        try:
            import psycopg2
            con = psycopg2.connect(host=self.host_edit.text(),
                                   port=self.port_spin.value(),
                                   dbname="postgres",
                                   user=self.user_edit.text(),
                                   password=self.pw_edit.text(),
                                   connect_timeout=5)
            cur = con.cursor(); cur.execute("SELECT version()")
            v = cur.fetchone()[0].split(",")[0]; con.close()
            self._log(f"✓ {v}")
        except ImportError:
            self._log("⚠ psycopg2 nicht verfügbar – Fallback auf ogr2ogr")
        except Exception as e:
            self._log(f"✗ {e}")

    def _start(self):
        sel = [k for k, cb in self._cbs.items() if cb.isChecked()]
        if not sel: self._log("⚠ Keine Fachschale gewählt."); return
        cfg = dict(host=self.host_edit.text(), port=self.port_spin.value(),
                   db=self.db_edit.text(), user=self.user_edit.text(),
                   password=self.pw_edit.text(), srid=self.srid_spin.value(),
                   create_db=self.create_cb.isChecked(), schemas=sel)
        self.run_btn.setEnabled(False)
        self.bar.setVisible(True); self.bar.setValue(0); self.log.clear()
        self._log(f"Starte Setup '{cfg['db']}' mit {len(sel)} Fachschalen …")
        self._worker = _SetupWorker(cfg)
        self._worker.progress.connect(self._on_prog)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_prog(self, pct, msg):
        if pct >= 0: self.bar.setValue(pct)
        self._log(msg)

    def _on_done(self, ok, msg):
        self.bar.setValue(100 if ok else 0)
        self.run_btn.setEnabled(True)
        self._log(""); self._log(msg)

    def _log(self, msg): self.log.append(msg)
