"""
Lädt Fachschalen-Konfiguration aus PostGIS.
Fallback: fachschalen_config.py (fest verdrahtet aus Musterdaten).
"""

from qgis.PyQt.QtCore import QThread, pyqtSignal
from .fachschalen_config import FACHSCHALEN


# ── Fachschalen-Liste ─────────────────────────────────────────────────────────
class FachschalenLoader(QThread):
    """
    Versucht Fachschalen aus public.fachschalen_config zu laden.
    Bei Fehler: Fallback auf FACHSCHALEN aus fachschalen_config.py.
    """
    ready = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, conn_params: dict):
        super().__init__()
        self.conn_params = conn_params

    def run(self):
        try:
            import psycopg2
            conn = psycopg2.connect(**self.conn_params)
            cur  = conn.cursor()
            cur.execute("""
                SELECT code, bezeichnung, schema_name, ref_schema
                FROM public.fachschalen_config
                WHERE aktiv = TRUE
                ORDER BY bezeichnung;
            """)
            rows = [
                {
                    "code":        r[0],
                    "bezeichnung": r[1],
                    "schema_name": r[2],
                    "ref_schema":  r[3],
                    "geo_layers":  [],
                    "ref_tables":  [],
                }
                for r in cur.fetchall()
            ]
            conn.close()

            # Bekannte Fachschalen mit lokaler Konfiguration anreichern
            _enrich_from_config(rows)

            self.ready.emit(rows if rows else FACHSCHALEN)

        except Exception as exc:
            # Fallback: lokale Konfiguration
            self.error.emit(str(exc))
            self.ready.emit(FACHSCHALEN)


def _enrich_from_config(rows: list):
    """Fügt geo_layers / ref_tables aus lokaler Config ein, wenn vorhanden."""
    config_map = {f["code"]: f for f in FACHSCHALEN}
    for row in rows:
        local = config_map.get(row["code"])
        if local:
            row["geo_layers"] = local.get("geo_layers", [])
            row["ref_tables"] = local.get("ref_tables", [])


# ── Layer + Referenzlisten einer Fachschale laden ─────────────────────────────
class FachschaleLayerLoader(QThread):
    """
    Lädt Layer der Fachschale aus PostGIS.
    Bekannte Fachschalen (z. B. Fundpunkte Tiere) nutzen die
    fest definierte Struktur aus fachschalen_config.py.
    """
    ready = pyqtSignal(list, list)   # (geo_layers, ref_tables)
    error = pyqtSignal(str)

    def __init__(self, conn_params: dict, fachschale: dict):
        super().__init__()
        self.conn_params = conn_params
        self.fachschale  = fachschale

    def run(self):
        # Bekannte Struktur aus lokaler Config → direkt verwenden
        if self.fachschale.get("geo_layers") or self.fachschale.get("ref_tables"):
            geo = self._build_geo_rows()
            ref = self._build_ref_rows()
            self.ready.emit(geo, ref)
            return

        # Unbekannte Fachschale → generisch aus DB laden
        self._load_from_db()

    def _build_geo_rows(self) -> list:
        # Styles aus public.layer_styles vorladen
        styles = self._fetch_styles(self.fachschale["schema_name"])
        rows = []
        for gl in self.fachschale.get("geo_layers", []):
            tbl_lower = gl["table"].lower()
            style_name, style_qml = styles.get(tbl_lower, ("", ""))
            rows.append({
                "schema":            self.fachschale["schema_name"],
                "table":             gl["table"],
                "geom_col":          gl["geom_col"],
                "geom_type":         gl["geom_type"],
                "style_name":        style_name,
                "style_qml":         style_qml,
                "is_ref":            False,
                "value_relations":   gl.get("value_relations", {}),
                "default_values":    gl.get("default_values", {}),
                "extra_widgets":     gl.get("extra_widgets", {}),
            })
        return rows

    def _build_ref_rows(self) -> list:
        styles = self._fetch_styles(self.fachschale["ref_schema"])
        rows = []
        for tbl in self.fachschale.get("ref_tables", []):
            tbl_lower = tbl.lower()
            style_name, style_qml = styles.get(tbl_lower, ("", ""))
            rows.append({
                "schema":          self.fachschale["ref_schema"],
                "table":           tbl,
                "geom_col":        None,
                "geom_type":       "Tabelle",
                "style_name":      style_name,
                "style_qml":       style_qml,
                "is_ref":          True,
                "value_relations": {},
            })
        return rows

    def _fetch_styles(self, schema: str) -> dict:
        """Lädt alle Styles für ein Schema aus public.layer_styles.
        Gibt {table_lower: (style_name, style_qml)} zurück.
        """
        result = {}
        try:
            import psycopg2
            conn = psycopg2.connect(**self.conn_params)
            cur  = conn.cursor()
            cur.execute("""
                SELECT LOWER(f_table_name), styleName, styleQML
                FROM public.layer_styles
                WHERE LOWER(f_table_schema) = LOWER(%s)
                  AND useAsDefault = TRUE
                ORDER BY id DESC
            """, (schema,))
            for tbl, name, qml in cur.fetchall():
                if tbl not in result:   # erste (neueste) Eintrag gewinnt
                    result[tbl] = (name or "", qml or "")
            conn.close()
        except Exception as _e:
            from qgis.core import QgsMessageLog
            QgsMessageLog.logMessage(
                f"FachschalenLoader: {_e}", "NRW Naturschutz", 1)
        return result

    def _load_from_db(self):
        """Generischer DB-Loader für unbekannte Fachschalen."""
        try:
            import psycopg2
            conn = psycopg2.connect(**self.conn_params)
            cur  = conn.cursor()
            schema     = self.fachschale["schema_name"]
            ref_schema = self.fachschale["ref_schema"]
            gemeinsam  = self.fachschale.get("gemeinsam", "gemeinsam")

            cur.execute("""
                SELECT f.f_table_schema, f.f_table_name,
                       f.f_geometry_column, f.type,
                       COALESCE(s.stylename,''), COALESCE(s.styleqml,'')
                FROM geometry_columns f
                LEFT JOIN layer_styles s
                       ON s.f_table_schema = f.f_table_schema
                      AND s.f_table_name   = f.f_table_name
                      AND s.useAsDefault   = TRUE
                WHERE f.f_table_schema = %s
                ORDER BY f.f_table_name;
            """, (schema,))
            geo = [
                {
                    "schema": r[0], "table": r[1], "geom_col": r[2],
                    "geom_type": r[3], "style_name": r[4], "style_qml": r[5],
                    "is_ref": False, "value_relations": {},
                }
                for r in cur.fetchall()
            ]

            cur.execute("""
                SELECT t.table_schema, t.table_name,
                       COALESCE(s.stylename,''), COALESCE(s.styleqml,'')
                FROM information_schema.tables t
                LEFT JOIN layer_styles s
                       ON s.f_table_schema = t.table_schema
                      AND LOWER(s.f_table_name) = LOWER(t.table_name)
                      AND s.useAsDefault   = TRUE
                WHERE t.table_schema = %s
                  AND t.table_type   = 'BASE TABLE'
                  AND t.table_name NOT IN (
                      SELECT f_table_name FROM geometry_columns
                      WHERE f_table_schema = %s)
                ORDER BY t.table_name;
            """, (ref_schema, ref_schema))
            ref = [
                {
                    "schema": r[0], "table": r[1],
                    "style_name": r[2], "style_qml": r[3],
                    "geom_col": None, "geom_type": "Tabelle",
                    "is_ref": True, "value_relations": {},
                }
                for r in cur.fetchall()
            ]
            conn.close()
            self.ready.emit(geo, ref)

        except Exception as exc:
            self.error.emit(str(exc))
