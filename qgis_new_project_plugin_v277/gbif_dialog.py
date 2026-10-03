"""
gbif_dialog.py – GBIF Artvorkommen abrufen
==========================================
Lädt Fundpunkte aus der GBIF Occurrence API für das aktuelle Projektgebiet.
Keine Registrierung nötig (öffentliche API für Lesezugriff).
"""

import json
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QGroupBox, QLineEdit,
    QSpinBox, QCheckBox, QTextEdit, QProgressBar,
    QComboBox, QDialogButtonBox,
)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsPointXY, QgsFields, QgsField, QgsWkbTypes,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor

GBIF_BASE = "https://api.gbif.org/v1"


class _GbifWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str, list)   # ok, msg, features

    def __init__(self, cfg: dict):
        super().__init__()
        self._cfg = cfg

    def run(self):
        try:
            self._fetch()
        except Exception as e:
            self.finished.emit(False, str(e), [])

    def _fetch(self):
        import urllib.request, urllib.parse

        cfg     = self._cfg
        bbox    = cfg["bbox"]           # (lon_min, lat_min, lon_max, lat_max)
        taxon   = cfg.get("taxon", "").strip()
        max_rec = cfg.get("max_records", 500)
        only_de = cfg.get("only_de", True)
        min_acc = cfg.get("min_accuracy", 1000)   # m

        # Taxon-Key über species/match auflösen
        taxon_key = None
        if taxon:
            self.progress.emit(5, f"Suche Taxon: {taxon} …")
            params = urllib.parse.urlencode({"name": taxon, "verbose": "false"})
            url = f"{GBIF_BASE}/species/match?{params}"
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read())
            if data.get("matchType") != "NONE" and "usageKey" in data:
                taxon_key = data["usageKey"]
                canon    = data.get("canonicalName", taxon)
                rank     = data.get("rank", "")
                self.progress.emit(10,
                    f"  → {canon} ({rank}, Key={taxon_key})")
            else:
                self.progress.emit(10,
                    f"  ⚠ Kein GBIF-Taxon gefunden für '{taxon}'")

        # ── Schritt 1: Gesamtanzahl ermitteln (limit=0) ─────────────────
        self.progress.emit(12, "Ermittle Gesamtanzahl …")
        count_params = {
            "decimalLatitude":    f"{bbox[1]},{bbox[3]}",
            "decimalLongitude":   f"{bbox[0]},{bbox[2]}",
            "hasCoordinate":      "true",
            "hasGeospatialIssue": "false",
            "limit": 0,
        }
        if cfg.get("only_de"): count_params["country"] = "DE"
        if taxon_key:          count_params["taxonKey"] = taxon_key
        if cfg.get("min_accuracy", 0) > 0:
            count_params["coordinateUncertaintyInMeters"] = f"0,{cfg['min_accuracy']}"
        if cfg.get("year_from"): 
            count_params["year"] = f"{cfg['year_from']},{cfg.get('year_to', 2100)}"
        elif cfg.get("year_to"):
            count_params["year"] = f"1700,{cfg['year_to']}"
        _url_c = f"{GBIF_BASE}/occurrence/search?{urllib.parse.urlencode(count_params)}"
        with urllib.request.urlopen(_url_c, timeout=15) as _r:
            _count_data = json.loads(_r.read())
        total_available = _count_data.get("count", 0)
        will_load = min(total_available, max_rec)
        self.progress.emit(14,
            f"  {total_available:,} Vorkommen verfügbar im Gebiet"
            f" – lade {will_load:,} (Maximum: {max_rec:,})")

        # ── Schritt 2: Datensätze laden ──────────────────────────────────
        self.progress.emit(15, "Lade Vorkommen …")
        all_feats = []
        offset    = 0
        page_size = min(300, max_rec)
        total     = total_available

        while True:
            params = {
                "decimalLatitude":  f"{bbox[1]},{bbox[3]}",
                "decimalLongitude": f"{bbox[0]},{bbox[2]}",
                "hasCoordinate":    "true",
                "hasGeospatialIssue": "false",
                "limit":  page_size,
                "offset": offset,
            }
            if only_de:
                params["country"] = "DE"
            if taxon_key:
                params["taxonKey"] = taxon_key
            if min_acc > 0:
                params["coordinateUncertaintyInMeters"] = f"0,{min_acc}"
            year_from = cfg.get("year_from")
            year_to   = cfg.get("year_to")
            if year_from and year_to:
                params["year"] = f"{year_from},{year_to}"
            elif year_from:
                params["year"] = f"{year_from},{year_to or 2100}"
            elif year_to:
                params["year"] = f"1700,{year_to}"

            url = f"{GBIF_BASE}/occurrence/search?{urllib.parse.urlencode(params)}"
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.loads(r.read())

            if total is None:   # Fallback wenn count-Request fehlschlug
                total = data.get("count", 0)

            results = data.get("results", [])
            all_feats.extend(results)
            offset += len(results)

            pct = min(90, 20 + int(70 * offset / max(total, 1)))
            self.progress.emit(pct,
                f"  {len(all_feats):,} / {min(total, max_rec):,} geladen …")

            if data.get("endOfRecords", True) or len(all_feats) >= max_rec:
                break

        self.progress.emit(95,
            f"✓ {len(all_feats):,} Fundpunkte geladen")
        self.finished.emit(True,
            f"✓ {len(all_feats):,} GBIF-Fundpunkte geladen", all_feats)


class GbifDialog(QDialog):
    """Dialog zum Abrufen von GBIF-Artvorkommen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GBIF – Artvorkommen abrufen")
        self.setMinimumWidth(480)
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)

        # ── Suchparameter ──────────────────────────────────────────────────
        grp = QGroupBox("Suchparameter")
        fl  = QFormLayout(grp)

        self.taxon_edit = QLineEdit()
        self.taxon_edit.setPlaceholderText(
            "z.B. Ciconia ciconia  –  leer = alle Arten")
        self.taxon_edit.setToolTip(
            "Wissenschaftlicher Name. Die GBIF species/match-API löst\n"
            "den Namen automatisch auf (tolerant gegenüber Tippfehlern).")
        fl.addRow("Art (wissenschaftl.):", self.taxon_edit)

        self.only_de_cb = QCheckBox("Nur Deutschland (country=DE)")
        self.only_de_cb.setChecked(True)
        fl.addRow("", self.only_de_cb)

        self.acc_spin = QSpinBox()
        self.acc_spin.setRange(0, 10000)
        self.acc_spin.setValue(1000)
        self.acc_spin.setSuffix(" m Koordinatengenauigkeit")
        self.acc_spin.setToolTip(
            "Nur Fundpunkte mit Koordinatengenauigkeit ≤ diesem Wert.\n"
            "0 = kein Filter.")
        fl.addRow("Max. Ungenauigkeit:", self.acc_spin)

        # Jahresfilter
        year_lo = QHBoxLayout()
        self.year_from = QSpinBox()
        self.year_from.setRange(1700, 2100)
        self.year_from.setValue(2000)
        self.year_from.setSpecialValueText("–")   # 1700 = kein Filter
        self.year_from.setMinimum(1700)
        self.year_to = QSpinBox()
        self.year_to.setRange(1700, 2100)
        import datetime
        self.year_to.setValue(datetime.date.today().year)
        self.year_to.setSpecialValueText("–")
        year_lo.addWidget(self.year_from)
        year_lo.addWidget(QLabel("–"))
        year_lo.addWidget(self.year_to)
        fl.addRow("Zeitraum (Jahr):", year_lo)

        self.max_spin = QSpinBox()
        self.max_spin.setRange(10, 10000)
        self.max_spin.setValue(500)
        self.max_spin.setSuffix(" Datensätze")
        fl.addRow("Maximale Anzahl:", self.max_spin)

        lo.addWidget(grp)

        # ── BBOX ───────────────────────────────────────────────────────────
        bbox_grp = QGroupBox("Gebiet")
        bbox_lo  = QVBoxLayout(bbox_grp)
        self.bbox_lbl = QLabel("→ wird aus dem Kartenausschnitt übernommen")
        self.bbox_lbl.setStyleSheet("color: gray; font-size: 11px;")
        bbox_lo.addWidget(self.bbox_lbl)
        lo.addWidget(bbox_grp)

        # ── Fortschritt / Log ──────────────────────────────────────────────
        self.bar = QProgressBar()
        self.bar.setRange(0, 100); self.bar.setValue(0)
        self.bar.setVisible(False)
        lo.addWidget(self.bar)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        lo.addWidget(self.log)

        # ── Buttons ────────────────────────────────────────────────────────
        btn_lo = QHBoxLayout()
        self.run_btn = QPushButton("Vorkommen laden")
        self.run_btn.setDefault(True)
        self.run_btn.clicked.connect(self._start)
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self.accept)
        btn_lo.addWidget(self.run_btn)
        btn_lo.addWidget(close_btn)
        lo.addLayout(btn_lo)

        self._update_bbox_label()

    def _update_bbox_label(self):
        bbox = self._get_bbox()
        if bbox:
            self.bbox_lbl.setText(
                f"Lon {bbox[0]:.4f}–{bbox[2]:.4f}, "
                f"Lat {bbox[1]:.4f}–{bbox[3]:.4f}")
        else:
            self.bbox_lbl.setText("⚠ Kein Kartenausschnitt – Projekt öffnen")

    def _get_bbox(self):
        """Canvas-Ausdehnung → WGS84 (lon_min, lat_min, lon_max, lat_max)."""
        try:
            from qgis.utils import iface
            ext = iface.mapCanvas().extent()
            crs_src = iface.mapCanvas().mapSettings().destinationCrs()
            crs_wgs = QgsCoordinateReferenceSystem("EPSG:4326")
            if crs_src != crs_wgs:
                tr  = QgsCoordinateTransform(crs_src, crs_wgs,
                                              QgsProject.instance())
                ext = tr.transformBoundingBox(ext)
            return (ext.xMinimum(), ext.yMinimum(),
                    ext.xMaximum(), ext.yMaximum())
        except Exception:
            return None

    def _resolve_datasets(self, lyr):
        """Löst fehlende Datenquellen über GBIF Registry API auf.
        Sammelt unique datasetKeys → ein Request pro Dataset → aktualisiert Layer.
        """
        import urllib.request, json
        # Sammle unique datasetKeys mit leerer Datenquelle
        lyr.startEditing()
        ds_keys = {}
        for feat in lyr.getFeatures():
            if not feat["datenquelle"] and feat["dataset_key"]:
                ds_keys.setdefault(feat["dataset_key"], [])\
                       .append(feat.id())
        if not ds_keys:
            lyr.commitChanges()
            return
        self._log(f"  Löse {len(ds_keys)} Dataset-Namen aus GBIF Registry auf …")
        idx_ds = lyr.fields().indexOf("datenquelle")
        idx_inst = lyr.fields().indexOf("institution")
        for dk, fids in ds_keys.items():
            try:
                url = f"https://api.gbif.org/v1/dataset/{dk}"
                with urllib.request.urlopen(url, timeout=10) as r:
                    meta = json.loads(r.read())
                title = meta.get("title", "")
                org   = meta.get("publishingOrganizationKey", "")
                # Plattform-Erkennung aus Titel
                _plat = ""
                for kw, name in [
                    ("observation.org",  "Observation.org"),
                    ("Observation.org",  "Observation.org"),
                    ("iNaturalist",      "iNaturalist"),
                    ("eBird",            "eBird"),
                    ("ornitho",          "ornitho.de"),
                    ("naturgucker",      "naturgucker"),
                    ("Artportalen",      "Artportalen"),
                ]:
                    if kw.lower() in title.lower():
                        _plat = name; break
                datenquelle = _plat or title or f"GBIF:{dk[:8]}"
                for fid in fids:
                    lyr.changeAttributeValue(fid, idx_ds,   datenquelle)
                    lyr.changeAttributeValue(fid, idx_inst, _plat or title[:20])
                self._log(f"    {dk[:8]}… → {datenquelle} ({len(fids)} Fundpunkte)")
            except Exception as _e:
                self._log(f"    ⚠ Registry {dk[:8]}…: {_e}")
        lyr.commitChanges()

    def _log(self, msg: str):
        self.log.append(msg)

    def _start(self):
        bbox = self._get_bbox()
        if not bbox:
            self._log("⚠ Kein gültiger Kartenausschnitt.")
            return

        cfg = {
            "bbox":         bbox,
            "taxon":        self.taxon_edit.text().strip(),
            "max_records":  self.max_spin.value(),
            "only_de":      self.only_de_cb.isChecked(),
            "min_accuracy": self.acc_spin.value(),
            "year_from":    self.year_from.value() if self.year_from.value() > 1700 else None,
            "year_to":      self.year_to.value()   if self.year_to.value()   > 1700 else None,
        }
        self.run_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.log.clear()
        self._log("GBIF-Abfrage wird gestartet …")

        self._worker = _GbifWorker(cfg)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, pct: int, msg: str):
        if pct >= 0:
            self.bar.setValue(pct)
        self._log(msg)

    def _on_finished(self, ok: bool, msg: str, records: list):
        self._log(msg)
        self.bar.setValue(100 if ok else 0)
        self.run_btn.setEnabled(True)
        if ok and records:
            self._build_layer(records)

    def _build_layer(self, records: list):
        """GBIF JSON-Records → QGIS-Punktlayer."""
        fields = QgsFields()
        for fname, ftype in [
            ("gbif_key",        QVariant.LongLong),
            ("art",             QVariant.String),
            ("familie",         QVariant.String),
            ("klasse",          QVariant.String),
            ("datum",           QVariant.String),
            ("beobachter",      QVariant.String),
            ("bestimmer",       QVariant.String),   # identifiedBy
            ("beobachter_id",   QVariant.String),   # recordedByID (ORCID/URL)
            ("datenquelle",     QVariant.String),   # datasetName / Plattform
            ("dataset_key",     QVariant.String),   # GBIF datasetKey (UUID)
            ("institution",     QVariant.String),   # institutionCode
            ("sammlung",        QVariant.String),   # collectionCode
            ("katalog_nr",      QVariant.String),   # catalogNumber
            ("quell_url",       QVariant.String),   # occurrenceID (Quell-Link)
            ("ort",             QVariant.String),   # locality
            ("bundesland",      QVariant.String),   # stateProvince
            ("rechte_inhaber",  QVariant.String),   # rightsHolder
            ("verifikation",    QVariant.String),   # identificationVerificationStatus
            ("genauigkeit_m",   QVariant.Int),
            ("basis",           QVariant.String),   # basisOfRecord (lesbar)
            ("land",            QVariant.String),
            ("jahr",            QVariant.Int),
            ("gbif_url",        QVariant.String),
        ]:
            fields.append(QgsField(fname, ftype))

        taxon_name = self.taxon_edit.text().strip() or "alle_Arten"
        lyr_name   = f"GBIF_{taxon_name.replace(' ', '_')}"
        lyr = QgsVectorLayer(
            f"Point?crs=EPSG:4326", lyr_name, "memory")
        dp  = lyr.dataProvider()
        dp.addAttributes(fields.toList())
        lyr.updateFields()

        feats = []
        skipped = 0
        for rec in records:
            lat = rec.get("decimalLatitude")
            lon = rec.get("decimalLongitude")
            if lat is None or lon is None:
                skipped += 1
                continue
            feat = QgsFeature(lyr.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
            feat["gbif_key"]      = rec.get("key", 0)
            feat["art"]           = rec.get("species",
                                       rec.get("scientificName", ""))
            feat["familie"]       = rec.get("family", "")
            feat["klasse"]        = rec.get("class", "")
            _ed = rec.get("eventDate", "")
            feat["datum"]         = _ed[:10] if _ed else ""
            _rec_by_raw = rec.get("recordedBy", "")
            _rec_id     = ""   # wird weiter unten gesetzt
            # Echter Name aus media[].creator wenn recordedBy anonymisiert
            _media_creator = ""
            for _m in (rec.get("media") or rec.get("extensions", {}).get(
                "http://rs.tdwg.org/ac/terms/Multimedia", []) or []):
                _mc = _m.get("creator", "") or _m.get(
                    "http://purl.org/dc/elements/1.1/creator", "")
                if _mc: _media_creator = _mc; break
            # Nutze echten Namen wenn recordedBy anonymisiert (User XXXXX)
            if _rec_by_raw.startswith("User ") and _media_creator:
                feat["beobachter"] = _media_creator
            else:
                feat["beobachter"] = _rec_by_raw
            feat["bestimmer"]     = rec.get("identifiedBy", "")
            feat["beobachter_id"] = _rec_id or rec.get("recordedByID", "")
            # ── Datenquelle vollständig auflösen ─────────────────────────
            _dsname  = rec.get("datasetName", "")
            _inst    = rec.get("institutionCode", "")
            _coll    = rec.get("collectionCode", "")
            _catno   = rec.get("catalogNumber", "")
            _occ_id  = rec.get("occurrenceID", "")   # Quell-URL (observation.org etc.)
            _rec_by  = rec.get("recordedBy", "")
            _rec_id  = rec.get("recordedByID", "")
            # Wenn Beobachter anonymisiert (User XXXXX) → Profil-URL aus occurrenceID
            if _rec_by.startswith("User ") and _occ_id:
                _uid = _rec_by.split(" ")[-1]
                if "observation.org" in _occ_id:
                    _rec_id = f"https://observation.org/users/{_uid}"
            _refs    = rec.get("references", "")
            # Plattform aus occurrenceID/references ableiten
            _plat = ""
            for _url in [_occ_id, _refs]:
                if "inaturalist.org" in _url:    _plat = "iNaturalist"; break
                if "ebird.org"       in _url:    _plat = "eBird";       break
                if "observation.org" in _url:    _plat = "Observation"; break
                if "ornitho.de"      in _url:    _plat = "ornitho.de";  break
                if "artportalen.se"  in _url:    _plat = "Artportalen"; break
                if "naturgucker.de"  in _url:    _plat = "naturgucker"; break
            _rights = rec.get("rightsHolder", "")
            # publishingOrgKey → Plattform-Erkennung aus rights
            if not _plat and _rights:
                for _kw, _name in [
                    ("observation", "Observation.org"),
                    ("iNaturalist",  "iNaturalist"),
                    ("eBird",        "eBird"),
                    ("ornitho",      "ornitho.de"),
                    ("naturgucker",  "naturgucker"),
                ]:
                    if _kw.lower() in _rights.lower():
                        _plat = _name; break
            # Datenhalter: Plattform > datasetName > rightsHolder > institutionCode
            _src_parts = [p for p in [_plat or _dsname, _inst, _coll] if p]
            feat["datenquelle"]   = " / ".join(_src_parts) if _src_parts \
                                    else (_rights or "unbekannt")
            feat["rechte_inhaber"] = _rights
            feat["institution"]   = _inst or _plat or _rights
            feat["sammlung"]      = _coll
            feat["katalog_nr"]    = _catno
            feat["quell_url"]     = _occ_id   # direkte Quell-URL
            feat["ort"]           = rec.get("locality", "") or \
                                    rec.get("verbatimLocality", "")
            feat["bundesland"]    = rec.get("stateProvince", "")
            feat["verifikation"]  = rec.get("identificationVerificationStatus", "")
            feat["dataset_key"]   = rec.get("datasetKey", "")
            feat["genauigkeit_m"] = int(rec.get(
                "coordinateUncertaintyInMeters", 0) or 0)
            _bor = rec.get("basisOfRecord", "")
            _basis_de = {
                "HUMAN_OBSERVATION":   "Beobachtung",
                "MACHINE_OBSERVATION": "Maschine",
                "PRESERVED_SPECIMEN":  "Herbarbelege/Präparat",
                "LIVING_SPECIMEN":     "Lebendexemplar",
                "FOSSIL_SPECIMEN":     "Fossil",
                "MATERIAL_CITATION":   "Literaturzitat",
                "OCCURRENCE":          "Vorkommen",
                "LITERATURE":          "Literatur",
            }
            feat["basis"]         = _basis_de.get(_bor, _bor)
            feat["land"]          = rec.get("country", "")
            key = rec.get("key", "")
            feat["gbif_url"]      = f"https://www.gbif.org/occurrence/{key}" if key else ""
            # Katalog-Nr. mit Quell-URL erweitern falls vorhanden
            if _catno and _occ_id and not feat["katalog_nr"].startswith("http"):
                feat["katalog_nr"] = f"{_catno}"
            feat["jahr"]          = int(_ed[:4]) if _ed and len(_ed) >= 4 and _ed[:4].isdigit() else 0
            feats.append(feat)

        ok, _ = dp.addFeatures(feats)
        if not ok:
            self._log(f"  ⚠ addFeatures fehlgeschlagen: {dp.lastError()}")
        lyr.updateExtents()

        # Einfacher Stil: orangefarbene Punkte
        try:
            from qgis.PyQt.QtGui import QColor
            sym = lyr.renderer().symbol()
            sym.setColor(QColor(230, 100, 20))
            sym.setSize(2.5)
        except Exception:
            pass

        QgsProject.instance().addMapLayer(lyr)
        self._log(
            f"✓ Layer '{lyr_name}' geladen "
            f"({len(feats)} Punkte{', ' + str(skipped) + ' ohne Koord. übersprungen' if skipped else ''})")
        # Fehlende Datenquellen über GBIF Registry auflösen
        self._resolve_datasets(lyr)

        self._log(
            f"  Attribute: Art, Familie, Datum, Beobachter, "
            f"Datenquelle, Institution, Quell-URL, "
            f"Ort, Bestimmer, Beobachter-ID, Grundlage, GBIF-URL")
