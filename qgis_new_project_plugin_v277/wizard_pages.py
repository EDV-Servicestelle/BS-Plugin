import os

from qgis.PyQt.QtWidgets import (
    QWizardPage, QLabel, QLineEdit, QPushButton, QFileDialog,
    QVBoxLayout, QHBoxLayout, QFormLayout, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QCheckBox, QAbstractItemView, QProgressBar, QComboBox,
    QSpinBox,
)
from qgis.PyQt.QtCore import QThread, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.gui import QgsProjectionSelectionWidget, QgsMapLayerComboBox
from qgis.core import QgsMapLayerProxyModel

from .fachschale_loader import FachschalenLoader, FachschaleLayerLoader
from .project_finalizer import (
    collect_and_copy_geopackages,
    relink_project_to_local_geopackages,
    QFieldCloudUploader,
)


# ════════════════════════════════════════════════════════════════════════════
# Seite 1 – Projektinfo + Fachschale + Projektvariablen
# ════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
# WizardBuildLog – Sammelt alle Fehler/Tracebacks während des Projektaufbaus
# ═══════════════════════════════════════════════════════════════════════════════

class WizardBuildLog:
    """Singleton-artiger Log-Sammler für den Wizard-Projektaufbau.
    Zeigt am Ende ein Fenster mit allen Fehlern wenn welche aufgetreten sind.
    """
    _entries: list = []

    @classmethod
    def clear(cls):
        cls._entries = []

    @classmethod
    def add(cls, msg: str, level: str = "INFO"):
        import traceback as _tb
        entry = f"[{level}] {msg}"
        cls._entries.append(entry)
        from qgis.core import QgsMessageLog
        lvl = 0 if level == "INFO" else (1 if level == "WARN" else 2)
        QgsMessageLog.logMessage(msg, "NRW Naturschutz", lvl)

    @classmethod
    def add_exception(cls, context: str):
        import traceback as _tb
        tb = _tb.format_exc()
        cls._entries.append(f"[ERROR] {context}:\n{tb}")
        from qgis.core import QgsMessageLog
        QgsMessageLog.logMessage(f"{context}: {tb}", "NRW Naturschutz", 2)

    @classmethod
    def show_if_errors(cls, parent=None):
        """Zeigt Log-Fenster wenn Fehler vorhanden."""
        errors = [e for e in cls._entries if "[ERROR]" in e or "[WARN]" in e]
        if not errors:
            return
        from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QLabel,
                                          QTextEdit, QPushButton)
        from qgis.PyQt.QtGui import QFont
        dlg = QDialog(parent)
        dlg.setWindowTitle("Projektaufbau – Protokoll")
        dlg.setMinimumSize(700, 500)
        lo = QVBoxLayout(dlg)
        lo.addWidget(QLabel(
            f"<b>{len(errors)} Warnung(en)/Fehler</b> während des Projektaufbaus:"))
        log = QTextEdit()
        log.setReadOnly(True)
        log.setFont(QFont("Courier New", 9))
        log.setPlainText("\n\n".join(cls._entries))
        lo.addWidget(log)
        btn = QPushButton("Schließen")
        btn.clicked.connect(dlg.accept)
        lo.addWidget(btn)
        dlg.exec()


class PageProjectInfo(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Projektinformationen")
        self.setSubTitle(
            "Geben Sie Name, Speicherort, Fachschale und Projektvariablen an."
        )
        self._loader = None

        # ── Projektname & Ordner ─────────────────────────────────────────────
        self.name_edit   = QLineEdit()
        self.folder_edit = QLineEdit()
        browse_btn = QPushButton("Durchsuchen …")
        browse_btn.clicked.connect(self._browse)

        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_edit)
        folder_row.addWidget(browse_btn)

        # ── Fachschale ───────────────────────────────────────────────────────
        fach_box = QGroupBox("Fachschale")
        fl = QVBoxLayout()

        # Verbindungszeile mit Labels
        conn_row = QHBoxLayout()
        self.fach_host = QLineEdit("localhost")
        self.fach_host.setPlaceholderText("Host / IP")
        self.fach_host.setMinimumWidth(120)
        self.fach_port = QSpinBox()
        self.fach_port.setRange(1, 65535)
        self.fach_port.setValue(5432)
        self.fach_port.setFixedWidth(70)
        self.fach_db   = QLineEdit(); self.fach_db.setPlaceholderText("Datenbank")
        self.fach_user = QLineEdit(); self.fach_user.setPlaceholderText("Benutzer")
        self.fach_pw   = QLineEdit(); self.fach_pw.setPlaceholderText("Passwort")
        self.fach_pw.setEchoMode(QLineEdit.EchoMode.Password)
        load_btn = QPushButton("Laden")
        load_btn.clicked.connect(self._load_fachschalen)
        for lbl, w in [("Host:", self.fach_host), ("Port:", self.fach_port),
                        ("DB:",   self.fach_db),   ("User:", self.fach_user),
                        ("PW:",   self.fach_pw)]:
            conn_row.addWidget(QLabel(lbl))
            conn_row.addWidget(w)
        conn_row.addWidget(load_btn)

        self.fach_combo = QComboBox()
        self.fach_combo.setEnabled(False)
        self.fach_combo.addItem("— bitte zuerst Verbindung laden —")
        self.fach_combo.currentIndexChanged.connect(self._on_fachschale_changed)

        self.fach_status = QLabel("Noch keine Fachschalen geladen.")
        self.fach_status.setStyleSheet("color: gray; font-size: 11px;")

        # Offline-Button: Fachschalen ohne DB-Verbindung aus lokaler Config laden
        offline_btn = QPushButton("Offline laden (ohne DB)")
        offline_btn.clicked.connect(self._load_offline)

        fl.addLayout(conn_row)
        fl.addWidget(offline_btn)
        fl.addWidget(self.fach_combo)
        fl.addWidget(self.fach_status)
        fach_box.setLayout(fl)

        # ── Projektvariablen ─────────────────────────────────────────────────
        var_box = QGroupBox("Projektvariablen")
        vl = QFormLayout()
        self.kartierer_edit    = QLineEdit()
        self.kartierer_edit.setPlaceholderText("Name des Kartierers …")
        self.institution_combo = QComboBox()
        self.institution_combo.setEditable(True)
        self.institution_combo.addItem("— bitte wählen —", None)
        self._populate_person_combos()
        vl.addRow("Kartierer:",   self.kartierer_edit)
        vl.addRow("Institution:", self.institution_combo)
        var_box.setLayout(vl)
        # Hinweis: Die frühere manuelle Landkreis-Auswahl (erster Versuch eines
        # Grundlagen-Abrufs) wurde entfernt. Verwaltungsgrenzen kommen jetzt
        # über den Grundlagen-Dialog (DVG-Dienste).

        # ── Hauptlayout ──────────────────────────────────────────────────────
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Projektname:"))
        layout.addWidget(self.name_edit)
        layout.addWidget(QLabel("Speicherordner:"))
        layout.addLayout(folder_row)
        layout.addSpacing(8)
        layout.addWidget(fach_box)
        layout.addWidget(var_box)
        self.setLayout(layout)

        self.registerField("projectName*",  self.name_edit)
        self.registerField("projectFolder*",self.folder_edit)
        # ComboBox-Felder: currentText liefert den angezeigten Text
        self.registerField("varKartierer",   self.kartierer_edit)
        self.registerField("varInstitution", self.institution_combo, "currentText")

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _populate_person_combos(self):
        """Befüllt Institution + Karterer.
        Quelle 1: PostGIS gemeinsam.institution / gemeinsam.karterer
        Quelle 2: Fallback auf lokale Referenzlisten.gpkg (adressrollle).
        """
        # Versuche PostGIS-Verbindung (Host/Port aus Fachschalen-Eingabe)
        if self._try_populate_from_postgis():
            return
        self._populate_from_gpkg()

    def _try_populate_from_postgis(self) -> bool:
        """Befüllt Combos aus gemeinsam.institution + gemeinsam.karterer."""
        try:
            import psycopg2
            host = self.fach_host.text().strip()
            port = self.fach_port.value()
            db   = self.fach_db.text().strip()
            user = self.fach_user.text().strip()
            pw   = self.fach_pw.text() if hasattr(self, 'fach_pw') else ""
            if not db:
                return False
            conn = psycopg2.connect(host=host, port=port, dbname=db,
                                    user=user, password=pw, connect_timeout=3)
            cur = conn.cursor()
            # Institutionen
            cur.execute("""
                SELECT kuerzel, name FROM gemeinsam.institution
                ORDER BY kuerzel
            """)
            inst_rows = cur.fetchall()
            # Karterer
            cur.execute("""
                SELECT vorname || ' ' || nachname, email, institution_kuerzel
                FROM gemeinsam.karterer
                WHERE aktiv = TRUE
                ORDER BY nachname, vorname
            """)
            kart_rows = cur.fetchall()
            conn.close()
        except Exception:
            return False

        if not inst_rows:
            return False

        # Institution-Combo befüllen
        for kuerzel, name in inst_rows:
            label = f"{kuerzel} – {name}" if name and kuerzel != name else (name or kuerzel)
            self.institution_combo.addItem(label, kuerzel)

        # Kartierer-Combo befüllen (falls vorhanden)
        if hasattr(self, 'kartierer_combo'):
            for name, email, inst in kart_rows:
                self.kartierer_combo.addItem(name, {"email": email, "institution": inst})

        # Ersten Eintrag vorauswählen
        if self.institution_combo.count() > 1:
            self.institution_combo.setCurrentIndex(1)
        return True

    def _populate_from_gpkg(self):
        """Fallback: lädt Institutionen aus lokaler adressrollle-Tabelle."""
        import sqlite3, os
        gpkg = os.path.join(os.path.dirname(__file__),
                            "data", "biotopbaum", "Referenzlisten.gpkg")
        if not os.path.isfile(gpkg):
            return
        try:
            con = sqlite3.connect(gpkg)
            rows = con.execute("""
                SELECT kurzname, langname FROM adressrollle
                WHERE parentlistitemid = 552172
                ORDER BY kurzname
            """).fetchall()
            con.close()
        except Exception:
            return
        from qgis.PyQt.QtCore import Qt
        for kurzname, langname in rows:
            label = f"{kurzname} – {langname}" if kurzname != langname else langname
            self.institution_combo.addItem(label, kurzname)
        idx = self.institution_combo.findText(
            "Eigene BS", flags=Qt.MatchFlag.MatchContains)
        if idx >= 0:
            self.institution_combo.setCurrentIndex(idx)

    def _conn_params(self) -> dict:
        return {
            "host":     self.fach_host.text().strip(),
            "port":     self.fach_port.value(),
            "dbname":   self.fach_db.text().strip(),
            "user":     self.fach_user.text().strip(),
            "password": self.fach_pw.text(),
        }

    def _load_fachschalen(self):
        self.fach_status.setText("Lade Fachschalen aus Datenbank …")
        self.fach_combo.setEnabled(False)
        wiz = self.wizard()
        if wiz:
            wiz.setProperty("_offlineMode", False)
        self._loader = FachschalenLoader(self._conn_params())
        self._loader.ready.connect(self._populate_combo)
        self._loader.error.connect(
            lambda e: self.fach_status.setText(f"DB-Fehler: {e} – Fallback aktiv.")
        )
        self._loader.start()

    def _load_offline(self):
        """Lädt Fachschalen direkt aus lokaler Konfiguration (ohne DB-Verbindung).
        Setzt _offlineMode=True im Wizard, damit _build_project die
        mitgelieferten GeoPackages statt PostGIS verwendet."""
        from .fachschalen_config import FACHSCHALEN
        wiz = self.wizard()
        if wiz:
            wiz.setProperty("_offlineMode", True)
        self._populate_combo(FACHSCHALEN)
        self.fach_status.setText("Offline-Modus: GeoPackage-Daten werden verwendet.")

    def _populate_combo(self, rows: list):
        self.fach_combo.clear()
        self.fach_combo.addItem("— Fachschale wählen —", None)
        for r in rows:
            self.fach_combo.addItem(r["bezeichnung"], r)
        self.fach_combo.setEnabled(True)
        self.completeChanged.emit()

    def _on_fachschale_changed(self, _index: int):
        fach = self.fach_combo.currentData()
        wiz  = self.wizard()
        if wiz:
            wiz.setProperty("_fachschale",  fach)
            wiz.setProperty("_connParams",  self._conn_params() if fach else None)
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        name_ok   = bool(self.name_edit.text().strip())
        folder_ok = os.path.isdir(self.folder_edit.text().strip())
        fach_ok   = self.fach_combo.currentData() is not None
        return name_ok and folder_ok and fach_ok

    def validatePage(self):
        return self.isComplete()

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Ordner wählen")
        if folder:
            self.folder_edit.setText(folder)


# ════════════════════════════════════════════════════════════════════════════
# Seite 2 – KRS
# ════════════════════════════════════════════════════════════════════════════
class PageCrsExtent(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Koordinatenreferenzsystem")
        self.setSubTitle("Wählen Sie das KRS für das neue Projekt.")

        self.crs_widget = QgsProjectionSelectionWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("KRS:"))
        layout.addWidget(self.crs_widget)
        layout.addStretch()
        self.setLayout(layout)

    def initializePage(self):
        from qgis.core import QgsCoordinateReferenceSystem
        # Standard NRW: UTM Zone 32N
        self.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:25832"))

    def validatePage(self):
        return self.crs_widget.crs().isValid()

    def nextId(self):
        self.wizard().setProperty("_crsAuthId", self.crs_widget.crs().authid())
        return super().nextId()


# ════════════════════════════════════════════════════════════════════════════
# Seite 3 – Untersuchungsgebiet
# ════════════════════════════════════════════════════════════════════════════
class PageUntersuchungsgebiet(QWizardPage):
    """
    Optionale Seite: Ermöglicht den Import eines Untersuchungsgebiets aus
    einer vorhandenen Vektordatei (Shapefile, GPKG, GeoJSON …).
    Wird für alle Fachschalen angeboten; der Wizard überträgt die Geometrie
    beim Projektaufbau in den jeweiligen UG-Layer der Fachschale.
    Seite kann übersprungen werden – UG-Layer bleibt dann leer.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Untersuchungsgebiet")
        self.setSubTitle(
            "Optional: Untersuchungsgebiet aus einer vorhandenen Datei ODER einem\n"
            "vorhandenen Polygon-Layer übernehmen. Wird nichts gewählt, wird kein\n"
            "UG-Layer angelegt. (Eine angegebene Datei hat Vorrang vor dem Layer.)"
        )

        # ── Dateiauswahl ──────────────────────────────────────────────────────
        file_row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("Pfad zur Vektordatei (optional) …")
        self.file_edit.setReadOnly(True)
        browse_btn = QPushButton("Durchsuchen …")
        browse_btn.clicked.connect(self._browse)
        clear_btn = QPushButton("✕")
        clear_btn.setFixedWidth(28)
        clear_btn.clicked.connect(self._clear)
        clear_btn.setToolTip("Auswahl zurücksetzen")
        file_row.addWidget(self.file_edit)
        file_row.addWidget(browse_btn)
        file_row.addWidget(clear_btn)

        # ── ODER: vorhandenen Layer wählen ────────────────────────────────────
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.layer_combo.setAllowEmptyLayer(True)
        self.layer_combo.setCurrentIndex(0)   # standardmäßig „kein Layer"
        self.layer_combo.layerChanged.connect(self._on_layer_changed)

        # ── KENNUNG ───────────────────────────────────────────────────────────
        self.kennung_edit = QLineEdit()
        self.kennung_edit.setPlaceholderText("z. B. UG-2024-001  (wird aus Projektname vorbelegt)")

        # ── Info-Label ────────────────────────────────────────────────────────
        self.info_label = QLabel("Kein Untersuchungsgebiet ausgewählt – es wird kein UG-Layer angelegt.")
        self.info_label.setStyleSheet("color: gray; font-size: 11px;")
        self.info_label.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Quelldatei:"))
        layout.addLayout(file_row)
        layout.addSpacing(4)
        layout.addWidget(QLabel("… oder vorhandenen Polygon-Layer:"))
        layout.addWidget(self.layer_combo)
        layout.addSpacing(8)
        layout.addWidget(QLabel("KENNUNG:"))
        layout.addWidget(self.kennung_edit)
        layout.addSpacing(8)
        layout.addWidget(self.info_label)
        layout.addStretch()
        self.setLayout(layout)

        self.registerField("ugSourcePath",  self.file_edit)
        self.registerField("ugKennung",     self.kennung_edit)

    def initializePage(self):
        # Vorbelegen: KENNUNG aus Projektname
        name = self.field("projectName") or ""
        if name and not self.kennung_edit.text().strip():
            self.kennung_edit.setText(name)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Vektordatei wählen",
            "",
            "Vektordateien (*.shp *.gpkg *.geojson *.json *.kml *.gml *.sqlite);;Alle Dateien (*)",
        )
        if not path:
            return
        uri = self._resolve_sublayer(path)
        if uri is None:   # Auswahl abgebrochen
            return
        self.file_edit.setText(uri)
        self._refresh_info()

    def _resolve_sublayer(self, path):
        """
        Enthält die Datei mehrere (Polygon-)Layer, wird abgefragt, welcher als
        Untersuchungsgebiet dienen soll. Rückgabe: OGR-URI (ggf. mit
        '|layername=…'), bei genau einem Layer der Pfad selbst, bei Abbruch None.
        """
        candidates = []
        try:
            from qgis.core import QgsProviderRegistry, Qgis, QgsWkbTypes
            reg = QgsProviderRegistry.instance()
            try:
                subs = reg.querySublayers(
                    path, Qgis.SublayerQueryFlag.ResolveGeometryType)
            except Exception:
                subs = reg.querySublayers(path)
            allv = list(subs)
            polys = []
            for s in allv:
                try:
                    if (QgsWkbTypes.geometryType(s.wkbType())
                            == QgsWkbTypes.GeometryType.PolygonGeometry):
                        polys.append(s)
                except Exception:
                    pass
            candidates = polys if polys else allv
        except Exception:
            candidates = []

        if len(candidates) <= 1:
            return candidates[0].uri() if len(candidates) == 1 else path

        from qgis.PyQt.QtWidgets import QInputDialog
        names = [s.name() for s in candidates]
        name, ok = QInputDialog.getItem(
            self, "Layer wählen",
            "Die Datei enthält mehrere Layer.\n"
            "Welcher soll als Untersuchungsgebiet verwendet werden?",
            names, 0, False)
        if not ok:
            return None
        return candidates[names.index(name)].uri()

    def _clear(self):
        self.file_edit.clear()
        self._refresh_info()

    def _on_layer_changed(self, _lyr=None):
        self._refresh_info()

    def _refresh_info(self):
        raw = self.file_edit.text().strip()
        lyr = self.layer_combo.currentLayer() if hasattr(self, "layer_combo") else None
        if raw:
            base  = os.path.basename(raw.split("|")[0])
            lname = ""
            for part in raw.split("|")[1:]:
                if part.startswith("layername="):
                    lname = " → " + part.split("=", 1)[1]
            self.info_label.setText(f"Wird übernommen (Datei): {base}{lname}")
            self.info_label.setStyleSheet("color: green; font-size: 11px;")
        elif lyr is not None:
            self.info_label.setText(f"Wird übernommen (Layer): {lyr.name()}")
            self.info_label.setStyleSheet("color: green; font-size: 11px;")
        else:
            self.info_label.setText(
                "Kein Untersuchungsgebiet ausgewählt – es wird kein UG-Layer angelegt.")
            self.info_label.setStyleSheet("color: gray; font-size: 11px;")

    def ug_source(self):
        """Liefert die UG-Quelle:
        ('file', pfad, kennung) | ('layer', layer, kennung) | (None, None, kennung).
        Eine angegebene Datei hat Vorrang vor dem gewählten Layer."""
        kennung = self.kennung_edit.text().strip()
        path = self.file_edit.text().strip()
        if path:
            return "file", path, kennung
        lyr = self.layer_combo.currentLayer() if hasattr(self, "layer_combo") else None
        if lyr is not None:
            return "layer", lyr, kennung
        return None, None, kennung

    def isComplete(self):
        return True   # Seite ist immer gültig (Quelle ist optional)


# ════════════════════════════════════════════════════════════════════════════
# Seite 3 – Layer der Fachschale + Referenzlisten
# ════════════════════════════════════════════════════════════════════════════
class PagePostGISLayers(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Layer der Fachschale")
        self.setSubTitle(
            "Layer und Referenzlisten werden nach der gewählten Fachschale gefiltert."
        )
        self._loader     = None
        self._layer_data = []

        # ── Optionen ─────────────────────────────────────────────────────────
        opt_box = QGroupBox("Optionen")
        ol = QHBoxLayout()
        self.apply_style_cb = QCheckBox("Style aus DB anwenden (layer_styles)")
        self.apply_style_cb.setChecked(True)
        self.wms_cb = QCheckBox("NRW-Hintergrundkarten (WMS/WMTS) einbinden")
        self.wms_cb.setChecked(True)
        ol.addWidget(self.apply_style_cb)
        ol.addWidget(self.wms_cb)
        ol.addStretch()
        opt_box.setLayout(ol)

        # ── Tabelle ──────────────────────────────────────────────────────────
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["", "Schema", "Tabelle", "Typ", "Kategorie", "ValueRelations"]
        )
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        btn_row = QHBoxLayout()
        sel_all  = QPushButton("Alle auswählen")
        sel_none = QPushButton("Alle abwählen")
        sel_all.clicked.connect(lambda: self._set_all(True))
        sel_none.clicked.connect(lambda: self._set_all(False))
        btn_row.addWidget(sel_all)
        btn_row.addWidget(sel_none)
        btn_row.addStretch()

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray; font-size: 11px;")

        layout = QVBoxLayout()
        layout.addWidget(opt_box)
        layout.addLayout(btn_row)
        layout.addWidget(self.table)
        layout.addWidget(self.status_label)
        self.setLayout(layout)

    def initializePage(self):
        wiz         = self.wizard()
        fachschale  = wiz.property("_fachschale")
        conn_params = wiz.property("_connParams")

        if not fachschale:
            self.status_label.setText("Keine Fachschale gewählt.")
            return

        self.status_label.setText(
            f"Lade Layer für '{fachschale['bezeichnung']}' …"
        )
        self.table.setRowCount(0)
        self._layer_data = []

        self._loader = FachschaleLayerLoader(
            conn_params or {}, fachschale
        )
        self._loader.ready.connect(self._populate_table)
        self._loader.error.connect(
            lambda e: self.status_label.setText(f"Fehler: {e}")
        )
        self._loader.start()

    def _populate_table(self, geo_layers: list, ref_tables: list):
        all_rows = geo_layers + ref_tables
        self._layer_data = all_rows
        self.table.setRowCount(len(all_rows))

        for i, r in enumerate(all_rows):
            cb = QCheckBox()
            cb.setChecked(True)
            self.table.setCellWidget(i, 0, cb)
            self.table.setItem(i, 1, QTableWidgetItem(r["schema"]))
            self.table.setItem(i, 2, QTableWidgetItem(r["table"]))
            self.table.setItem(i, 3, QTableWidgetItem(r["geom_type"]))

            kat_item = QTableWidgetItem(
                "Referenzliste" if r["is_ref"] else "Fachschale"
            )
            kat_item.setForeground(
                QColor("#185FA5") if r["is_ref"] else QColor("#3B6D11")
            )
            self.table.setItem(i, 4, kat_item)

            # ValueRelations-Spalte
            vr = r.get("value_relations", {})
            vr_text = ", ".join(
                f"{f}→{c['ref_table']}" for f, c in vr.items()
            ) if vr else "–"
            vr_item = QTableWidgetItem(vr_text)
            if vr:
                vr_item.setForeground(QColor("#854F0B"))
            self.table.setItem(i, 5, vr_item)

        n_geo = len(geo_layers)
        n_ref = len(ref_tables)
        self.status_label.setText(
            f"{n_geo} Fachschalen-Layer + {n_ref} Referenzlisten geladen."
        )

    def _set_all(self, checked: bool):
        for row in range(self.table.rowCount()):
            cb = self.table.cellWidget(row, 0)
            if cb:
                cb.setChecked(checked)

    def selected_layers(self) -> list:
        return [
            r for i, r in enumerate(self._layer_data)
            if (cb := self.table.cellWidget(i, 0)) and cb.isChecked()
        ]

    def apply_style(self) -> bool:
        return self.apply_style_cb.isChecked()

    def load_wms(self) -> bool:
        return self.wms_cb.isChecked()

    def _conn_params(self) -> dict:
        return self.wizard().property("_connParams") or {}


# ════════════════════════════════════════════════════════════════════════════
# Seite 4 – Zusammenfassung
# ════════════════════════════════════════════════════════════════════════════
class PageSummary(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Zusammenfassung")
        self.setSubTitle("Überprüfen Sie Ihre Eingaben vor dem Erstellen.")

        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        layout = QVBoxLayout()
        layout.addWidget(self.summary)
        self.setLayout(layout)

    def initializePage(self):
        wiz           = self.wizard()
        name          = self.field("projectName")
        folder        = self.field("projectFolder")
        crs           = wiz.property("_crsAuthId") or "–"
        kartierer   = self.field("varKartierer") or "–"
        institution = self.field("varInstitution") or "–"
        # Nur den kurzname-Teil anzeigen
        kartierer   = kartierer.split(" – ")[0] if " – " in kartierer else kartierer
        institution = institution.split(" – ")[0] if " – " in institution else institution
        fach          = wiz.property("_fachschale")
        fach_name     = fach["bezeichnung"] if fach else "–"
        pg_page       = wiz.page(wiz.PAGE_POSTGIS)
        layers        = pg_page.selected_layers()
        apply_s       = pg_page.apply_style()
        load_wms      = pg_page.load_wms()

        geo_layers = [r for r in layers if not r["is_ref"]]
        ref_tables = [r for r in layers if r["is_ref"]]

        def fmt(rows):
            lines = []
            for r in rows:
                vr = r.get("value_relations", {})
                vr_info = f" [{len(vr)} ValueRelations]" if vr else ""
                lines.append(
                    f"  • {r['schema']}.{r['table']} [{r['geom_type']}]{vr_info}"
                )
            return "\n".join(lines) or "  (keine ausgewählt)"

        self.summary.setPlainText(
            f"Projektname      : {name}\n"
            f"Speicherpfad     : {folder}\n"
            f"KRS              : {crs}\n"
            f"Fachschale       : {fach_name}\n"
            f"\n"
            f"Projektvariablen:\n"
            f"  Kartierer      : {kartierer}\n"
            f"  Institution    : {institution}\n"
            f"\n"
            f"Fachschalen-Layer ({len(geo_layers)}):\n{fmt(geo_layers)}\n"
            f"\n"
            f"Referenzlisten ({len(ref_tables)}):\n{fmt(ref_tables)}\n"
            f"\n"
            f"Style aus DB     : {'Ja' if apply_s else 'Nein'}\n"
            f"WMS-Dienste      : {'Ja (4 NRW-Dienste)' if load_wms else 'Nein'}\n"
        )



# ════════════════════════════════════════════════════════════════════════════
# Seite 5 – GeoPackage-Export & QFieldCloud-Upload
# ════════════════════════════════════════════════════════════════════════════
class PageExportAndUpload(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._project_built = False
        self.setTitle("Export & QFieldCloud-Upload")
        self.setSubTitle(
            "Layer als GeoPackage sichern, Projekt speichern und "
            "zu QFieldCloud übertragen."
        )
        self.setFinalPage(True)
        self._uploader = None

        # ── Projektordner ────────────────────────────────────────────────────
        gpkg_box = QGroupBox("Projektordner")
        gl = QHBoxLayout()
        self.gpkg_edit = QLineEdit()
        self.gpkg_edit.setPlaceholderText("Ordner für Projekt + GeoPackages …")
        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(32)
        browse_btn.clicked.connect(self._browse_gpkg)
        gl.addWidget(self.gpkg_edit)
        gl.addWidget(browse_btn)
        gpkg_box.setLayout(gl)

        # ── QFieldCloud ──────────────────────────────────────────────────────
        cloud_box = QGroupBox("QFieldCloud")
        cl = QVBoxLayout()
        self.cloud_cb = QCheckBox("Zu QFieldCloud hochladen")
        self.cloud_cb.setChecked(True)
        self.cloud_cb.toggled.connect(self._toggle_cloud)

        row1 = QHBoxLayout()
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Benutzername")
        row1.addWidget(QLabel("Benutzer:"))
        row1.addWidget(self.user_edit)

        row2 = QHBoxLayout()
        self.pw_edit = QLineEdit()
        self.pw_edit.setPlaceholderText("Passwort")
        self.pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        row2.addWidget(QLabel("Passwort:"))
        row2.addWidget(self.pw_edit)

        row3 = QHBoxLayout()
        self.org_edit = QLineEdit()
        self.org_edit.setPlaceholderText("Organisation (leer = persönliches Konto)")
        row3.addWidget(QLabel("Org.:"))
        row3.addWidget(self.org_edit)

        cl.addWidget(self.cloud_cb)
        cl.addLayout(row1)
        cl.addLayout(row2)
        cl.addLayout(row3)
        cloud_box.setLayout(cl)

        # ── Projekt nach Abschluss oeffnen ──────────────────────────────────
        qf_box = QGroupBox("Nach Abschluss")
        qf_lo  = QVBoxLayout()

        self.open_qgis_cb = QCheckBox(
            "Projekt in QGIS öffnen (gespeicherte Fassung neu laden)")
        self.open_qgis_cb.setChecked(True)
        self.open_qgis_cb.setToolTip(
            "Lädt das soeben gespeicherte Projekt aus dem Projektordner neu. "
            "Damit arbeitet QGIS auf genau der Fassung mit relativen Pfaden, "
            "die auch zu QFieldCloud hochgeladen wurde.")
        qf_lo.addWidget(self.open_qgis_cb)

        qf_box.setLayout(qf_lo)

        # ── Fortschritt & Log ────────────────────────────────────────────────
        self.run_btn  = QPushButton("Export & Upload starten")
        self.run_btn.clicked.connect(self._run)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)

        layout = QVBoxLayout()
        layout.addWidget(gpkg_box)
        layout.addWidget(cloud_box)
        layout.addWidget(qf_box)
        layout.addWidget(self.run_btn)
        layout.addWidget(self.progress)
        layout.addWidget(self.log)
        self.setLayout(layout)

        self.registerField("gpkgPath*", self.gpkg_edit)


    def initializePage(self):
        """Exportordner vorbelegen. Build passiert via _run()."""
        folder = self.field("projectFolder")
        if folder:
            self.gpkg_edit.setText(folder)

    def _browse_gpkg(self):
        folder = QFileDialog.getExistingDirectory(self, "Projektordner wählen")
        if folder:
            self.gpkg_edit.setText(folder)

    def _toggle_cloud(self, checked: bool):
        self.user_edit.setEnabled(checked)
        self.pw_edit.setEnabled(checked)
        self.org_edit.setEnabled(checked)

    def _log(self, msg: str):
        self.log.append(msg)

    def _run(self):
        self.run_btn.setEnabled(False)
        self.log.clear()
        self.progress.setValue(0)
        self._cloud_url = ""      # URL des vorherigen Laufs verwerfen

        from qgis.core import QgsProject

        dest_dir     = self.gpkg_edit.text().strip()
        proj_name    = self.field("projectName")
        project_path = os.path.normpath(os.path.join(dest_dir, f"{proj_name}.qgz"))

        if not dest_dir or not os.path.isdir(dest_dir):
            self._log("FEHLER: Bitte gültigen Projektordner wählen.")
            self.run_btn.setEnabled(True)
            return

        try:
            # 1. GPKGs direkt aus Fachschalen-Config kopieren
            #    (QgsProject ist zu diesem Zeitpunkt noch nicht gebaut –
            #     _build_project läuft erst bei accepted())
            import shutil as _shutil
            from .new_project_wizard import _PLUGIN_DIR as _PD
            wiz_ref   = self.wizard()
            fach_ref  = wiz_ref.property("_fachschale") if wiz_ref else None
            gpkg_data = (fach_ref or {}).get("gpkg_data", {})

            self._log("Kopiere GeoPackages in Projektordner …")
            path_map  = {}   # {abs_src: abs_dst}
            for cat in ["geo_layers", "ref_layers", "border_layers"]:
                for entry in gpkg_data.get(cat, []):
                    src = os.path.normpath(os.path.join(_PD, entry["gpkg"]))
                    if not os.path.isfile(src) or src in path_map:
                        continue
                    dst = os.path.normpath(os.path.join(dest_dir, os.path.basename(src)))
                    _shutil.copy2(src, dst)
                    path_map[src] = dst
                    self._log(f"  ✓ {os.path.basename(src)}")
            self._log(f"  {len(path_map)} GPKG(s) kopiert.")
            self.progress.setValue(40)

            # 2. Projekt aus Plugin-GPKGs aufbauen (Offline-Modus erzwingen)
            self._log("Baue QGIS-Projekt (Offline-Modus) …")
            if wiz_ref:
                wiz_ref.setProperty("_offlineMode", True)   # GPKGs statt PostGIS
                wiz_ref._build_project()
            project = QgsProject.instance()
            self.progress.setValue(55)

            # 3. Projekt mit lokalen Pfaden speichern
            self._log("Speichere QGIS-Projekt …")
            try:
                from qgis.core import Qgis
                project.setHomePath(dest_dir)
                project.setFilePathStorage(Qgis.FilePathType.Relative)
            except Exception:
                WizardBuildLog.add_exception("relink_layers")
            relink_project_to_local_geopackages(project, path_map, project_path)
            self._projekt_pfad = project_path      # fuer das Oeffnen in QField
            self._log(f"  Projekt gespeichert: {project_path}")
            self.progress.setValue(65)

            # 3. QField-Plugin-Dateien in Projektordner kopieren
            import shutil as _shutil
            wiz = self.wizard()
            fach = wiz.property("_fachschale") if wiz else None
            fach_code = (fach or {}).get("code", "")
            _PLUGIN_MAP = {
                "fundpunkte_tiere": "qfield_plugins/fundpunkte",
                "brutvogel":        "qfield_plugins/brutvogel",
            }
            plugin_files = []
            rel_dir = _PLUGIN_MAP.get(fach_code)
            if rel_dir:
                from .qfield_project_dialog import _PLUGIN_DIR as _PD
                src_dir = os.path.join(_PD, rel_dir)
                if os.path.isdir(src_dir):
                    for fname in os.listdir(src_dir):
                        src = os.path.join(src_dir, fname)
                        # main.qml → <projektname>.qml
                        dst_name = f"{proj_name}.qml" if fname == "main.qml" else fname
                        dst_path = os.path.join(dest_dir, dst_name)
                        _shutil.copy2(src, dst_path)
                        plugin_files.append(dst_path)
                        self._log(f"  ✓ Plugin: {dst_name}")
            self.progress.setValue(70)

            if self.cloud_cb.isChecked():
                username = self.user_edit.text().strip()
                password = self.pw_edit.text()
                if not username or not password:
                    self._log("  FEHLER: Benutzername und Passwort erforderlich.")
                    self.run_btn.setEnabled(True)
                    return

                self._log("Übertrage zu QFieldCloud …")
                # Projekt + GPKGs + Plugin-Dateien hochladen
                upload_files = [project_path] + list(path_map.values()) + plugin_files
                # UG-GeoPackage (vom Wizard erzeugt) mit hochladen, sonst fehlt
                # der Untersuchungsgebiet-Layer auf dem Gerät.
                ug_gpkg = wiz_ref.property("_ugGpkgPath") if wiz_ref else None
                if ug_gpkg and os.path.isfile(ug_gpkg) and ug_gpkg not in upload_files:
                    upload_files.append(ug_gpkg)
                    self._log(f"  ✓ UG: {os.path.basename(ug_gpkg)}")

                self._pruefe_nicht_paketierbare_layer(project)
                self._uploader = QFieldCloudUploader(
                    username      = username,
                    password      = password,
                    project_name  = proj_name,
                    project_path  = project_path,
                    upload_files  = upload_files,
                    organization  = self.org_edit.text().strip(),
                )
                self._uploader.progress.connect(self._on_upload_progress)
                self._uploader.finished_ok.connect(self._on_upload_done)
                self._uploader.error.connect(self._on_upload_error)
                self._uploader.start()
            else:
                self.progress.setValue(100)
                self._log("Fertig. (Kein Cloud-Upload gewählt)")
                self.run_btn.setEnabled(True)
                self._oeffne_in_qgis()

        except Exception as exc:
            import traceback
            self._log(f"FEHLER: {exc}")
            self._log(traceback.format_exc())
            self.run_btn.setEnabled(True)

    def _pruefe_nicht_paketierbare_layer(self, project):
        """
        Meldet Layer, die nicht als Datei mitgehen koennen.

        Uebernommen werden nur GeoPackage-Vektorlayer. WMS/WMTS-Hintergrund-
        karten und direkt eingebundene PostGIS-Layer bleiben Online-Quellen und
        sind im Gelaende ohne Internet- bzw. DB-Verbindung nicht verfuegbar.
        """
        from qgis.core import QgsVectorLayer
        online, db = [], []
        for lyr in project.mapLayers().values():
            provider = ""
            try:
                provider = (lyr.dataProvider().name() or "").lower()
            except Exception:
                continue
            if provider in ("wms", "wcs", "xyz", "arcgismapserver"):
                online.append(lyr.name())
            elif provider == "postgres":
                db.append(lyr.name())
            elif isinstance(lyr, QgsVectorLayer) and provider == "wfs":
                online.append(lyr.name())

        if online:
            self._log(f"  ⚠ {len(online)} Online-Layer bleiben Online-Quellen "
                      f"(kein Offline-Betrieb): {', '.join(online[:6])}"
                      + (" …" if len(online) > 6 else ""))
        if db:
            self._log(f"  ⚠ {len(db)} PostGIS-Layer werden NICHT paketiert und "
                      f"fehlen auf dem Gerät: {', '.join(db[:6])}"
                      + (" …" if len(db) > 6 else ""))
        if not online and not db:
            self._log("  ✓ Alle Layer liegen als GeoPackage vor (offline-fähig).")

    def _on_upload_progress(self, pct: int, msg: str):
        self.progress.setValue(65 + int(pct * 0.35))
        self._log(f"  {msg}")

    def _on_upload_done(self, url: str):
        self._log("Upload abgeschlossen.")
        self._log(f"  Cloud-URL: {url}")
        self.progress.setValue(100)
        self.run_btn.setEnabled(True)
        self._cloud_url = url
        from qgis.utils import iface
        iface.messageBar().pushSuccess("QFieldCloud", f"Projekt verfügbar: {url}")

        # Angelegtes Cloud-Projekt nach Abschluss in QGIS oeffnen
        self._oeffne_in_qgis()

    # ── Projekt in QGIS oeffnen ─────────────────────────────────────────────
    def _oeffne_in_qgis(self):
        """
        Laedt das gespeicherte Projekt in QGIS neu.

        Waehrend des Laufs arbeitet der Wizard auf QgsProject.instance(); die
        Layerquellen werden erst beim Speichern auf die kopierten GeoPackages
        und auf relative Pfade umgehaengt. Durch das erneute Laden aus dem
        Projektordner arbeitet QGIS danach auf genau der Fassung, die auch zu
        QFieldCloud hochgeladen wurde - nicht auf dem Zwischenstand im
        Arbeitsspeicher.
        """
        if not self.open_qgis_cb.isChecked():
            return
        projekt = getattr(self, "_projekt_pfad", None)
        if not projekt or not os.path.isfile(projekt):
            self._log("  ⚠ QGIS: Projektdatei nicht gefunden – nicht geöffnet.")
            return
        try:
            from qgis.PyQt.QtCore import QTimer
            from qgis.utils import iface

            def _laden():
                try:
                    iface.addProject(projekt)
                    self._log(f"  ✓ Projekt in QGIS geöffnet: "
                              f"{os.path.basename(projekt)}")
                except Exception as exc:
                    self._log(f"  ⚠ Projekt konnte in QGIS nicht geöffnet "
                              f"werden: {exc}")

            # Verzoegert starten, damit der laufende Signalaufruf und der
            # Dialog zuerst abgearbeitet werden - ein Projektwechsel mitten
            # im Signal kann QGIS sonst zum Absturz bringen.
            QTimer.singleShot(0, _laden)
        except Exception as exc:
            self._log(f"  ⚠ Projekt konnte in QGIS nicht geöffnet werden: {exc}")

    def _on_upload_error(self, msg: str):
        self._log(f"Upload-Fehler: {msg}")
        self.run_btn.setEnabled(True)


# ═══════════════════════════════════════════════════════════════════════════════
# PageGrundlagen – Grundlagendaten & Grundlagen-DB-Verbindung
# ═══════════════════════════════════════════════════════════════════════════════

class PageGrundlagen(QWizardPage):
    """
    Wizard-Seite für Grundlagendaten:
    - Verbindungsparameter der Grundlagen-DB (nrw_grundlagen)
    - Auswahl welche Dienste geladen werden (NSG, LSG, FFH, ATKIS …)
    - Fallback auf Live-WFS wenn keine DB konfiguriert
    """

    DIENSTE_DEFAULT = {
        "nsg":                   ("Naturschutzgebiete (NSG)",          True),
        "lsg":                   ("Landschaftsschutzgebiete (LSG)",    True),
        "ffh":                   ("FFH-Gebiete",                       True),
        "vsg":                   ("Vogelschutzgebiete (VSG)",          False),
        "ffh_lrt":               ("FFH-Lebensraumtypen",               False),
        "atkis_gewaesserachse":  ("Gewässerachsen (ATKIS)",            True),
        "atkis_gewaesser_fliessend": ("Fließgewässer (ATKIS)",         True),
        "atkis_gewaesser_stehend":   ("Stehende Gewässer (ATKIS)",     False),
        "atkis_wald":            ("Wald (ATKIS)",                      True),
        "atkis_gehoelz":         ("Gehölze (ATKIS)",                   False),
        "atkis_moor":            ("Moore (ATKIS)",                     False),
        "atkis_heide":           ("Heiden (ATKIS)",                    False),
        "atkis_landwirtschaft":  ("Landwirtschaft (ATKIS)",            False),
        # ATKIS Objektgruppe Siedlung (tatsächliche Nutzung)
        "atkis_wohnbau":           ("Wohnbaufläche",               False),
        "atkis_industrie":         ("Industrie / Gewerbe",        False),
        "atkis_gemischt":          ("Gemischte Nutzung",          False),
        "atkis_besondere_nutzung": ("Besondere funkt. Prägung",   False),
        "atkis_sport_freizeit":    ("Sport / Freizeit / Erholung", False),
        "atkis_friedhof":          ("Friedhof",                   False),
        # Verwaltungsgrenzen (DVG1, WFS) – auch bei konfigurierter DB über WFS
        "dvg1_krs":              ("Kreise / kreisfreie Städte (DVG1)",  False),
        "dvg1_gem":              ("Gemeinden (DVG1)",                   False),
        "dvg1_rbz":              ("Regierungsbezirke (DVG1)",           False),
        "dvg1_lan":              ("Land NRW (DVG1)",                    False),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Grundlagendaten")
        self.setSubTitle(
            "Wählen Sie Quellen und Dienste für die Grundlagendaten des Projekts."
        )
        self._build_ui()
        self._load_saved_settings()

    def _build_ui(self):
        lo = QVBoxLayout(self)

        # ── Quelle + DB-Verbindung nebeneinander (spart vertikalen Platz) ────
        top_lo = QHBoxLayout()

        src_grp = QGroupBox("Datenquelle")
        src_lo  = QVBoxLayout(src_grp)
        self.rb_db   = QCheckBox("Grundlagen-DB (PostGIS) – schnell, offline-fähig")
        self.rb_wfs  = QCheckBox("Live-WFS/OGC-API (Fallback wenn keine DB)")
        self.rb_db.setChecked(True)
        self.rb_wfs.setChecked(True)
        src_lo.addWidget(self.rb_db)
        src_lo.addWidget(self.rb_wfs)
        src_lo.addStretch(1)
        top_lo.addWidget(src_grp, 1)

        # ── Grundlagen-DB Verbindung ────────────────────────────────────────
        self.db_grp = QGroupBox("Grundlagen-DB Verbindung (nrw_grundlagen)")
        db_fl = QFormLayout(self.db_grp)
        self.gdb_host = QLineEdit("localhost")
        self.gdb_port = QSpinBox(); self.gdb_port.setRange(1, 65535); self.gdb_port.setValue(5432)
        self.gdb_db   = QLineEdit("nrw_grundlagen")
        self.gdb_user = QLineEdit("postgres")
        self.gdb_pw   = QLineEdit(); self.gdb_pw.setEchoMode(QLineEdit.Password)
        db_fl.addRow("Host:",      self.gdb_host)
        db_fl.addRow("Port:",      self.gdb_port)
        db_fl.addRow("Datenbank:", self.gdb_db)
        db_fl.addRow("Benutzer:",  self.gdb_user)
        db_fl.addRow("Passwort:",  self.gdb_pw)
        btn_lo = QHBoxLayout()
        test_btn = QPushButton("Verbindung testen")
        test_btn.clicked.connect(self._test_connection)
        save_btn = QPushButton("Speichern")
        save_btn.clicked.connect(self._save_settings)
        btn_lo.addWidget(test_btn); btn_lo.addWidget(save_btn)
        db_fl.addRow("", btn_lo)
        self.db_status = QLabel("")
        self.db_status.setStyleSheet("font-size: 11px;")
        db_fl.addRow("", self.db_status)
        top_lo.addWidget(self.db_grp, 1)
        self.rb_db.toggled.connect(self.db_grp.setEnabled)

        lo.addLayout(top_lo)

        # ── Dienste in drei Spalten (passt ohne Scrollen auf 24")  ───────────
        dienste_grp = QGroupBox("Zu ladende Dienste")
        cols_lo = QHBoxLayout(dienste_grp)
        self._dienst_cbs = {}

        def _add_column(title, keys):
            col = QVBoxLayout()
            lbl = QLabel(f"<b>{title}</b>")
            col.addWidget(lbl)
            for key in keys:
                label, default = self.DIENSTE_DEFAULT[key]
                cb = QCheckBox(label)
                cb.setChecked(default)
                col.addWidget(cb)
                self._dienst_cbs[key] = cb
            col.addStretch(1)
            cols_lo.addLayout(col, 1)

        schutz     = ["nsg", "lsg", "ffh", "vsg", "ffh_lrt"]
        siedlung   = ["atkis_wohnbau", "atkis_industrie", "atkis_gemischt",
                      "atkis_besondere_nutzung", "atkis_sport_freizeit",
                      "atkis_friedhof"]
        verwaltung = ["dvg1_krs", "dvg1_gem", "dvg1_rbz", "dvg1_lan"]
        atkis      = [k for k in self.DIENSTE_DEFAULT
                      if k not in schutz and k not in verwaltung
                      and k not in siedlung]

        _add_column("Schutzgebiete", schutz)
        _add_column("ATKIS Grundlagendaten", atkis)
        _add_column("Siedlung (ATKIS)", siedlung)
        _add_column("Verwaltungsgrenzen (DVG1)", verwaltung)

        lo.addWidget(dienste_grp)

        # Felder registrieren
        self.registerField("grundlagenHost",  self.gdb_host)
        self.registerField("grundlagenPort",  self.gdb_port, "value")
        self.registerField("grundlagenDb",    self.gdb_db)
        self.registerField("grundlagenUser",  self.gdb_user)
        self.registerField("grundlagenPw",    self.gdb_pw)
        self.registerField("grundlagenUseDb", self.rb_db)

    def _load_saved_settings(self):
        """Gespeicherte Verbindungsparameter aus QgsSettings laden."""
        try:
            from qgis.core import QgsSettings
            s = QgsSettings()
            host = s.value("naturschutz/grundlagen_host", "")
            if host:
                self.gdb_host.setText(host)
                self.gdb_port.setValue(int(s.value("naturschutz/grundlagen_port", 5432)))
                self.gdb_db.setText(s.value("naturschutz/grundlagen_db", "nrw_grundlagen"))
                self.gdb_user.setText(s.value("naturschutz/grundlagen_user", "postgres"))
                self.gdb_pw.setText(s.value("naturschutz/grundlagen_pw", ""))
                self.db_status.setText("✓ Gespeicherte Verbindung geladen")
                self.db_status.setStyleSheet("color: green; font-size: 11px;")
        except Exception:
            pass

    def _test_connection(self):
        try:
            import psycopg2
            con = psycopg2.connect(
                host=self.gdb_host.text(), port=self.gdb_port.value(),
                dbname=self.gdb_db.text(), user=self.gdb_user.text(),
                password=self.gdb_pw.text(), connect_timeout=4)
            cur = con.cursor()
            try:
                cur.execute("SELECT COUNT(*) FROM public.grundlagen_index")
                n = cur.fetchone()[0]
                self.db_status.setText(f"✓ Verbunden – {n} Dienste im Index")
                self.db_status.setStyleSheet("color: green; font-size: 11px;")
            except Exception:
                self.db_status.setText("✓ Verbunden (Index noch nicht angelegt)")
                self.db_status.setStyleSheet("color: orange; font-size: 11px;")
            con.close()
        except ImportError:
            self.db_status.setText("⚠ psycopg2 nicht verfügbar")
            self.db_status.setStyleSheet("color: orange; font-size: 11px;")
        except Exception as e:
            self.db_status.setText(f"✗ {str(e)[:60]}")
            self.db_status.setStyleSheet("color: red; font-size: 11px;")

    def _save_settings(self):
        try:
            from qgis.core import QgsSettings
            s = QgsSettings()
            s.setValue("naturschutz/grundlagen_host", self.gdb_host.text())
            s.setValue("naturschutz/grundlagen_port", self.gdb_port.value())
            s.setValue("naturschutz/grundlagen_db",   self.gdb_db.text())
            s.setValue("naturschutz/grundlagen_user",  self.gdb_user.text())
            s.setValue("naturschutz/grundlagen_pw",    self.gdb_pw.text())
            self.db_status.setText("✓ Gespeichert")
            self.db_status.setStyleSheet("color: green; font-size: 11px;")
        except Exception as e:
            self.db_status.setText(f"✗ {e}")

    def selected_dienste(self) -> list:
        """Gibt Liste der ausgewählten Dienst-Keys zurück."""
        return [k for k, cb in self._dienst_cbs.items() if cb.isChecked()]

    def use_db(self) -> bool:
        return self.rb_db.isChecked()

    def conn_params(self) -> dict | None:
        if not self.rb_db.isChecked():
            return None
        return {
            "host":     self.gdb_host.text().strip(),
            "port":     self.gdb_port.value(),
            "dbname":   self.gdb_db.text().strip(),
            "user":     self.gdb_user.text().strip(),
            "password": self.gdb_pw.text(),
        }
