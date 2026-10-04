"""
import_dialog.py – FundpunkteImportDialog (5-Tab-Dialog)
====================================================
Reine UI-Schicht.
Algorithmen:  core/import_core.py
Worker:       workers/import_worker.py

Tabs:
  1 – Quelle        (Datei laden, Artname-Feld, Suchmodus)
  2 – Feldmapping   (Quell- ↔ Zielfeld; Kennung/Eingabedatum automatisch)
  3 – Feldwerte     (Institution, Status, Stadium, Geschlecht)
  4 – Artnamen      (Scan, Debug-CSV)
  5 – Import        (Validierung, Import-Log)
"""
import os

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QPushButton, QGroupBox, QDialogButtonBox,
    QProgressBar, QTextEdit, QSpinBox, QDoubleSpinBox,
    QFileDialog, QLineEdit, QCheckBox, QComboBox,
    QTabWidget, QWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy, QScrollArea, QFrame,
    QCompleter, QAbstractItemView, QMessageBox,
)
from qgis.PyQt.QtCore import Qt, QSortFilterProxyModel
from qgis.PyQt.QtGui import QColor, QBrush

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature,
    QgsCoordinateReferenceSystem, QgsWkbTypes,
)

try:
    from qgis_new_project_plugin.core.import_core import (
        AUTO_FIELDS, GEO_FIELDS, DATE_FIELDS, SYSTEM_FIELDS,
        UUID_FIELDS, NOW_FIELDS, PROTECTED_FIELDS,
        COLOR_AUTO, COLOR_GEO, COLOR_DATE, COLOR_MAP, COLOR_UUID,
        _REF_GPKG, _NUTZUNG_GPKG, _NUTZUNG_TABLE, _NUTZUNG_FIELD,
        _TFIDF_INDEX, _KNN_INDEX, _CONTEXT, _SYNONYMS,
        _ARTEN_LOOKUP_CACHE, _ARTEN_LOOKUP_MODE,
        _SKLEARN_AVAILABLE, _build_tfidf_index,
        build_arten_lookup, import_altdaten,
        _normalize, _fuzzy_match_field, _FIELD_TO_VOCAB,
        _validate_matcher, _extract_test_pairs, _kappa_interpretation,
        _ensure_fehlend_table, _append_fehlend,
        _ensure_extras_table, _append_extras,
        _KNNSpatialIndex,
        _build_field_vocab,
        ensemble_rank,
        search_arten,
    )
    from qgis_new_project_plugin.workers.import_worker import _ScanWorker
except ImportError:
    from .core.import_core import (
        AUTO_FIELDS, GEO_FIELDS, DATE_FIELDS, SYSTEM_FIELDS,
        UUID_FIELDS, NOW_FIELDS, PROTECTED_FIELDS,
        COLOR_AUTO, COLOR_GEO, COLOR_DATE, COLOR_MAP, COLOR_UUID,
        _REF_GPKG, _NUTZUNG_GPKG, _NUTZUNG_TABLE, _NUTZUNG_FIELD,
        _TFIDF_INDEX, _KNN_INDEX, _CONTEXT, _SYNONYMS,
        _ARTEN_LOOKUP_CACHE, _ARTEN_LOOKUP_MODE,
        _SKLEARN_AVAILABLE, _build_tfidf_index,
        build_arten_lookup, import_altdaten,
        _normalize, _fuzzy_match_field, _FIELD_TO_VOCAB,
        _validate_matcher, _extract_test_pairs, _kappa_interpretation,
        _ensure_fehlend_table, _append_fehlend,
        _ensure_extras_table, _append_extras,
        _KNNSpatialIndex,
        _build_field_vocab,
        ensemble_rank,
        search_arten,
    )
    from .workers.import_worker import _ScanWorker

class FundpunkteImportDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fundpunkte Tiere – Altdaten importieren")
        self.setMinimumWidth(600)
        self.setMinimumHeight(580)
        self._src_layer = None
        self._scan_data = []
        self._worker    = None
        self._map_src_id            = None
        self._map_tgt_id            = None
        self._fv_tbl_widgets        = {}
        self._build_ui()
        self._populate_target_layers()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # ── Tab 1: Quelle ─────────────────────────────────────────────────
        tab1 = QWidget()
        t1 = QVBoxLayout(tab1)

        file_box = QGroupBox("Quelldatei")
        fl = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText(
            "Vektordatei oder Tabelle (GPKG, SHP, CSV, XLSX, GeoJSON …)")
        browse_btn = QPushButton("…"); browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(self._browse_src)
        fl.addWidget(self.file_edit); fl.addWidget(browse_btn)
        file_box.setLayout(fl)

        art_box = QGroupBox("Artname-Auflösung")
        ag = QFormLayout()
        self.artname_combo = QComboBox(); self.artname_combo.setEnabled(False)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Deutsch + Wissenschaftlich", "both")
        self.mode_combo.addItem("Nur Deutsch",                "de")
        self.mode_combo.addItem("Nur Wissenschaftlich",       "wiss")
        ag.addRow("Feld mit Artname:", self.artname_combo)
        ag.addRow("Suche nach:",       self.mode_combo)
        art_box.setLayout(ag)

        test_box = QGroupBox("Testsuche")
        tl = QVBoxLayout()
        tr = QHBoxLayout()
        self.test_edit = QLineEdit()
        self.test_edit.setPlaceholderText("Artname tippen und testen …")
        self.test_edit.returnPressed.connect(self._test_search)
        test_btn = QPushButton("Suchen"); test_btn.clicked.connect(self._test_search)
        tr.addWidget(self.test_edit); tr.addWidget(test_btn)
        self.result_tbl = QTableWidget(0, 3)
        self.result_tbl.setHorizontalHeaderLabels(["Wiss. Name","Deutsch","entityid"])
        self.result_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.result_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.result_tbl.setFixedHeight(120)
        tl.addLayout(tr); tl.addWidget(self.result_tbl)
        test_box.setLayout(tl)

        t1.addWidget(file_box); t1.addWidget(art_box)
        ctx_box=QGroupBox("Kontext-Layer (optional)")
        cg=QFormLayout()
        self.lu_combo=QComboBox();self.lu_combo.addItem("-- kein --",None)
        self.lu_field=QComboBox();self.lu_field.setEnabled(False)
        self.pr_combo=QComboBox();self.pr_combo.addItem("-- kein --",None)
        self.pr_field=QComboBox();self.pr_field.setEnabled(False)
        from qgis.core import QgsVectorLayer as _VL2
        for _lyr in QgsProject.instance().mapLayers().values():
            if isinstance(_lyr,_VL2):
                self.lu_combo.addItem(_lyr.name(),_lyr)
                self.pr_combo.addItem(_lyr.name(),_lyr)
        self.lu_combo.currentIndexChanged.connect(
            lambda:self._fill_field_combo(self.lu_combo,self.lu_field))
        self.pr_combo.currentIndexChanged.connect(
            lambda:self._fill_field_combo(self.pr_combo,self.pr_field))
        cg.addRow("Landnutzung (Layer):",self.lu_combo)
        cg.addRow("Landnutzung (Feld):",self.lu_field)
        cg.addRow("Schutzgebiet (Layer):",self.pr_combo)
        cg.addRow("Schutzgebiet (Feld):",self.pr_field)
        ctx_box.setLayout(cg)
        t1.addWidget(ctx_box)
        t1.addWidget(test_box);t1.addStretch()

        # ── Tab 2: Feldmapping ─────────────────────────────────────────────
        tab2 = QWidget()
        t2 = QVBoxLayout(tab2)

        dst_form = QFormLayout()
        self.target_combo = QComboBox()
        self.target_combo.currentIndexChanged.connect(self._rebuild_map_table)
        dst_form.addRow("Ziel-Layer:", self.target_combo)
        t2.addLayout(dst_form)

        # Legende
        leg = QHBoxLayout()
        for color, text in [
            (COLOR_AUTO, "Auto (Artenauflösung)"),
            (COLOR_GEO,  "Auto (Geometrie)"),
            (COLOR_DATE, "Auto (Datum)"),
            (COLOR_MAP,  "Manuell"),
        ]:
            lbl = QLabel(f"  {text}  ")
            lbl.setStyleSheet(
                f"background:{color.name()};border:1px solid #aaa;"
                f"padding:1px 4px;font-size:11px;"
            )
            leg.addWidget(lbl)
        leg.addStretch()
        t2.addLayout(leg)

        # Mapping-Tabelle: 3 Spalten
        # Col 0: Zielfeld  Col 1: Modus (ComboBox)  Col 2: Wert/Quellfeld
        map_box = QGroupBox(
            "Feldmapping   "
            "| Modus: 'Auto' = wird automatisch gesetzt  "
            "'Quellfeld' = aus Quelldatei  "
            "'Fixwert' = fester Wert"
        )
        ml = QVBoxLayout()
        self.map_tbl = QTableWidget(0, 3)
        self.map_tbl.setHorizontalHeaderLabels(
            ["Zielfeld (Fund)", "Modus", "Quellfeld / Fixwert"])
        self.map_tbl.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.map_tbl.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self.map_tbl.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self.map_tbl.verticalHeader().setDefaultSectionSize(26)
        ml.addWidget(self.map_tbl)
        map_box.setLayout(ml)
        t2.addWidget(map_box)

        # ── Tab 5: Import ─────────────────────────────────────────────────
        tab3 = QWidget()
        t3 = QVBoxLayout(tab3)
        # Validierungsbereich
        val_grp = QGroupBox("Matcher-Qualität validieren")
        val_v   = QVBoxLayout()
        val_v.addWidget(QLabel(
            "Testet den Matcher anhand eines bereits korrekt importierten\n"
            "Fund-Layers und berechnet Precision@k, MRR und Cohen's κ."))
        val_row = QHBoxLayout()
        val_row.addWidget(QLabel("Referenz-Layer:"))
        self.val_combo = QComboBox()
        self.val_combo.addItem("— keiner —", None)
        from qgis.core import QgsVectorLayer as _VL3
        for _lyr in QgsProject.instance().mapLayers().values():
            if isinstance(_lyr, _VL3):
                self.val_combo.addItem(_lyr.name(), _lyr)
        val_row.addWidget(self.val_combo)
        val_btn = QPushButton("Validieren")
        val_btn.clicked.connect(self._run_validation)
        val_row.addWidget(val_btn)
        val_v.addLayout(val_row)
        val_grp.setLayout(val_v)
        t3.addWidget(val_grp)
        self.log = QTextEdit(); self.log.setReadOnly(True)
        self.progress = QProgressBar(); self.progress.setVisible(False)
        t3.addWidget(QLabel("Import-Log:")); t3.addWidget(self.log)
        t3.addWidget(self.progress)

        # Tab 3: Artname-Mapping
        tab_art = QWidget()
        ta = QVBoxLayout(tab_art)
        ta.addWidget(QLabel(
            "Nicht aufgelöste Artnamen: \n"
            "Wähle für jeden Eintrag die passende Art aus der Referenzliste."
        ))
        art_scan_row = QHBoxLayout()
        art_scan_btn = QPushButton("Artnamen analysieren")
        art_scan_btn.clicked.connect(self._scan_artnames)
        self._export_btn = QPushButton("Debug-CSV …")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export_scan_csv)
        art_scan_row.addWidget(art_scan_btn)
        art_scan_row.addWidget(self._export_btn)
        art_scan_row.addStretch()
        ta.addLayout(art_scan_row)
        self.artmap_tbl = QTableWidget(0, 4)
        self.artmap_tbl.setHorizontalHeaderLabels(
            ["Quell-Artname", "k-NN räumlich", "TF-IDF/Synonym", "Zuordnung"])
        self.artmap_tbl.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.artmap_tbl.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.artmap_tbl.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self.artmap_tbl.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch)
        self.artmap_tbl.verticalHeader().setDefaultSectionSize(28)
        self.artmap_tbl.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        ta.addWidget(self.artmap_tbl)

        tab_fv = QWidget()
        fv_main = QVBoxLayout(tab_fv)
        fv_hdr = QHBoxLayout()
        fv_btn = QPushButton("Feldwerte scannen")
        fv_btn.clicked.connect(self._scan_field_values)
        fv_hdr.addWidget(fv_btn); fv_hdr.addStretch()
        fv_main.addLayout(fv_hdr)
        fv_main.addWidget(QLabel(
            "Ordnet Quellwerte den NRW-Standardwerten zu\n"
            "(Institution, Status, Stadium, Geschlecht). Gültig für den Import."))
        self._fv_scroll_layout = QVBoxLayout()
        self._fv_scroll_layout.addStretch()
        _fvw = QWidget(); _fvw.setLayout(self._fv_scroll_layout)
        from qgis.PyQt.QtWidgets import QScrollArea
        _fvs = QScrollArea(); _fvs.setWidgetResizable(True)
        _fvs.setWidget(_fvw); fv_main.addWidget(_fvs)
        self.tabs.addTab(tab1,    "1 – Quelle")
        self.tabs.addTab(tab2,    "2 – Feldmapping")
        self.tabs.addTab(tab_fv,  "3 – Feldwerte")
        self.tabs.addTab(tab_art, "4 – Artnamen")
        self.tabs.addTab(tab3,    "5 – Import")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        btn_box = QDialogButtonBox()
        self.run_btn   = btn_box.addButton("Importieren",
                                           QDialogButtonBox.ButtonRole.AcceptRole)
        self.close_btn = btn_box.addButton("Schließen",
                                           QDialogButtonBox.ButtonRole.RejectRole)
        self.run_btn.clicked.connect(self._run)
        self.close_btn.clicked.connect(self.reject)
        layout.addWidget(btn_box)

    # ── Slots ─────────────────────────────────────────────────────────────
    def _fill_field_combo(self, lc, fc):
        lyr = lc.currentData()
        fc.clear()
        if lyr is None:
            fc.setEnabled(False)
            return
        fc.setEnabled(True)
        for field in lyr.fields():
            fc.addItem(field.name(), field.name())

    def _auto_select_nutzung_layer(self):
        for i in range(self.lu_combo.count()):
            lyr = self.lu_combo.itemData(i)
            if lyr is None:
                continue
            src = lyr.source() if hasattr(lyr, "source") else ""
            if "Nutzung.gpkg" in src or "nutzung" in lyr.name().lower():
                self.lu_combo.setCurrentIndex(i)
                for j in range(self.lu_field.count()):
                    if self.lu_field.itemText(j).lower() == "nutzart":
                        self.lu_field.setCurrentIndex(j)
                        break
                return

    def _populate_target_layers(self):
        for lyr in QgsProject.instance().mapLayers().values():
            if not isinstance(lyr, QgsVectorLayer):
                continue
            if (lyr.geometryType() == QgsWkbTypes.GeometryType.PointGeometry
                    and lyr.fields().indexFromName("Artname") >= 0):
                self.target_combo.addItem(lyr.name(), lyr)
        for i in range(self.target_combo.count()):
            if "fund" in self.target_combo.itemText(i).lower():
                self.target_combo.setCurrentIndex(i); break

    def _scan_field_values(self):
        if not self._src_layer:
            self._log("Bitte erst Quelldatei laden."); return
        controlled = list(_FIELD_TO_VOCAB.keys())
        src_for_tgt = {}
        for row in range(self.map_tbl.rowCount()):
            item0 = self.map_tbl.item(row, 0)
            if not item0: continue
            tgt_f = item0.text().lower()
            if tgt_f not in controlled: continue
            mc = self.map_tbl.cellWidget(row, 1)
            if not mc or mc.currentData() != "src": continue
            vw = self.map_tbl.cellWidget(row, 2)
            sf = vw.currentData() if vw and hasattr(vw,"currentData") else None
            if sf: src_for_tgt[tgt_f] = sf
        if not src_for_tgt:
            self._log("  Keine kontrollierten Felder als Quellfeld gemappt."); return
        src_vals = {tf: set() for tf in src_for_tgt}
        for feat in self._src_layer.getFeatures():
            for tgt_f, sf in src_for_tgt.items():
                try:
                    from qgis.core import NULL as _QN3
                    v = feat[sf]
                    if v is None or v is _QN3: continue
                except Exception: continue
                s = str(v).strip()
                if s and s.upper() != "NULL": src_vals[tgt_f].add(s)
        while self._fv_scroll_layout.count() > 1:
            item = self._fv_scroll_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self._fv_tbl_widgets.clear()
        for tgt_f, sf in src_for_tgt.items():
            tbl_name = _FIELD_TO_VOCAB[tgt_f]
            vocab    = _build_field_vocab(tbl_name)
            ref_terms = sorted({term for _, term in vocab.values()})
            vals      = sorted(src_vals.get(tgt_f, []))
            if not vals: continue
            grp = QGroupBox(f"{tgt_f.capitalize()}  →  Quellfeld: {sf!r}")
            gv  = QVBoxLayout()
            tbl = QTableWidget(len(vals), 3)
            tbl.setHorizontalHeaderLabels(["Quell-Wert","Vorschlag","Zuordnung"])
            for ci, rm in [(0, QHeaderView.ResizeMode.ResizeToContents),
                           (1, QHeaderView.ResizeMode.Stretch),
                           (2, QHeaderView.ResizeMode.Stretch)]:
                tbl.horizontalHeader().setSectionResizeMode(ci, rm)
            tbl.verticalHeader().setDefaultSectionSize(26)
            for ri, raw_val in enumerate(vals):
                it0 = QTableWidgetItem(raw_val)
                it0.setFlags(Qt.ItemFlag.ItemIsEnabled)
                tbl.setItem(ri, 0, it0)
                raw_n = _normalize(raw_val)
                sug   = (vocab.get(raw_n) or vocab.get(raw_val.lower(),
                         (None,"")))[1]
                it1 = QTableWidgetItem(sug)
                it1.setFlags(Qt.ItemFlag.ItemIsEnabled)
                if sug: it1.setBackground(QBrush(QColor(220,255,220)))
                tbl.setItem(ri, 1, it1)
                combo = QComboBox(); combo.setEditable(True)
                combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                combo.addItem("— nicht ändern —", None)
                for term in ref_terms: combo.addItem(term, term)
                if sug: combo.setCurrentText(sug)
                # QCompleter für Autovervollständigung (kein Reset der Auswahl)
                from qgis.PyQt.QtWidgets import QCompleter
                from qgis.PyQt.QtCore import Qt as _Qt
                _cmp = QCompleter(ref_terms, combo)
                _cmp.setCaseSensitivity(_Qt.CaseSensitivity.CaseInsensitive)
                _cmp.setFilterMode(_Qt.MatchFlag.MatchContains)
                combo.setCompleter(_cmp)
                tbl.setCellWidget(ri, 2, combo)
            gv.addWidget(tbl); grp.setLayout(gv)
            self._fv_scroll_layout.insertWidget(
                self._fv_scroll_layout.count()-1, grp)
            self._fv_tbl_widgets[tgt_f] = tbl
        self._log("  Feldwerte: "
                  + ", ".join(f"{k}={len(src_vals[k])}" for k in src_for_tgt))

    def _read_field_value_overrides(self):
        overrides = {}
        for tgt_f, tbl in self._fv_tbl_widgets.items():
            fmap = {}
            for ri in range(tbl.rowCount()):
                src_item = tbl.item(ri, 0)
                combo    = tbl.cellWidget(ri, 2)
                if not src_item or not combo: continue
                ref_term = combo.currentData()
                if ref_term:
                    fmap[src_item.text().lower()] = ref_term
                    fmap[src_item.text()]          = ref_term
            if fmap: overrides[tgt_f] = fmap
        return overrides

    def _on_tab_changed(self, index):
        if index == 1:  # Feldmapping
            tgt_now    = self.target_combo.currentData()
            src_id_now = id(self._src_layer) if self._src_layer else None
            tgt_id_now = id(tgt_now)         if tgt_now         else None
            if src_id_now != self._map_src_id or tgt_id_now != self._map_tgt_id:
                self._rebuild_map_table()

    def _check_debug_csv(self, src_fields):
        """Warnt wenn der geladene Layer wie ein Debug-Export aussieht."""
        debug_cols = {"Quell_Artname", "Erkannt", "Stufe", "TFIDF_Score"}
        if debug_cols.issubset(set(src_fields)):
            self._log(
                "  ⚠ ACHTUNG: Diese Datei sieht nach einem Debug-Export aus\n"
                "  Bitte lade die Original-Quelldatei (GPKG/SHP/Altdaten-CSV).")
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Falsche Quelldatei?",
                "Die geladene Datei enthält Spalten wie 'Quell_Artname'"
                " und 'Erkannt' – das ist der Debug-Export der"
                " Artname-Analyse, nicht die Originaldatei.\n\n"
                "Bitte lade die Original-Quelldatei (GPKG, SHP, Altdaten-CSV).")

    def _run_validation(self):
        ref_layer = self.val_combo.currentData()
        if ref_layer is None:
            self._log("\u26a0 Bitte einen Referenz-Layer w\u00e4hlen."); return
        if not _TFIDF_INDEX.built:
            self._log("  Baue TF-IDF-Index \u2026")
            _build_tfidf_index()
        self._log(f"\nValidierung gegen: {ref_layer.name()}")
        pairs = _extract_test_pairs(ref_layer)
        if not pairs:
            self._log("  \u26a0 Keine Testpaare (Artname + Artname_wiss) gefunden.")
            return
        self._log(f"  {len(pairs)} eindeutige Paare als Testmenge")
        self._log("  (Quellname aus AN_LANUK/Artname_deutsch, "
                  "Erwartung aus Artname_wiss/entityid)")
        mode = self.mode_combo.currentData() or "both"
        res  = _validate_matcher(pairs, artname_mode=mode, top_k=5)
        if not res:
            return
        k = res["cohens_kappa"]
        interp = _kappa_interpretation(k)
        self._log(
            f"\n  \u250c\u2500 Matcher-Qualit\u00e4t "  
            f"({res['n_tested']} Testpaare) \u2500\u2500\u2510")
        self._log(f"  \u2502  Precision@1:  {res['precision_at_1']*100:5.1f}%")
        self._log(f"  \u2502  Precision@3:  {res['precision_at_3']*100:5.1f}%")
        self._log(f"  \u2502  Precision@5:  {res['precision_at_5']*100:5.1f}%")
        self._log(f"  \u2502  MRR:          {res['mrr']:.3f}")
        self._log(f"  \u2502  Cohen's \u03ba:   {k:+.3f}  ({interp})")
        self._log(f"  \u251c\u2500 Stufen \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2524")
        self._log(f"  \u2502  Direkt:{res['n_direct']:4}  Synonym:{res['n_synonym']:4}  "
                  f"TF+Lev:{res['n_tfidf']:4}  Fehler:{res['n_miss']:4}")
        self._log(f"  \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518")

    def _browse_src(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Quelldatei wählen", "",
            "Vektordateien (*.shp *.gpkg *.geojson *.csv *.xlsx *.xls *.ods *.kml);;Alle (*)"
        )
        if path:
            self.file_edit.setText(path)
            self._load_source(path)

    def _load_source(self, path):
        if path.lower().endswith(".csv"):
            # Delimiter auto-erkennen: Semikolon oder Komma
            delim = ","
            try:
                with open(path, encoding="utf-8-sig", errors="replace") as fh:
                    first = fh.readline()
                if first.count(";") > first.count(","):
                    delim = ";"
            except Exception:
                pass
            delim_enc = "%3B" if delim == ";" else "%2C"
            uri = (f"file:///{path}?type=csv"
                   f"&delimiter={delim_enc}"
                   f"&detectTypes=yes&geomType=none&encoding=UTF-8")
            lyr = QgsVectorLayer(uri, "src", "delimitedtext")
            if not lyr.isValid() or lyr.fields().count() <= 1:
                # Fallback: anderen Delimiter versuchen
                other = "%2C" if delim == ";" else "%3B"
                uri2  = (f"file:///{path}?type=csv"
                         f"&delimiter={other}"
                         f"&detectTypes=yes&geomType=none&encoding=UTF-8")
                lyr2  = QgsVectorLayer(uri2, "src", "delimitedtext")
                if lyr2.isValid() and lyr2.fields().count() > lyr.fields().count():
                    lyr = lyr2
        else:
            lyr = QgsVectorLayer(path, "src", "ogr")
        if not lyr.isValid():
            self._log(f"⚠ Layer ungültig: {path}"); return
        self._src_layer = lyr
        src_fields = [f.name() for f in lyr.fields()]
        self.artname_combo.clear()
        self.artname_combo.addItem("— Feld wählen —", None)
        for f in src_fields:
            self.artname_combo.addItem(f, f)
            if any(kw in f.lower() for kw in ("art","spez","spec","taxon","name")):
                self.artname_combo.setCurrentText(f)
        self.artname_combo.setEnabled(True)
        self._rebuild_map_table()
        self._log(f"✓ {os.path.basename(path)}  "
                  f"({lyr.featureCount()} Features, {len(src_fields)} Felder)")
        if len(src_fields) == 1 and path.lower().endswith(".csv"):
            self._log("  ⚠ Nur 1 Feld erkannt – CSV evtl. mit falschem"
                      " Trennzeichen geladen. Prüfe Datei.")
        self._check_debug_csv(src_fields)

    def _rebuild_map_table(self):
        tgt_lyr = self.target_combo.currentData()
        if tgt_lyr is None:
            return
        src_fields = ([f.name() for f in self._src_layer.fields()]
                      if self._src_layer else [])

        tgt_fields = [f.name() for f in tgt_lyr.fields()
                      if f.name() not in SYSTEM_FIELDS]

        # Auto-Mapping: exakte Namen (case-insensitiv) + bekannte Alias-Paare
        _ALIASES = {
            "beobachtungsdatum": ("k_datum","datum","date","obs_date",
                                  "beob_datum","obs_dat"),
            "artname":           ("artname","art","spez","taxon","species","name"),
            "anzahl":            ("anzahl","count","n","number","anz"),
            "kartierer":         ("kartierer","observer","beobachter","recorder"),
            "institution":       ("institution","org","organisation","verein"),
            "fundort":           ("fundort","ort","location","lokalitaet","site"),
            "bemerkung":         ("bemerkung","anmerkung","comment","note"),
            "status":            ("status","verhalten"),
            "stadium":           ("stadium",),
            "geschlecht":        ("geschlecht","sex","gender"),
            "anzahl":            ("anzahl","count","n","number"),
        }
        auto_map = {}
        sf_lower  = {sf.lower(): sf for sf in src_fields}
        for tf in tgt_fields:
            if tf in PROTECTED_FIELDS:
                continue  # nie automatisch auf ein Quellfeld legen
            tf_l = tf.lower()
            # 1. Exakter Treffer
            if tf_l in sf_lower:
                auto_map[tf] = sf_lower[tf_l]; continue
            # 2. Alias-Treffer
            for aliases in _ALIASES.get(tf_l, ()):
                if aliases in sf_lower:
                    auto_map[tf] = sf_lower[aliases]; break

        self.map_tbl.setRowCount(len(tgt_fields))
        self.map_tbl.blockSignals(True)

        for row, tf in enumerate(tgt_fields):
            # ── Col 0: Zielfeld ────────────────────────────────────────────
            item0 = QTableWidgetItem(tf)
            item0.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.map_tbl.setItem(row, 0, item0)

            # ── Kategorie bestimmen ────────────────────────────────────────
            if tf in PROTECTED_FIELDS:
                cat = "auto_fix"
                bg  = COLOR_UUID
            elif tf in AUTO_FIELDS:
                cat = "auto_art"
                bg  = COLOR_AUTO
            elif tf in GEO_FIELDS:
                cat = "auto_geo"
                bg  = COLOR_GEO
            elif tf in DATE_FIELDS:
                cat = "auto_date"
                bg  = COLOR_DATE
            else:
                cat = "manual"
                bg  = COLOR_MAP

            item0.setBackground(QBrush(bg))

            # ── Col 1: Modus-ComboBox ──────────────────────────────────────
            mode_combo = QComboBox()
            if cat == "auto_fix":
                # Wird beim Import immer automatisch gesetzt und darf
                # nicht gemappt werden -> keine weiteren Modi anbieten
                if tf in UUID_FIELDS:
                    mode_combo.addItem("Auto (uuid) - nicht mappbar", "auto")
                    mode_combo.setToolTip(
                        "Die Kennung wird beim Import automatisch als UUID "
                        "erzeugt und kann nicht aus der Quelle uebernommen "
                        "werden. Eine vorhandene Quell-ID bleibt in der "
                        "Tabelle Fund_Quellfelder erhalten.")
                else:
                    mode_combo.addItem(
                        "Auto (aktuelles Datum) - nicht mappbar", "auto")
                    mode_combo.setToolTip(
                        f"{tf} wird automatisch auf den Zeitpunkt des "
                        "Imports gesetzt (Systemfeld, NOT NULL) und kann "
                        "nicht aus der Quelle uebernommen werden. Ein Datum "
                        "aus den Altdaten gehoert in das Feld "
                        "Beobachtungsdatum.")
                mode_combo.setEnabled(False)
            elif cat.startswith("auto"):
                mode_combo.addItem("Auto (wird gesetzt)", "auto")
                mode_combo.addItem("Quellfeld",           "src")
                mode_combo.addItem("Fixwert",             "fix")
            else:
                mode_combo.addItem("Quellfeld",           "src")
                mode_combo.addItem("Fixwert",             "fix")
                mode_combo.addItem("Leer lassen",         "skip")

            self.map_tbl.setCellWidget(row, 1, mode_combo)

            # ── Col 2: Wert-Widget (initial) ───────────────────────────────
            self._update_value_widget(row, mode_combo.currentData(),
                                      tf, src_fields, auto_map)

            # Farbe auch auf Col 1+2
            for col in (1, 2):
                it = self.map_tbl.item(row, col)
                if it:
                    it.setBackground(QBrush(bg))

            # Signal: Modus geändert → Wert-Widget neu aufbauen
            mode_combo.currentIndexChanged.connect(
                lambda _idx, r=row, tf=tf, sf=src_fields:
                    self._on_mode_changed(r, tf, sf)
            )

        self.map_tbl.blockSignals(False)
        tgt_now = self.target_combo.currentData()
        self._map_src_id = id(self._src_layer) if self._src_layer else None
        self._map_tgt_id = id(tgt_now)         if tgt_now         else None

    def _update_value_widget(self, row, mode, tf, src_fields, auto_map=None):
        """Setzt das richtige Widget in Spalte 2 je nach Modus."""
        if mode == "auto" or mode == "skip":
            item = QTableWidgetItem(
                "uuid()" if tf in UUID_FIELDS
                else "now()" if tf in NOW_FIELDS
                else "—")
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.map_tbl.setItem(row, 2, item)
            self.map_tbl.removeCellWidget(row, 2)
            self.map_tbl.setItem(row, 2, item)
        elif mode == "src":
            combo = QComboBox()
            combo.addItem("— nicht mappen —", None)
            for sf in src_fields:
                combo.addItem(sf, sf)
            # Auto-Vorauswahl
            if auto_map and tf in auto_map:
                combo.setCurrentText(auto_map[tf])
            self.map_tbl.setCellWidget(row, 2, combo)
        elif mode == "fix":
            # Vorbelegen: Kartierer/Institution aus Projektvariablen
            prefill = ""
            if tf in ("Kartierer", "Institution"):
                from qgis.core import QgsExpressionContextUtils
                ctx = QgsExpressionContextUtils.projectScope(QgsProject.instance())
                prefill = str(ctx.variable(tf.lower()) or "")
            line = QLineEdit(prefill)
            line.setPlaceholderText(f"Fixwert für {tf} …")
            self.map_tbl.setCellWidget(row, 2, line)

    def _on_mode_changed(self, row, tf, src_fields):
        mode_combo = self.map_tbl.cellWidget(row, 1)
        if mode_combo is None:
            return
        mode = mode_combo.currentData()
        self._update_value_widget(row, mode, tf, src_fields)

    def _test_search(self):
        q    = self.test_edit.text().strip()
        mode = self.mode_combo.currentData() or "both"
        res  = search_arten(q, by=mode, limit=15)
        self.result_tbl.setRowCount(len(res) or 1)
        if res:
            for r, row in enumerate(res):
                self.result_tbl.setItem(r, 0, QTableWidgetItem(row["term"]))
                self.result_tbl.setItem(r, 1, QTableWidgetItem(row["Name_deutsch"]))
                self.result_tbl.setItem(r, 2, QTableWidgetItem(str(row["entityid"])))
        else:
            self.result_tbl.setItem(0, 0, QTableWidgetItem("Keine Treffer"))

    def _log(self, msg):
        self.log.append(msg)

    def _scan_artnames(self):
        if self._src_layer is None:
            self._log("Bitte erst Quelldatei laden (Tab 1)."); return
        artname_field = self.artname_combo.currentData()
        if not artname_field:
            self._log("Bitte Artname-Feld waehlen (Tab 1)."); return
        if self._worker and self._worker.isRunning():
            self._worker.quit(); self._worker.wait()
        self._export_btn.setEnabled(False)
        self._log("Analysiere Artnamen ...")
        self._worker = _ScanWorker(
            src_layer     = self._src_layer,
            artname_field = artname_field,
            mode          = self.mode_combo.currentData() or "both",
            lu_layer      = self.lu_combo.currentData(),
            lu_field      = self.lu_field.currentData(),
            pr_layer      = self.pr_combo.currentData(),
            pr_field      = self.pr_field.currentData(),
            ctx_key_cache = getattr(self, "_ctx_key_cache", None),
            parent        = self,
        )
        self._worker.log_msg.connect(self._log)
        self._worker.finished.connect(self._on_scan_done)
        self._worker.start()

    def _on_scan_done(self, not_found, scan_data, pos_cache):
        self._scan_data = scan_data
        self._export_btn.setEnabled(bool(scan_data))
        self._pos_cache = pos_cache
        self._ctx_key_cache = (id(_CONTEXT.landuse_layer),
                               id(_CONTEXT.protect_layer),
                               _CONTEXT.landuse_field,
                               _CONTEXT.protect_field)
        lookup = _ARTEN_LOOKUP_CACHE
        mode   = self.mode_combo.currentData() or "both"

        self.artmap_tbl.setRowCount(len(not_found))
        for row, raw in enumerate(not_found):
            it0 = QTableWidgetItem(raw)
            it0.setFlags(Qt.ItemFlag.ItemIsEnabled)
            it0.setBackground(QBrush(QColor(255, 235, 235)))
            self.artmap_tbl.setItem(row, 0, it0)
            # Synonym-Prüfung zuerst
            raw_n_r   = _normalize(raw)
            syn_key_r = _SYNONYMS.get(raw_n_r) or _SYNONYMS.get(raw.lower().strip())
            syn_entry = None
            if syn_key_r:
                syn_entry = (lookup.get(syn_key_r.lower())
                             or lookup.get(_normalize(syn_key_r)))
                if not syn_entry and os.path.isfile(_REF_GPKG):
                    import sqlite3 as _sq3
                    _c3 = _sq3.connect(_REF_GPKG)
                    _r3 = _c3.execute(
                        "SELECT entityid,term,Name_deutsch,parentid FROM Arten "
                        "WHERE parentid!='nan' AND "
                        "(lower(term) LIKE lower(?) OR lower(Name_deutsch) LIKE lower(?)) "
                        "ORDER BY length(term) LIMIT 1",
                        (f"%{syn_key_r}%", f"%{syn_key_r}%")).fetchone()
                    _c3.close()
                    if _r3:
                        syn_entry = {"entityid":_r3[0],"term":_r3[1] or "",
                                     "Name_deutsch":_r3[2] or "","parentid":_r3[3] or ""}
            # Ensemble: TF-IDF + k-NN + Habitat + Schutz
            tf_top = _TFIDF_INDEX.query(raw, top_k=12) if _TFIDF_INDEX.built else []
            knn_v2 = self._get_knn_vote_for(raw)
            lu_val = pr_val = ""
            if _CONTEXT.built:
                pos2 = self._positions_for(raw)
                if pos2:
                    from collections import Counter as _Ct2
                    _lus, _prs = zip(*[_CONTEXT.get_context(x, y) for x, y in pos2[:5]])
                    lu_val = _Ct2(_lus).most_common(1)[0][0]
                    pr_val = _Ct2(_prs).most_common(1)[0][0]
            ranked = ensemble_rank(tf_top, knn_v2, lu_val, pr_val)
            if syn_entry:
                sug = syn_entry
            else:
                sug = ranked[0][1] if ranked else self._suggest(raw, lookup)
            if knn_v2:
                _ke  = knn_v2["entry"]
                _kpc = min(int(knn_v2["count"]/max(knn_v2["total"],1)*100), 100)
                knn_text = (_ke["Name_deutsch"] or _ke["term"]) + f" ({_kpc}%)"
            else:
                knn_text = "—"
            it_knn   = QTableWidgetItem(knn_text)
            it_knn.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if knn_text != "—":
                it_knn.setBackground(QBrush(QColor(220, 240, 255)))
            self.artmap_tbl.setItem(row, 1, it_knn)
            if syn_entry:
                ens_lbl = syn_entry["term"]+"  ("+syn_entry["Name_deutsch"]+")  [Synonym]"
            elif ranked:
                sc0, e0, _ = ranked[0]
                ens_lbl = e0["term"]+"  ("+e0["Name_deutsch"]+")  ["+f"{sc0:.2f}"+"]"
            else:
                ens_lbl = (sug["term"]+"  ("+sug["Name_deutsch"]+")") if sug else "---"
            it1=QTableWidgetItem(ens_lbl)
            it1.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if syn_entry:
                it1.setBackground(QBrush(QColor(255, 255, 180)))  # gelb = Synonym
            elif ranked and ranked[0][0] > 0.25:
                it1.setBackground(QBrush(QColor(220, 255, 220)))  # gruen = TF-IDF
            self.artmap_tbl.setItem(row,2,it1)
            combo = QComboBox()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            combo.addItem("nicht zuordnen",None)
            added = set()
            if syn_entry:  # Synonym zuerst in der Liste
                lbl2 = syn_entry["term"] + " - " + syn_entry["Name_deutsch"]
                combo.addItem(lbl2, syn_entry); added.add(lbl2)
            for _, re2, _ in ranked[:6]:
                lbl2 = re2["term"] + " - " + re2["Name_deutsch"]
                if lbl2 not in added: combo.addItem(lbl2, re2); added.add(lbl2)
            if sug:
                lbl2 = sug["term"] + " - " + sug["Name_deutsch"]
                if lbl2 not in added: combo.addItem(lbl2, sug); added.add(lbl2)
            for r in search_arten(raw,by=mode,limit=5):
                lbl2=r["term"]+" - "+r["Name_deutsch"]
                if lbl2 not in added:combo.addItem(lbl2,r);added.add(lbl2)
            combo.setCurrentIndex(1 if (ranked or sug) else 0)
            combo.lineEdit().textChanged.connect(
                lambda text, c=combo, m=mode: self._live_search(text, c, m))
            self.artmap_tbl.setCellWidget(row, 3, combo)
        total    = len(scan_data)
        resolved = total - len(not_found)
        self._log(
            f"Analyse: {total} eindeutige Artnamen "
            f"-> {resolved} aufgeloest, {len(not_found)} nicht erkannt")
        if not_found:
            preview = ", ".join(not_found[:8])
            if len(not_found) > 8: preview += " ..."
            self._log(f"  Nicht erkannt: {preview}")
            self.tabs.setCurrentIndex(3)
        else:
            self._log("  Alle Artnamen wurden aufgeloest.")


    def _positions_for(self, raw_name):
        """Gibt UTM32-Koordinaten der Fundpunkte für einen Artnamen.
        Primär aus pos_cache (bereits transformiert vom Worker).
        Fallback: direkt aus Layer lesen (ohne Transform – nur Notfall).
        """
        if hasattr(self, "_pos_cache") and self._pos_cache:
            return self._pos_cache.get(raw_name, [])
        # Fallback: direkt aus Layer (kommt selten vor)
        af = self.artname_combo.currentData()
        if not af or not self._src_layer:
            return []
        pos = []
        for feat in self._src_layer.getFeatures():
            val = feat[af]
            try:
                from qgis.core import NULL as _NL3
                if val is None or val is _NL3:
                    continue
            except Exception:
                pass
            if str(val).strip() != raw_name:
                continue
            g = feat.geometry()
            if g and not g.isEmpty():
                pt = g.asPoint()
                pos.append((pt.x(), pt.y()))
        return pos

    def _build_knn_index(self, lookup):
        global _KNN_INDEX
        src_id = id(self._src_layer) if self._src_layer else None
        if _KNN_INDEX.built and getattr(self, "_knn_src_id", None) == src_id:
            return  # Bereits aktuell
        _KNN_INDEX = _KNNSpatialIndex()
        self._knn_src_id = src_id
        if not self._src_layer:
            return
        art_field = self.artname_combo.currentData()
        if not art_field:
            return
        records = []
        # pos_cache nutzen falls vorhanden
        if hasattr(self, "_pos_cache") and self._pos_cache:
            for name, positions in self._pos_cache.items():
                entry = (lookup.get(name.lower()) or lookup.get(_normalize(name)))
                if not entry:
                    syn = _SYNONYMS.get(_normalize(name)) or _SYNONYMS.get(name.lower())
                    if syn: entry = lookup.get(syn.lower()) or lookup.get(_normalize(syn))
                if not entry: continue
                for x, y in positions:
                    records.append({"x":x,"y":y,"entityid":entry["entityid"],
                                    "term":entry["term"],"Name_deutsch":entry["Name_deutsch"]})
        else:
            for feat in self._src_layer.getFeatures():
                val = feat[art_field]
                try:
                    from qgis.core import NULL as _NULL
                    if val is None or val is _NULL:
                        continue
                except Exception:
                    pass
                name  = str(val).strip()
                entry = lookup.get(name.lower()) or lookup.get(_normalize(name))
                if not entry:
                    continue
                geom = feat.geometry()
                if not geom or geom.isEmpty():
                    continue
                pt = geom.asPoint()
                records.append({"x": pt.x(), "y": pt.y(),
                                 "entityid": entry["entityid"],
                                 "term": entry["term"],
                                 "Name_deutsch": entry["Name_deutsch"]})
        _KNN_INDEX.build(records)
        if _KNN_INDEX.built:
            self._log(f"  k-NN-Index: {len(records)} aufgelöste Records  (aus Cache)")

    def _get_knn_vote_for(self, raw_name):
        if not _KNN_INDEX.built:
            return {}
        from collections import Counter
        ev = Counter(); ee = {}; total = 0
        for x, y in self._positions_for(raw_name):
            v = _KNN_INDEX.vote(x, y, k=10, max_radius=50000.0)  # 50 km
            if v:
                eid = v["entry"]["entityid"]
                ev[eid] += v["count"]
                ee[eid]  = v["entry"]
                total   += v.get("total", 0)
        if not ev:
            return {}
        best = ev.most_common(1)[0][0]
        return {"entry": ee[best], "count": ev[best], "total": max(total, 1)}

    def _knn_suggest_for(self, raw_name):
        if not _KNN_INDEX.built:return "—"
        af=self.artname_combo.currentData()
        if not af:return "—"
        knn_v=self._get_knn_vote_for(raw_name)
        if not knn_v:return "—"
        e=knn_v["entry"]
        pct=min(int(knn_v["count"]/max(knn_v["total"],1)*100),100)
        lbl=e["Name_deutsch"] or e["term"]
        return f"{lbl} ({pct}%)"

    def _export_scan_csv(self):
        from qgis.PyQt.QtWidgets import QFileDialog
        if not self._scan_data:
            self._log("Erst Artnamen analysieren."); return
        path, _ = QFileDialog.getSaveFileName(
            self, "Debug-CSV speichern", "artname_analyse.csv", "CSV (*.csv)")
        if not path:
            return
        if not path.endswith(".csv"):
            path += ".csv"
        cols=["Quell_Artname","Erkannt","KNN","Landnutzung","Schutzgebiet",
                "Ensemble_Score","Stufe","Synonym_Key",
                "Vorschlag_wiss","Vorschlag_de","Vorschlag_eid","TFIDF_Score"]
        import csv
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=cols, delimiter=";",
                                   extrasaction="ignore")
                w.writeheader()
                w.writerows(self._scan_data)
            self._log(f"✓ Debug-CSV: {path}  ({len(self._scan_data)} Zeilen)")
        except Exception as e:
            self._log(f"✗ {e}")

    def _suggest(self, raw, lookup):
        """
        Artname-Suggest mit drei Stufen:
        1. Synonymtabelle (_SYNONYMS) – für bekannte NRW-Altdaten-Abweichungen
        2. Direkter Lookup (normalisiert) – exakter Treffer im Lookup-Dict
        3. TF-IDF (Bi+Trigramm Cosine-Similarity) – für alles andere
        Bonus: 'unbestimmt'-Einträge werden bevorzugt wenn passend.
        """
        raw_n = _normalize(raw)
        has_unb = "unbestimmt" in raw_n

        # Stufe 1: Synonymtabelle
        synonym_term = _SYNONYMS.get(raw_n) or _SYNONYMS.get(raw.lower().strip())
        if synonym_term:
            # Suche Synonym im Lookup
            entry = lookup.get(synonym_term) or lookup.get(_normalize(synonym_term))
            if entry:
                return entry
            # Sonst: SQL-Suche nach Synonym
            if os.path.isfile(_REF_GPKG):
                import sqlite3 as _sq
                con = _sq.connect(_REF_GPKG)
                cur = con.cursor()
                cur.execute(
                    "SELECT entityid, term, Name_deutsch, parentid FROM Arten "
                    "WHERE parentid != 'nan' AND "
                    "(lower(term) LIKE lower(?) OR lower(Name_deutsch) LIKE lower(?)) "
                    "ORDER BY length(term) LIMIT 1",
                    (f"%{synonym_term}%", f"%{synonym_term}%"),
                )
                row = cur.fetchone()
                con.close()
                if row:
                    return {"entityid": row[0], "term": row[1] or "",
                            "Name_deutsch": row[2] or "", "parentid": row[3] or ""}

        # Stufe 2: Direkter normalisierter Lookup
        direct = lookup.get(raw_n) or lookup.get(raw.lower().strip())
        if direct:
            return direct

        # Stufe 3: TF-IDF
        if not _TFIDF_INDEX.built:
            return None
        results = _TFIDF_INDEX.query(raw, top_k=10)
        if not results:
            return None
        if has_unb:
            for sim, entry in results:
                if "unbestimmt" in entry["Name_deutsch"].lower():
                    return entry
        return results[0][1]

    def _live_search(self, text, combo, mode):
        if len(text) < 2:
            return
        results = search_arten(text, by=mode, limit=10)
        combo.blockSignals(True)
        while combo.count() > 1:
            combo.removeItem(1)
        for r in results:
            combo.addItem(f"{r['term']} - {r['Name_deutsch']}", r)
        combo.blockSignals(False)

        # ── Mapping aus Tabelle lesen ──────────────────────────────────────────
    def _read_mapping(self):
        mapping = []
        for row in range(self.map_tbl.rowCount()):
            item0 = self.map_tbl.item(row, 0)
            if item0 is None:
                continue
            tf         = item0.text()
            mode_combo = self.map_tbl.cellWidget(row, 1)
            mode       = mode_combo.currentData() if mode_combo else "skip"
            val_widget = self.map_tbl.cellWidget(row, 2)

            if tf in PROTECTED_FIELDS:
                continue  # Kennung/Eingabedatum: immer automatisch
            if mode == "auto" or mode == "skip":
                continue  # wird automatisch gefüllt oder explizit weggelassen

            if mode == "src":
                src_f = val_widget.currentData() if val_widget else None
                if src_f:
                    mapping.append({"tgt": tf, "mode": "src",
                                    "src_field": src_f, "fix_value": None})
            elif mode == "fix":
                fix_v = val_widget.text().strip() if val_widget else ""
                mapping.append({"tgt": tf, "mode": "fix",
                                 "src_field": None, "fix_value": fix_v})
        return mapping

    # ── Import starten ────────────────────────────────────────────────────
    def _run(self):
        if self._src_layer is None:
            self._log("⚠ Bitte zuerst Quelldatei laden (Tab 1).")
            self.tabs.setCurrentIndex(0); return
        artname_field = self.artname_combo.currentData()
        if not artname_field:
            self._log("⚠ Bitte Artname-Feld wählen (Tab 1).")
            self.tabs.setCurrentIndex(0); return
        tgt_layer = self.target_combo.currentData()
        if tgt_layer is None:
            self._log("⚠ Kein Ziel-Layer (Tab 2).")
            self.tabs.setCurrentIndex(1); return

        mapping = self._read_mapping()
        mode    = self.mode_combo.currentData() or "both"

        artname_overrides = {}
        for row in range(self.artmap_tbl.rowCount()):
            raw_item = self.artmap_tbl.item(row, 0)
            combo    = self.artmap_tbl.cellWidget(row, 3)
            if raw_item and combo:
                data = combo.currentData()
                if data and isinstance(data, dict):
                    artname_overrides[raw_item.text().lower().strip()] = data

        self.run_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.tabs.setCurrentIndex(3)

        self._log(f"Importiere {self._src_layer.featureCount()} Features ...")
        self._log(f"  Artname-Feld: {artname_field!r}  Suchmodus: {mode}")
        self._log(f"  {len(mapping)} manuelle Feldmappings")
        if artname_overrides:
            self._log(f"  {len(artname_overrides)} manuelle Artname-Zuordnungen")

        def prog(pct, msg):
            if pct >= 0:
                self.progress.setValue(pct)
            if msg:
                self._log(msg)

        try:
            imported, not_res, errors = import_altdaten(
                self._src_layer, tgt_layer,
                mapping, artname_field, mode, prog,
                artname_overrides=artname_overrides,
                field_value_overrides=self._read_field_value_overrides())
            self.progress.setValue(100)
            self._log(f"\n✓ {imported} Features importiert")
            if not_res:
                self._log(
                    f"  ⚠ {not_res} Artnamen nicht aufgeloest "
                    f"(Rohwert in Artname_wiss) "
                    f"-> Tab 3 Artnamen erneut scannen")
            if errors:
                self._log(f"  ✗ {errors} Fehler beim Import")
            tgt_layer.triggerRepaint()
        except Exception as e:
            import traceback
            self._log(f"✗ {e}\n{traceback.format_exc()}")
        finally:
            self.progress.setVisible(False)
            self.run_btn.setEnabled(True)
