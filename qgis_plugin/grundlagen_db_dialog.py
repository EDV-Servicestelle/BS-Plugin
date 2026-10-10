"""
grundlagen_db_dialog.py – Zentrale Grundlagen-Datenbank verwalten
=================================================================
Befüllt und aktualisiert eine dedizierte nrw_grundlagen PostGIS-DB.
Der Fachschalen-Wizard ruft bei der Projekterstellung per ST_Intersects
daraus ab statt jeden Dienst einzeln anzufragen.
"""

import os
from pathlib import Path
from .pg_verbindung import bezeichner_sql
from datetime import datetime

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QPushButton, QLineEdit, QSpinBox, QTextEdit,
    QProgressBar, QCheckBox, QTreeWidget, QTreeWidgetItem,
    QTabWidget, QWidget, QSizePolicy,
)
from qgis.PyQt.QtCore import QThread, pyqtSignal, Qt
from qgis.PyQt.QtGui import QFont, QColor

PLUGIN_DIR = Path(__file__).parent

# ── Dienste die in der Grundlagen-DB gehalten werden ────────────────────────
GRUNDLAGEN_DIENSTE = {
    # Schutzgebiete (OGC-API)
    "nsg":      {"label": "Naturschutzgebiete (NSG)",          "schema": "schutzgebiete", "typ": "ogcapi"},
    "lsg":      {"label": "Landschaftsschutzgebiete (LSG)",    "schema": "schutzgebiete", "typ": "ogcapi"},
    "ffh":      {"label": "FFH-Gebiete",                       "schema": "schutzgebiete", "typ": "ogcapi"},
    "vsg":      {"label": "Vogelschutzgebiete (VSG)",          "schema": "schutzgebiete", "typ": "ogcapi"},
    "ntp":      {"label": "Naturdenkmale / NTP",               "schema": "schutzgebiete", "typ": "ogcapi"},
    "ffh_lrt":  {"label": "FFH-Lebensraumtypen",               "schema": "schutzgebiete", "typ": "ffh_lrt"},
    # Bodennutzung / Landwirtschaft (LWK NRW)
    "lwk_feldblöcke":      {"label": "Feldblöcke (LWK)",             "schema": "bodennutzung", "typ": "lwk_wfs",
                             "typename": "app:Feldbloecke",
                             "felder": [("flik","FLIK"),("nutz_code","NUTZ_CODE"),
                                        ("nutz_txt","NUTZ_TXT"),("area_ha","AREA_HA"),
                                        ("validfrom","VALIDFROM")]},
    "lwk_teilschlaege":    {"label": "Teilschläge (LWK)",            "schema": "bodennutzung", "typ": "lwk_wfs",
                             "typename": "app:Teilschlaege",
                             "felder": [("flik","FLIK"),("nutz_code","NUTZ_CODE"),
                                        ("nutz_txt","NUTZ_TXT"),("area_ha","AREA_HA")]},
    "lwk_dauergruenland":  {"label": "Dauergrünland (LWK)",          "schema": "bodennutzung", "typ": "lwk_wfs",
                             "typename": "app:Dauergruenland",
                             "felder": [("flik","FLIK"),("area_ha","AREA_HA")]},
    "lwk_landschaftselem": {"label": "Landschaftselemente (LWK)",    "schema": "bodennutzung", "typ": "lwk_wfs",
                             "typename": "app:Landschaftselemente",
                             "felder": [("flek","FLEK"),("le_code","LE_CODE"),
                                        ("le_txt","LE_TXT")]},
    # ATKIS
    "atkis_gewaesserachse":    {"label": "Gewässerachsen",     "schema": "atkis", "typ": "atkis_wfs"},
    "atkis_gewaesser_fliessend":{"label":"Fließgewässer",      "schema": "atkis", "typ": "atkis_wfs"},
    "atkis_gewaesser_stehend": {"label": "Stehende Gewässer",  "schema": "atkis", "typ": "atkis_wfs"},
    "atkis_kanal":             {"label": "Kanäle",             "schema": "atkis", "typ": "atkis_wfs"},
    "atkis_wald":              {"label": "Wald",               "schema": "atkis", "typ": "atkis_wfs"},
    "atkis_gehoelz":           {"label": "Gehölze",            "schema": "atkis", "typ": "atkis_wfs"},
    "atkis_moor":              {"label": "Moore",              "schema": "atkis", "typ": "atkis_wfs"},
    "atkis_heide":             {"label": "Heiden",             "schema": "atkis", "typ": "atkis_wfs"},
    "atkis_landwirtschaft":    {"label": "Landwirtschaft",     "schema": "atkis", "typ": "atkis_wfs"},
    "atkis_siedlung":          {"label": "Siedlungsfläche",    "schema": "atkis", "typ": "atkis_wfs"},
    "atkis_strassenverkehr":   {"label": "Straßen",           "schema": "atkis", "typ": "atkis_wfs"},
    "atkis_bahnverkehr":       {"label": "Bahnnetz",          "schema": "atkis", "typ": "atkis_wfs"},
}


# ── Worker ───────────────────────────────────────────────────────────────────
class _UpdateWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, cfg: dict):
        super().__init__()
        self._cfg = cfg

    def run(self):
        try:
            self._update()
        except Exception as e:
            self.finished.emit(False, str(e))

    def _update(self):
        cfg      = self._cfg
        host     = cfg["host"]; port = cfg["port"]
        db       = cfg["db"];   user = cfg["user"]; pw = cfg["password"]
        dienste  = cfg["dienste"]
        bbox     = cfg.get("bbox_nrw", (5.8, 50.3, 9.5, 52.6))  # ganz NRW

        try:
            import psycopg2 as _pg
        except ImportError:
            _pg = None

        # 1. DB + Extensions + Schemas
        self.progress.emit(2, "Lege DB-Struktur an …")
        for ddl in [
            bezeichner_sql("CREATE DATABASE {d} ENCODING 'UTF8'", d=db),
        ]:
            self._sql("postgres", ddl, _pg, host, port, user, pw, ignore_errors=True)

        for ddl in [
            "CREATE EXTENSION IF NOT EXISTS postgis",
            "CREATE SCHEMA IF NOT EXISTS schutzgebiete",
            "CREATE SCHEMA IF NOT EXISTS atkis",
            "CREATE SCHEMA IF NOT EXISTS bodennutzung",
            "CREATE SCHEMA IF NOT EXISTS landnutzung",
            """CREATE TABLE IF NOT EXISTS public.grundlagen_index (
                id          SERIAL PRIMARY KEY,
                dienst_key  TEXT UNIQUE NOT NULL,
                label       TEXT,
                schema_name TEXT,
                bbox_wgs84  TEXT,
                last_update TIMESTAMP,
                feature_count INTEGER DEFAULT 0,
                srid        INTEGER DEFAULT 25832
            )""",
        ]:
            self._sql(db, ddl, _pg, host, port, user, pw)

        # 2. Dienste abrufen und schreiben
        from .core.grundlagen import DIENSTE, _fetch_ogcapi, _fetch_atkis_wfs, _fetch_ffh_lrt, _write_to_gpkg
        from qgis.core import QgsCoordinateReferenceSystem
        import tempfile

        crs   = QgsCoordinateReferenceSystem("EPSG:25832")
        total = len(dienste); done = 0

        for key in dienste:
            if key not in GRUNDLAGEN_DIENSTE or key not in DIENSTE:
                done += 1; continue
            gd     = GRUNDLAGEN_DIENSTE[key]
            cfg_d  = DIENSTE[key]
            schema = gd["schema"]
            pct    = 5 + int(85 * done / max(total, 1))
            self.progress.emit(pct, f"► {gd['label']} …")

            try:
                typ = cfg_d["typ"]
                if typ == "lwk_wfs":
                    features = self._fetch_lwk_wfs(gd, bbox)
                elif typ == "ogcapi":
                    features = _fetch_ogcapi(cfg_d, bbox, 120)
                elif typ == "ffh_lrt":
                    features = _fetch_ffh_lrt(cfg_d, bbox, 120)
                else:
                    features = _fetch_atkis_wfs(cfg_d, bbox, 120)

                if not features:
                    self.progress.emit(-1, f"  ⚠ {key}: 0 Features")
                    done += 1; continue

                # Temp-GPKG → ogr2ogr → PostGIS
                import subprocess, os as _os
                tmp = tempfile.mktemp(suffix=f"_{key}.gpkg")
                _write_to_gpkg(tmp, key, features, cfg_d, crs, append=False)

                pg_uri = f"PG:host={host} port={port} dbname={db} user={user} password={pw}"
                cmd = [
                    "ogr2ogr", "-overwrite", "-f", "PostgreSQL", pg_uri, tmp, key,
                    "-nln", f"{schema}.{key}",
                    "-lco", f"SCHEMA={schema}",
                    "-lco", "GEOMETRY_NAME=geom",
                    "-lco", "FID=gid",
                    "-lco", "OVERWRITE=YES",
                    "-nlt", "PROMOTE_TO_MULTI",
                    "-t_srs", "EPSG:25832",
                ]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                try: _os.unlink(tmp)
                except: pass

                if r.returncode != 0:
                    self.progress.emit(-1, f"  ✗ {key}: {r.stderr[:80]}")
                else:
                    # Index-Eintrag aktualisieren
                    self._sql(db,
                        """INSERT INTO public.grundlagen_index
                            (dienst_key, label, schema_name, bbox_wgs84, last_update, feature_count)
                            VALUES (%s, %s, %s, %s, NOW(), %s)
                            ON CONFLICT (dienst_key) DO UPDATE SET
                              last_update = NOW(), feature_count = EXCLUDED.feature_count""",
                        _pg, host, port, user, pw,
                        params=(key, gd["label"], schema, str(bbox), len(features)))
                    self.progress.emit(-1, f"  ✓ {key}: {len(features)} Features")
            except Exception as e:
                self.progress.emit(-1, f"  ✗ {key}: {e}")
            done += 1

        self.progress.emit(100, "✓ Fertig")
        self.finished.emit(True,
            f"Grundlagen-DB '{db}' aktualisiert.\n"
            f"{total} Dienste verarbeitet.")

    def _fetch_lwk_wfs(self, gd: dict, bbox: tuple) -> list:
        """LWK NRW WFS: Feldblöcke, Teilschläge, Dauergrünland, Landschaftselemente."""
        import urllib.request, urllib.parse, xml.etree.ElementTree as ET

        url    = "https://www.wfs.nrw.de/umwelt/lwk_eufoerderung"
        typename = gd.get("typename", "app:Feldbloecke")
        lon_min, lat_min, lon_max, lat_max = bbox
        bbox_str = f"{lon_min},{lat_min},{lon_max},{lat_max},EPSG:4326"

        params = {
            "SERVICE": "WFS", "VERSION": "2.0.0",
            "REQUEST": "GetFeature",
            "TYPENAMES": typename,
            "SRSNAME": "EPSG:25832",
            "BBOX": bbox_str,
            "COUNT": "50000",
        }
        try:
            req = urllib.request.urlopen(
                url + "?" + urllib.parse.urlencode(params), timeout=120)
            data = req.read()
            root = ET.fromstring(data)
        except Exception as e:
            self.progress.emit(-1, f"  LWK WFS Fehler: {e}")
            return []

        ns = {
            "wfs": "http://www.opengis.net/wfs/2.0",
            "gml": "http://www.opengis.net/gml/3.2",
            "app": "http://www.deegree.org/app",
        }
        feats = []
        felder = gd.get("felder", [])
        for member in root.iter("{http://www.opengis.net/wfs/2.0}member"):
            for feat_el in member:
                props = {}
                for attr_name, xml_name in felder:
                    el = feat_el.find(f"{{http://www.deegree.org/app}}{xml_name}")
                    props[attr_name] = el.text if el is not None else None
                # Geometrie
                geom_el = feat_el.find(".//{http://www.opengis.net/gml/3.2}posList")
                if geom_el is not None:
                    nums = (geom_el.text or "").split()
                    if len(nums) >= 6:
                        pts  = [f"{float(nums[i]):.2f} {float(nums[i+1]):.2f}"
                                for i in range(0, len(nums)-1, 2)]
                        wkt  = "MULTIPOLYGON(((" + ", ".join(pts) + ")))"
                        feats.append({"props": props, "wkt": wkt})
        return feats

    def _sql(self, dbname, sql, pg, host, port, user, pw, ignore_errors=False, params=None):
        if pg and sql is not None:
            try:
                con = pg.connect(host=host, port=port, dbname=dbname,
                                 user=user, password=pw)
                con.autocommit = True
                con.cursor().execute(sql, params)
                con.close()
            except Exception as e:
                if not ignore_errors and "already exists" not in str(e).lower():
                    self.progress.emit(-1, f"  SQL: {str(e)[:80]}")


# ── Dialog ───────────────────────────────────────────────────────────────────
class GrundlagenDbDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Grundlagen-Datenbank verwalten")
        self.setMinimumSize(740, 640)
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        tabs = QTabWidget()
        lo.addWidget(tabs)

        # ── Tab 1: Verbindung ────────────────────────────────────────────────
        cw = QWidget(); cl = QVBoxLayout(cw)
        grp = QGroupBox("PostgreSQL-Verbindung (Grundlagen-DB)")
        fl  = QFormLayout(grp)
        self.host_edit = QLineEdit("localhost")
        self.port_spin = QSpinBox(); self.port_spin.setRange(1,65535); self.port_spin.setValue(5432)
        self.db_edit   = QLineEdit("nrw_grundlagen")
        self.user_edit = QLineEdit("postgres")
        self.pw_edit   = QLineEdit(); self.pw_edit.setEchoMode(QLineEdit.Password)
        fl.addRow("Host:",      self.host_edit)
        fl.addRow("Port:",      self.port_spin)
        fl.addRow("Datenbank:", self.db_edit)
        fl.addRow("Benutzer:",  self.user_edit)
        fl.addRow("Passwort:",  self.pw_edit)
        cl.addWidget(grp)

        info = QLabel(
            "Die Grundlagen-DB wird <b>einmal zentral befüllt</b> und gepflegt.<br>"
            "Der Fachschalen-Wizard ruft bei der Projekterstellung per "
            "<tt>ST_Intersects(geom, bbox_ug)</tt> daraus ab – "
            "kein WFS-Download bei jedem Projekt mehr."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: var(--color-text-secondary, gray); padding: 8px 0; font-size: 12px;")
        cl.addWidget(info)

        btn_row = QHBoxLayout()
        test_btn = QPushButton("Verbindung testen / Index anzeigen")
        test_btn.clicked.connect(self._test)
        save_btn = QPushButton("Als Standard speichern")
        save_btn.clicked.connect(self._save_settings)
        btn_row.addWidget(test_btn); btn_row.addWidget(save_btn)
        cl.addLayout(btn_row)
        cl.addStretch()
        tabs.addTab(cw, "Verbindung")

        # ── Tab 2: Dienste auswählen ────────────────────────────────────────
        sw = QWidget(); sl = QVBoxLayout(sw)
        sl.addWidget(QLabel("Dienste für Grundlagen-DB auswählen:"))

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Dienst", "Schema", "Typ"])
        self.tree.setColumnWidth(0, 260); self.tree.setColumnWidth(1, 100)
        self._cbs = {}

        gruppen = {}
        for key, gd in GRUNDLAGEN_DIENSTE.items():
            gruppen.setdefault(gd["schema"], []).append((key, gd))

        for schema, items in gruppen.items():
            parent = QTreeWidgetItem(self.tree)
            parent.setText(0, schema.upper())
            parent.setExpanded(True)
            for key, gd in items:
                child = QTreeWidgetItem(parent)
                cb = QCheckBox()
                cb.setChecked(True)
                self.tree.setItemWidget(child, 0, cb)
                child.setText(1, gd["label"])
                child.setText(2, gd["schema"])
                self._cbs[key] = cb

        sl.addWidget(self.tree)

        # Bereich-Auswahl
        bbox_grp = QGroupBox("Abruf-Bereich (WGS84)")
        bbox_fl  = QFormLayout(bbox_grp)
        self.bbox_info = QLabel("Standard: ganz NRW (5.8°O – 9.5°O, 50.3°N – 52.6°N)")
        self.bbox_info.setStyleSheet("font-size: 11px; color: gray;")
        bbox_fl.addRow("", self.bbox_info)
        sl.addWidget(bbox_grp)
        tabs.addTab(sw, "Dienste")

        # ── Log + Fortschritt ────────────────────────────────────────────────
        self.bar = QProgressBar(); self.bar.setRange(0,100); self.bar.setVisible(False)
        lo.addWidget(self.bar)
        self.log = QTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(220)
        self.log.setFont(QFont("Courier New", 9))
        lo.addWidget(self.log)

        btn_lo = QHBoxLayout()
        self.run_btn = QPushButton("Grundlagen-DB aktualisieren")
        self.run_btn.setDefault(True)
        self.run_btn.clicked.connect(self._start)
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self.accept)
        btn_lo.addWidget(self.run_btn); btn_lo.addWidget(close_btn)
        lo.addLayout(btn_lo)

    def _save_settings(self):
        from qgis.core import QgsSettings
        s = QgsSettings()
        s.setValue("naturschutz/grundlagen_host", self.host_edit.text())
        s.setValue("naturschutz/grundlagen_port", self.port_spin.value())
        s.setValue("naturschutz/grundlagen_db",   self.db_edit.text())
        s.setValue("naturschutz/grundlagen_user",  self.user_edit.text())
        s.setValue("naturschutz/grundlagen_pw",    self.pw_edit.text())
        self._log("✓ Verbindung gespeichert – Wizard nutzt diese DB ab sofort.")

    def _test(self):

        try:
            import psycopg2
            con = psycopg2.connect(
                host=self.host_edit.text(), port=self.port_spin.value(),
                dbname=self.db_edit.text(), user=self.user_edit.text(),
                password=self.pw_edit.text(), connect_timeout=5)
            cur = con.cursor()
            try:
                cur.execute("""
                    SELECT dienst_key, label, feature_count,
                           to_char(last_update,'DD.MM.YYYY HH24:MI') as dt
                    FROM public.grundlagen_index ORDER BY dienst_key
                """)
                rows = cur.fetchall()
                self._log(f"✓ Verbindung OK – {len(rows)} Dienste im Index:")
                for r in rows:
                    self._log(f"  {r[0]:30s} {r[2]:>6} Features  ({r[3]})")
            except Exception:
                self._log("✓ Verbindung OK – Grundlagen-Index noch nicht angelegt")
            con.close()
        except ImportError:
            self._log("⚠ psycopg2 nicht verfügbar")
        except Exception as e:
            self._log(f"✗ {e}")

    def _start(self):
        sel = [k for k, cb in self._cbs.items() if cb.isChecked()]
        if not sel:
            self._log("⚠ Keine Dienste ausgewählt."); return
        cfg = dict(
            host=self.host_edit.text(), port=self.port_spin.value(),
            db=self.db_edit.text(), user=self.user_edit.text(),
            password=self.pw_edit.text(),
            dienste=sel,
            bbox_nrw=(5.8, 50.3, 9.5, 52.6),
        )
        self.run_btn.setEnabled(False)
        self.bar.setVisible(True); self.bar.setValue(0); self.log.clear()
        self._log(f"Starte Update '{cfg['db']}': {len(sel)} Dienste …")
        self._worker = _UpdateWorker(cfg)
        self._worker.progress.connect(lambda p, m: (
            self.bar.setValue(p) if p >= 0 else None, self._log(m)))
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_done(self, ok, msg):
        self.bar.setValue(100 if ok else 0)
        self.run_btn.setEnabled(True)
        self._log(""); self._log(msg)

    def _log(self, msg): self.log.append(msg)


def get_conn_params_from_settings() -> dict | None:
    """Liest gespeicherte Grundlagen-DB-Verbindung aus QGIS-Settings."""
    from qgis.core import QgsSettings
    s = QgsSettings()
    host = s.value("naturschutz/grundlagen_host", "")
    if not host:
        return None
    return {
        "host":     host,
        "port":     int(s.value("naturschutz/grundlagen_port", 5432)),
        "dbname":   s.value("naturschutz/grundlagen_db", "nrw_grundlagen"),
        "user":     s.value("naturschutz/grundlagen_user", "postgres"),
        "password": s.value("naturschutz/grundlagen_pw", ""),
    }


def fetch_from_grundlagen_db(conn_params: dict, bbox_25832,
                              dienst_keys: list, ug_wkt: str = None) -> dict:
    """
    Lädt Features für die angegebenen Dienste aus der Grundlagen-DB.
    bbox_25832: QgsRectangle in EPSG:25832 (Fallback-Filter).
    ug_wkt:     Optionales UG-Polygon (WKT, EPSG:25832). Wenn gesetzt, werden
                die Geometrien serverseitig per ST_Intersection auf das UG
                GECLIPPT (statt nur per Bounding-Box gefiltert).
    Gibt {dienst_key: [feature_dicts]} zurück.
    """
    import json
    result = {}
    try:
        import psycopg2
        conn = psycopg2.connect(**conn_params)
        cur  = conn.cursor()

        for key in dienst_keys:
            if key not in GRUNDLAGEN_DIENSTE:
                continue
            schema = GRUNDLAGEN_DIENSTE[key]["schema"]
            try:
                if ug_wkt:
                    # Auf das UG-Polygon clippen; ST_CollectionExtract behält
                    # die Dimension der Quelle (Polygon/Linie) und verwirft
                    # punktförmige Schnitt-Artefakte.
                    cur.execute(bezeichner_sql('''
                        SELECT gid,
                               ST_AsText(ST_CollectionExtract(
                                   ST_Intersection(
                                       geom, ST_MakeValid(ST_GeomFromText(%s, 25832))),
                                   ST_Dimension(geom) + 1)) AS wkt,
                               row_to_json(t)::text AS props
                        FROM {t} t
                        WHERE ST_Intersects(
                            geom, ST_MakeValid(ST_GeomFromText(%s, 25832)))
                    ''', t=(schema, key)), (ug_wkt, ug_wkt))
                else:
                    cur.execute(bezeichner_sql('''
                        SELECT gid, ST_AsText(geom) AS wkt,
                               row_to_json(t)::text AS props
                        FROM {t} t
                        WHERE ST_Intersects(geom,
                            ST_MakeEnvelope(%s,%s,%s,%s,25832))
                    ''', t=(schema, key)), (bbox_25832.xMinimum(), bbox_25832.yMinimum(),
                          bbox_25832.xMaximum(), bbox_25832.yMaximum()))
                rows = []
                for r in cur.fetchall():
                    wkt = r[1]
                    # Leere/entartete Clip-Ergebnisse überspringen
                    if not wkt or "EMPTY" in wkt.upper():
                        continue
                    props = json.loads(r[2]) if r[2] else {}
                    props.pop("geom", None)
                    rows.append({"wkt": wkt, "props": props})
                result[key] = rows
            except Exception:
                result[key] = []   # Tabelle nicht vorhanden → leer
        conn.close()
    except Exception:
        pass
    return result
