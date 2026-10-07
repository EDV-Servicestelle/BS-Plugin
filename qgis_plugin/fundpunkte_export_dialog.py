"""
fundpunkte_export_dialog.py
============================
Exportiert den Fund-Layer als:
  • CSV (kompatibel mit Excel / LibreOffice)
  • XLSX (Excel, mit Spaltenbreiten und gefrorener Kopfzeile)
  • GPKG (GeoPackage, für GIS-Nachnutzung)

Felder: alle Attribute + optional WKT-Geometrie (für CSV/XLSX)
"""

import os
import csv
from datetime import datetime

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QDialogButtonBox,
    QProgressBar, QTextEdit, QComboBox, QCheckBox,
    QFileDialog, QLineEdit, QGroupBox, QRadioButton,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsVectorFileWriter,
    QgsCoordinateTransformContext, QgsWkbTypes,
)

_PLUGIN_DIR = os.path.dirname(__file__)

# Steuerfeld: Features mit aktivem Flag werden NICHT exportiert; das Feld selbst
# wird NIE mitexportiert. (Frühere Bezeichnungen des Feldes: kein_Export, AN_LANUK.)
EXPORT_FLAG_FIELD   = "Sensibel"
EXPORT_FLAG_ALIASES = ("sensibel", "kein_export", "an_lanuk")


def _fmt_val(val):
    """Konvertiert QGIS-Feldwerte in exportierbare Strings.
    Wandelt QDateTime/QDate/QTime in ISO-Strings um.
    """
    if val is None:
        return ""
    # QDateTime → "2026-04-20 22:00:00"
    try:
        from qgis.PyQt.QtCore import QDateTime, QDate, QTime
        if isinstance(val, QDateTime):
            return val.toString("yyyy-MM-dd HH:mm:ss") if val.isValid() else ""
        if isinstance(val, QDate):
            return val.toString("yyyy-MM-dd") if val.isValid() else ""
        if isinstance(val, QTime):
            return val.toString("HH:mm:ss") if val.isValid() else ""
    except ImportError:
        pass
    # Fallback: str() – aber repr() von Qt-Objekten abfangen
    s = str(val)
    if s.startswith("PyQt") or s.startswith("<PyQt"):
        return ""   # unbekannter Qt-Typ
    return s


class FundpunkteExportDialog(QDialog):


    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fundpunkte Tiere – Export")
        self.setMinimumWidth(520)
        self._flag_field = None
        self._build_ui()

    def _resolve_flag_field(self, lyr):
        """Findet das Steuerfeld (sensibel bzw. alt kein_Export/AN_LANUK), case-insensitiv."""
        if not lyr:
            return None
        for f in lyr.fields():
            if f.name().lower() in EXPORT_FLAG_ALIASES:
                return f.name()
        return None

    @staticmethod
    def _flag_active(val):
        """True, wenn das Steuerfeld aktiviert ist (Feature NICHT exportieren)."""
        if val is None:
            return False
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return val != 0
        return str(val).strip().lower() in ("1", "true", "t", "yes", "ja", "y", "wahr")

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.addWidget(QLabel(
            "Exportiert den Fund-Layer in verschiedene Formate.\n"
            "Artname_deutsch und Artname_wiss werden aus den Referenzlisten\n"
            "automatisch aufgelöst falls sie leer sind.\n"
            "Hinweis: Das Feld »Sensibel« wird nie exportiert; Features mit\n"
            "aktivem »Sensibel« werden vom Export ausgenommen."
        ))

        # ── Layer ────────────────────────────────────────────────────────────
        form = QFormLayout()
        self.layer_combo = QComboBox()
        self._fill_layer_combo()
        form.addRow("Layer:", self.layer_combo)
        lo.addLayout(form)

        # ── Format ───────────────────────────────────────────────────────────
        fmt_box = QGroupBox("Ausgabe-Format")
        fmt_lo  = QVBoxLayout(fmt_box)
        self.rb_csv  = QRadioButton("CSV (Excel-kompatibel, UTF-8 BOM)")
        self.rb_xlsx = QRadioButton("XLSX (Excel)")
        self.rb_gpkg = QRadioButton("GeoPackage (.gpkg)")
        self.rb_csv.setChecked(True)
        for rb in [self.rb_csv, self.rb_xlsx, self.rb_gpkg]:
            fmt_lo.addWidget(rb)
        lo.addWidget(fmt_box)

        # ── Optionen ─────────────────────────────────────────────────────────
        opt_box = QGroupBox("Optionen")
        opt_lo  = QFormLayout(opt_box)

        self.geom_check = QCheckBox("WKT-Geometrie-Spalte (nur CSV/XLSX)")
        self.geom_check.setChecked(False)
        opt_lo.addRow("", self.geom_check)

        self.art_check = QCheckBox("Artname auflösen (deutsch + wiss.)")
        self.art_check.setChecked(True)
        opt_lo.addRow("", self.art_check)

        self.filter_check = QCheckBox("Nur selektierte Features")
        self.filter_check.setChecked(False)
        opt_lo.addRow("", self.filter_check)

        lo.addWidget(opt_box)

        # ── Feldauswahl ──────────────────────────────────────────────────────
        field_box = QGroupBox("Felder (abwählen = nicht exportieren)")
        field_lo  = QVBoxLayout(field_box)
        self.field_list_lo = field_lo   # wird beim Layer-Wechsel befüllt
        self.field_checks  = {}         # feldname → QCheckBox
        self.layer_combo.currentIndexChanged.connect(self._update_field_list)
        lo.addWidget(field_box)
        # Initiale Befüllung
        from qgis.PyQt.QtCore import QTimer
        QTimer.singleShot(0, self._update_field_list)

        # ── Ausgabepfad ───────────────────────────────────────────────────────
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Ausgabedatei wählen …")
        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(32)
        browse_btn.clicked.connect(self._browse)
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse_btn)
        lo.addLayout(path_row)

        # ── Log ───────────────────────────────────────────────────────────────
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(140)
        lo.addWidget(self.log)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lo.addWidget(self.bar)

        bb = QDialogButtonBox()
        self.run_btn = bb.addButton("Exportieren", QDialogButtonBox.ButtonRole.AcceptRole)
        self.run_btn.clicked.connect(self._run)
        bb.addButton("Schließen", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        lo.addWidget(bb)

    # ── Hilfsmethoden ────────────────────────────────────────────────────────

    def _fill_layer_combo(self):
        self.layer_combo.clear()
        for lyr in QgsProject.instance().mapLayers().values():
            if isinstance(lyr, QgsVectorLayer) and "fund" in lyr.name().lower():
                self.layer_combo.addItem(lyr.name(), lyr)
        # Fallback alle Vektorlayer
        if self.layer_combo.count() == 0:
            for lyr in QgsProject.instance().mapLayers().values():
                if isinstance(lyr, QgsVectorLayer):
                    self.layer_combo.addItem(lyr.name(), lyr)

    def _update_field_list(self):
        """Baut die Feldauswahl-Checkboxen neu auf."""
        # Alte Checkboxen entfernen
        while self.field_list_lo.count():
            item = self.field_list_lo.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.field_checks.clear()
        lyr = self.layer_combo.currentData()
        if not lyr: return
        self._flag_field = self._resolve_flag_field(lyr)
        # Felder die standardmäßig ausgeblendet werden
        HIDDEN_DEFAULT = {"fid", "geom"}
        from qgis.PyQt.QtWidgets import QHBoxLayout as _HBox, QWidget as _W
        row_widget = None; row_lo = None; col = 0
        for field in lyr.fields():
            if self._flag_field and field.name() == self._flag_field:
                continue   # Steuerfeld nie exportierbar → keine Checkbox
            if col % 3 == 0:
                row_widget = _W()
                row_lo = _HBox(row_widget)
                row_lo.setContentsMargins(0,0,0,0)
                self.field_list_lo.addWidget(row_widget)
            cb = QCheckBox(field.name())
            cb.setChecked(field.name() not in HIDDEN_DEFAULT)
            row_lo.addWidget(cb)
            self.field_checks[field.name()] = cb
            col += 1

    def _browse(self):
        if self.rb_csv.isChecked():
            ext, filt = "csv", "CSV (*.csv)"
        elif self.rb_xlsx.isChecked():
            ext, filt = "xlsx", "Excel (*.xlsx)"
        else:
            ext, filt = "gpkg", "GeoPackage (*.gpkg)"

        default = os.path.join(
            os.path.expanduser("~"),
            f"Fundpunkte_Export_{datetime.now().strftime('%Y%m%d')}.{ext}"
        )
        path, _ = QFileDialog.getSaveFileName(self, "Exportdatei", default, filt)
        if path:
            self.path_edit.setText(path)

    def _log(self, msg):
        self.log.append(msg)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    # ── Export ───────────────────────────────────────────────────────────────

    def _run(self):
        self.run_btn.setEnabled(False)
        self.log.clear()

        lyr  = self.layer_combo.currentData()
        path = self.path_edit.text().strip()

        if not lyr:
            self._log("⚠ Kein Layer gewählt."); self.run_btn.setEnabled(True); return
        if not path:
            self._log("⚠ Kein Ausgabepfad angegeben."); self.run_btn.setEnabled(True); return

        # Art-Lookup aufbauen (entityid → (deutsch, wiss))
        art_lookup = {}
        if self.art_check.isChecked():
            for ref in QgsProject.instance().mapLayers().values():
                if isinstance(ref, QgsVectorLayer) and "arten" == ref.name().lower():
                    for f in ref.getFeatures():
                        eid  = str(f.attribute("entityid") or "")
                        de   = f.attribute("Name_deutsch") or ""
                        wiss = f.attribute("term")         or ""
                        if eid:
                            art_lookup[eid] = (de, wiss)
                    break

        flag = self._resolve_flag_field(lyr)
        feats = list(lyr.selectedFeatures() if self.filter_check.isChecked()
                     else lyr.getFeatures())
        if flag:
            before = len(feats)
            feats = [f for f in feats if not self._flag_active(f.attribute(flag))]
            skipped = before - len(feats)
            if skipped:
                self._log(f"ℹ {skipped} Feature(s) mit aktivem »{flag}« werden nicht exportiert.")
        total = len(feats)
        self.bar.setRange(0, max(total, 1))
        self.bar.setVisible(True)

        if self.rb_gpkg.isChecked():
            self._export_gpkg(lyr, path, feats, total)
        elif self.rb_xlsx.isChecked():
            self._export_xlsx(lyr, path, feats, total, art_lookup)
        else:
            self._export_csv(lyr, path, feats, total, art_lookup)

        self.run_btn.setEnabled(True)

    def _rows(self, lyr, feats, art_lookup):
        """Gibt Header + Datenzeilen zurück."""
        fields = lyr.fields()
        flag = self._resolve_flag_field(lyr)
        # Nur gewählte Felder exportieren; Steuerfeld nie
        selected_fields = [f for f in fields
                           if f.name() != flag
                           and (self.field_checks.get(f.name(), None) is None
                                or self.field_checks[f.name()].isChecked())]
        header = [f.name() for f in selected_fields]
        if self.geom_check.isChecked():
            header.append("WKT")

        rows = []
        for feat in feats:
            row = []
            for f in selected_fields:
                val = feat.attribute(f.name())
                # Art-Lookup anwenden
                if self.art_check.isChecked() and f.name() == "Artname" and val:
                    de, wiss = art_lookup.get(str(val), ("", ""))
                    # Ersetze leere Felder
                    row.append(val)
                    continue
                if self.art_check.isChecked() and f.name() == "Artname_deutsch" and not val:
                    artname = feat.attribute("Artname")
                    val = art_lookup.get(str(artname or ""), ("", ""))[0] if artname else ""
                if self.art_check.isChecked() and f.name() == "Artname_wiss" and not val:
                    artname = feat.attribute("Artname")
                    val = art_lookup.get(str(artname or ""), ("", ""))[1] if artname else ""
                row.append(_fmt_val(val))
            if self.geom_check.isChecked():
                geom = feat.geometry()
                row.append(geom.asWkt(2) if geom else "")
            rows.append(row)
        return header, rows

    def _export_csv(self, lyr, path, feats, total, art_lookup):
        header, rows = self._rows(lyr, feats, art_lookup)
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh, delimiter=";")
                writer.writerow(header)
                for i, row in enumerate(rows):
                    writer.writerow(row)
                    self.bar.setValue(i + 1)
            self._log(f"✓ CSV: {len(rows)} Zeilen → {path}")
        except Exception as e:
            self._log(f"✗ Fehler: {e}")

    def _export_xlsx(self, lyr, path, feats, total, art_lookup):
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
        except ImportError:
            self._log("⚠ openpyxl nicht installiert → pip install openpyxl")
            self._export_csv(lyr, path.replace(".xlsx", ".csv"), feats, total, art_lookup)
            return

        header, rows = self._rows(lyr, feats, art_lookup)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Fundpunkte"

        # Kopfzeile
        hdr_fill = PatternFill("solid", fgColor="2E7D32")
        hdr_font = Font(bold=True, color="FFFFFF")
        ws.append(header)
        for cell in ws[1]:
            cell.font  = hdr_fill; cell.fill = hdr_fill; cell.font = hdr_font
            cell.alignment = Alignment(horizontal="center")

        for i, row in enumerate(rows):
            ws.append(row)
            self.bar.setValue(i + 1)

        # Spaltenbreiten
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

        ws.freeze_panes = "A2"
        try:
            wb.save(path)
            self._log(f"✓ XLSX: {len(rows)} Zeilen → {path}")
        except Exception as e:
            self._log(f"✗ Fehler: {e}")

    def _export_gpkg(self, lyr, path, feats, total):
        flag = self._resolve_flag_field(lyr)
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName  = "GPKG"
        options.layerName   = "Fundpunkte"
        options.fileEncoding = "UTF-8"
        options.onlySelectedFeatures = self.filter_check.isChecked()

        # Nur die im Dialog angehakten Felder exportieren (wie _rows bei CSV/XLSX);
        # das Steuerfeld wird grundsätzlich nie geschrieben.
        fields = lyr.fields()
        selected_idx = [
            i for i in range(fields.count())
            if fields[i].name() != flag
            and (self.field_checks.get(fields[i].name()) is None
                 or self.field_checks[fields[i].name()].isChecked())
        ]
        options.attributes = selected_idx

        # Nur Features ohne aktives Steuerfeld schreiben. Der Writer liest den
        # Layer direkt, daher temporär per Subset-String filtern.
        err, msg = None, ""
        prev_subset = lyr.subsetString() if flag else None
        try:
            if flag:
                clause = f'"{flag}" IS NULL OR "{flag}" = 0'
                new_subset = (f'({prev_subset}) AND ({clause})'
                              if prev_subset else clause)
                lyr.setSubsetString(new_subset)
            err, msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
                lyr, path, QgsCoordinateTransformContext(), options
            )
        finally:
            if flag:
                lyr.setSubsetString(prev_subset or "")

        if err == QgsVectorFileWriter.WriterError.NoError:
            self._log(f"✓ GPKG: {total} Features → {path}")
        else:
            self._log(f"✗ GPKG-Fehler: {msg}")
        self.bar.setValue(total)
