"""
ornitho_import_dialog.py – Ornitho.de Basic+ JSON importieren
==============================================================
Liest den ornitho.de-Export im Basic+-Format (JSON) und erstellt
einen QGIS-Punktlayer mit allen Feldbeobachtungen.
"""

import json
from datetime import datetime

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QGroupBox, QLineEdit,
    QTextEdit, QProgressBar, QFileDialog, QCheckBox,
    QSpinBox, QComboBox,
)
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsPointXY, QgsFields, QgsField, QgsCoordinateReferenceSystem,
)


class OrnithoImportDialog(QDialog):
    """Dialog zum Import von ornitho.de Basic+-Exporten."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ornitho.de – Basic+ Import")
        self.setMinimumWidth(500)
        self._sightings = []
        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        lo = QVBoxLayout(self)

        # Datei-Auswahl
        file_grp = QGroupBox("Exportdatei (JSON, Basic+-Format)")
        file_lo  = QHBoxLayout(file_grp)
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("export_XXXX.json …")
        self.file_edit.setReadOnly(True)
        browse_btn = QPushButton("Durchsuchen …")
        browse_btn.clicked.connect(self._browse)
        file_lo.addWidget(self.file_edit)
        file_lo.addWidget(browse_btn)
        lo.addWidget(file_grp)

        # Filter
        flt_grp = QGroupBox("Filter (optional)")
        flt_fl  = QFormLayout(flt_grp)

        self.art_edit = QLineEdit()
        self.art_edit.setPlaceholderText("z.B. Zilpzalp  –  leer = alle Arten")
        flt_fl.addRow("Art (dt. oder lat.):", self.art_edit)

        yr_lo = QHBoxLayout()
        self.year_from = QSpinBox(); self.year_from.setRange(1900, 2100); self.year_from.setValue(2020)
        self.year_to   = QSpinBox(); self.year_to.setRange(1900, 2100)
        self.year_to.setValue(datetime.now().year)
        yr_lo.addWidget(self.year_from)
        yr_lo.addWidget(QLabel("–"))
        yr_lo.addWidget(self.year_to)
        self.year_cb = QCheckBox("Jahresfilter aktiv")
        yr_lo.addWidget(self.year_cb)
        flt_fl.addRow("Zeitraum (Jahr):", yr_lo)

        self.only_precise = QCheckBox("Nur präzise GPS-Koordinaten (precision=precise)")
        self.only_precise.setChecked(True)
        flt_fl.addRow("", self.only_precise)

        lo.addWidget(flt_grp)

        # Vorschau
        self.info_lbl = QLabel("Keine Datei geladen.")
        self.info_lbl.setStyleSheet("color: gray; font-style: italic;")
        lo.addWidget(self.info_lbl)

        # Log
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        lo.addWidget(self.log)

        # Buttons
        btn_lo = QHBoxLayout()
        self.import_btn = QPushButton("Layer erstellen")
        self.import_btn.setDefault(True)
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._import)
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self.accept)
        btn_lo.addWidget(self.import_btn)
        btn_lo.addWidget(close_btn)
        lo.addLayout(btn_lo)

    # ── Datei laden ─────────────────────────────────────────────────────────

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Ornitho Basic+ JSON öffnen", "",
            "JSON-Dateien (*.json);;Alle Dateien (*)")
        if not path:
            return
        self.file_edit.setText(path)
        self._load_file(path)

    def _load_file(self, path: str):
        try:
            data = json.load(open(path, encoding="utf-8"))
            raw  = data.get("data", data).get("sightings", [])
            self._sightings = raw
            arten = {}
            for s in raw:
                a = s.get("species", {}).get("name", "?")
                arten[a] = arten.get(a, 0) + 1
            dates = []
            for s in raw:
                iso = s.get("date", {}).get("@ISO8601", "")
                if iso:
                    try: dates.append(iso[:10])
                    except: pass
            date_info = f"{min(dates)} – {max(dates)}" if dates else "?"
            self.info_lbl.setText(
                f"{len(raw)} Beobachtungen  |  {len(arten)} Arten  |  {date_info}")
            self.info_lbl.setStyleSheet("color: #333;")
            self.import_btn.setEnabled(True)
            self._log(f"✓ {len(raw)} Beobachtungen geladen aus {path.split('/')[-1]}")
        except Exception as e:
            self._log(f"✗ Ladefehler: {e}")

    # ── Import ──────────────────────────────────────────────────────────────

    def _import(self):
        if not self._sightings:
            return
        art_filter   = self.art_edit.text().strip().lower()
        year_filter  = self.year_cb.isChecked()
        y_from       = self.year_from.value()
        y_to         = self.year_to.value()
        only_precise = self.only_precise.isChecked()

        fields = QgsFields()
        for fname, ftype in [
            ("ornitho_id",    QVariant.String),
            ("art",           QVariant.String),
            ("art_lat",       QVariant.String),
            ("art_id",        QVariant.Int),
            ("datum",         QVariant.String),
            ("jahr",          QVariant.Int),
            ("anzahl",        QVariant.Int),
            ("erfassung",     QVariant.String),   # EXACT_VALUE / MINIMUM
            ("beobachter",    QVariant.String),
            ("ort",           QVariant.String),
            ("gemeinde",      QVariant.String),
            ("atlas_code",    QVariant.String),
            ("akustisch",     QVariant.Int),       # auditory_contact
            ("kommentar",     QVariant.String),
            ("praezision",    QVariant.String),
            ("quelle",        QVariant.String),    # MOBILE_LIVE_IOS etc.
            ("guid",          QVariant.String),
            ("ornitho_url",   QVariant.String),
        ]:
            fields.append(QgsField(fname, ftype))

        lyr_name = "Ornitho"
        if art_filter:
            lyr_name += f"_{art_filter.replace(' ', '_')}"
        lyr = QgsVectorLayer("Point?crs=EPSG:4326", lyr_name, "memory")
        dp  = lyr.dataProvider()
        dp.addAttributes(fields.toList())
        lyr.updateFields()

        feats = []; skipped = 0; filtered = 0

        for s in self._sightings:
            sp  = s.get("species", {})
            art = sp.get("name", "")
            lat_name = sp.get("latin_name", "")

            # Artfilter
            if art_filter:
                if art_filter not in art.lower() and art_filter not in lat_name.lower():
                    filtered += 1
                    continue

            # Zeitfilter
            iso = s.get("date", {}).get("@ISO8601", "")
            year = int(iso[:4]) if iso and len(iso) >= 4 else 0
            if year_filter and year:
                if not (y_from <= year <= y_to):
                    filtered += 1
                    continue

            obs = s.get("observers", [{}])[0] if s.get("observers") else {}
            place = s.get("place", {})

            # Koordinaten: GPS-Beobachter zuerst, sonst Rasterpunkt
            try:
                lat = float(obs.get("coord_lat") or obs.get("gps_lat") or
                            place.get("coord_lat", 0))
                lon = float(obs.get("coord_lon") or obs.get("gps_lon") or
                            place.get("coord_lon", 0))
            except (ValueError, TypeError):
                skipped += 1; continue
            if lat == 0 and lon == 0:
                skipped += 1; continue

            precision = obs.get("precision", "")
            if only_precise and precision and precision != "precise":
                skipped += 1; continue

            # Atlas-Code
            atlas = obs.get("atlas_code", {})
            atlas_txt = ""
            if isinstance(atlas, dict):
                atlas_txt = atlas.get("#text", atlas.get("@id", ""))
            elif atlas:
                atlas_txt = str(atlas)

            # Anzahl
            try: count = int(obs.get("count", 1) or 1)
            except: count = 1

            # Erfassungscode
            est = obs.get("estimation_code", "")
            est_de = {"EXACT_VALUE": "Exakt", "MINIMUM": "Minimum",
                      "MAXIMUM": "Maximum", "ESTIMATE": "Schätzung"}.get(est, est)

            # Datum
            datum_str = iso[:10] if iso else ""

            feat = QgsFeature(lyr.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
            feat["ornitho_id"] = obs.get("id_universal", obs.get("id_sighting", ""))
            feat["art"]        = art
            feat["art_lat"]    = lat_name
            feat["art_id"]     = int(sp.get("@id", 0) or 0)
            feat["datum"]      = datum_str
            feat["jahr"]       = year
            feat["anzahl"]     = count
            feat["erfassung"]  = est_de
            feat["beobachter"] = obs.get("name", "")
            feat["ort"]        = place.get("name", "")
            feat["gemeinde"]   = place.get("municipality", "")
            feat["atlas_code"] = atlas_txt
            feat["akustisch"]  = int(obs.get("auditory_contact", 0) or 0)
            feat["kommentar"]  = obs.get("comment", "")
            feat["praezision"] = precision
            feat["quelle"]     = obs.get("source", "")
            feat["guid"]       = obs.get("guid", "")
            oid = obs.get("id_sighting", "")
            feat["ornitho_url"] = f"https://www.ornitho.de/index.php?m_id=94&showback=1&idt_sighting={oid}" if oid else ""
            feats.append(feat)

        dp.addFeatures(feats)
        lyr.updateExtents()

        # Stil: orangefarbene Punkte
        try:
            sym = lyr.renderer().symbol()
            sym.setColor(QColor(220, 80, 20))
            sym.setSize(2.5)
        except Exception:
            pass

        QgsProject.instance().addMapLayer(lyr)
        self._log(
            f"✓ Layer '{lyr_name}': {len(feats)} Fundpunkte"
            + (f", {filtered} gefiltert" if filtered else "")
            + (f", {skipped} ohne Koordinaten" if skipped else ""))

    def _log(self, msg: str):
        self.log.append(msg)
