"""
papierreviere_export_dialog.py
==============================
Transformiert die Mittelpunkte (Centroids) der Papierreviere aus der
Brutvogel-Fachschale in Fundpunkte-Einträge (Fund-Layer).

Mapping:
  Papierreviere.Vogel_Art  → Artname (via wiss. Name / dt. Name in Referenzen)
  Papierreviere.Anzahl     → Anzahl
  Papierreviere.Bemerkung  → Bemerkung
  Centroid(geom)           → geom (Point)
  Artengruppe              → '165844'  (Vögel)
  Kartierer/Institution    → aus Projektvariablen
"""

import os

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QDialogButtonBox,
    QProgressBar, QTextEdit, QComboBox, QCheckBox, QSpinBox,
)
from qgis.PyQt.QtCore import Qt
import uuid as _uuid
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsExpressionContextUtils,
)

_PLUGIN_DIR = os.path.dirname(__file__)

# listitemid der Vogelgruppe in Referenzen.gpkg
VOEGEL_LISTITEMID = "165844"

# Sinnvolle Defaults (entityid) für Pflichtfelder
DEFAULT_STATUS      = 42734    # "keine Angabe"
DEFAULT_STADIUM     = 139716   # "keine Angabe"
DEFAULT_ZAEHLEINHEIT= 139718   # "Individuen / Einzeltiere"



def _normalize(s):
    """Normalisiert Text für Fuzzy-Vergleich:
    Kleinschreibung, ae→ä, oe→ö, ue→ü, ß→ss, Sonderzeichen weg.
    """
    s = s.lower().strip()
    # Umlaute normalisieren (beide Richtungen)
    s = s.replace("ae", "ä").replace("oe", "ö").replace("ue", "ü")
    s = s.replace("ß", "ss")
    return s


def _levenshtein(a, b):
    """Levenshtein-Distanz zwischen zwei Strings (iterativ, O(n*m))."""
    if a == b: return 0
    if not a:  return len(b)
    if not b:  return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(
                prev[j + 1] + 1,          # Löschung
                curr[j]     + 1,          # Einfügung
                prev[j]     + (ca != cb)  # Ersetzung
            ))
        prev = curr
    return prev[-1]


def _fuzzy_match(query, lookup, max_dist=2):
    """
    Findet den besten Treffer in lookup {norm_name → entityid}.
    Reihenfolge: exakt → enthält → Levenshtein ≤ max_dist.
    Gibt (entityid, matched_term, distance) zurück oder ("", "", -1).
    """
    q = _normalize(query)
    if not q:
        return "", "", -1
    # 1. Exakter Treffer
    if q in lookup:
        return lookup[q][0], lookup[q][1], 0
    # 2. Enthält-Treffer (Kurzname in vollem Namen)
    for norm, (eid, orig) in lookup.items():
        if q in norm or norm in q:
            return eid, orig, 0
    # 3. Levenshtein – besten Treffer suchen
    best_dist = max_dist + 1
    best_eid  = ""
    best_term = ""
    for norm, (eid, orig) in lookup.items():
        d = _levenshtein(q, norm)
        if d < best_dist:
            best_dist, best_eid, best_term = d, eid, orig
    if best_dist <= max_dist:
        return best_eid, best_term, best_dist
    return "", "", -1


class PapierreviereExportDialog(QDialog):


    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Papierreviere → Fundpunkte")
        self.setMinimumWidth(500)
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.addWidget(QLabel(
            "Berechnet den Mittelpunkt jedes Papierreviers und legt\n"
            "einen Fundpunkt-Eintrag im aktiven Fund-Layer an.\n\n"
            "Voraussetzung: Beide Layer (Papierreviere und Fund) müssen\n"
            "im aktuellen Projekt geladen sein."
        ))

        form = QFormLayout()

        # Quell-Layer Papierreviere
        self.src_combo = QComboBox()
        self._fill_combo(self.src_combo, geom_types=["Polygon", "MultiPolygon"])
        form.addRow("Papierreviere-Layer:", self.src_combo)

        # Ziel-Layer Fund
        self.dst_combo = QComboBox()
        self._fill_combo(self.dst_combo, name_hint="Fund")
        form.addRow("Fund-Layer (Ziel):", self.dst_combo)

        # Referenz-Layer Arten
        self.ref_combo = QComboBox()
        self._fill_combo(self.ref_combo, name_hint="Arten")
        form.addRow("Arten-Referenz-Layer:", self.ref_combo)

        # Standardwerte für ValueRelation-Felder
        self.status_combo      = QComboBox()
        self.status_combo.setObjectName("status_combo")
        self.stadium_combo     = QComboBox()
        self.zaehleinheit_combo= QComboBox()
        self._fill_ref_combo(self.status_combo,       "Status",     DEFAULT_STATUS)
        self._fill_ref_combo(self.stadium_combo,      "Geschlecht", DEFAULT_STADIUM)
        self._fill_ref_combo(self.zaehleinheit_combo, "Einheit",    DEFAULT_ZAEHLEINHEIT)
        form.addRow("Status (Standard):",       self.status_combo)
        form.addRow("Stadium (Standard):",      self.stadium_combo)
        form.addRow("Zähleinheit (Standard):",  self.zaehleinheit_combo)

        # Optionen
        self.skip_no_art = QCheckBox("Reviere ohne Artname überspringen")
        self.skip_no_art.setChecked(True)
        form.addRow("", self.skip_no_art)

        self.use_utm = QCheckBox("UTM-Koordinaten (Utm_east / Utm_north) setzen")
        self.use_utm.setChecked(True)
        form.addRow("", self.use_utm)

        lo.addLayout(form)

        # Log
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(180)
        lo.addWidget(self.log)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lo.addWidget(self.bar)

        bb = QDialogButtonBox()
        self.run_btn = bb.addButton("Transformieren", QDialogButtonBox.ButtonRole.AcceptRole)
        self.run_btn.clicked.connect(self._run)
        bb.addButton("Schließen", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        lo.addWidget(bb)

    def _fill_combo(self, combo, geom_types=None, name_hint=None):
        combo.clear()
        for lyr in QgsProject.instance().mapLayers().values():
            if not isinstance(lyr, QgsVectorLayer):
                continue
            if geom_types:
                gtype = lyr.geometryType().name if hasattr(lyr.geometryType(), 'name') else str(lyr.geometryType())
                wkb = lyr.wkbType()
                # Polygon-Check
                geom_ok = any(gt.lower() in str(wkb).lower() for gt in geom_types) or \
                          lyr.geometryType() == 2  # Polygon = 2
                if not geom_ok:
                    continue
            combo.addItem(lyr.name(), lyr)

        # Vorauswahl per Name-Hinweis
        if name_hint:
            for i in range(combo.count()):
                if name_hint.lower() in combo.itemText(i).lower():
                    combo.setCurrentIndex(i)
                    break

    def _fill_ref_combo(self, combo, layer_name, default_eid):
        """Befüllt ein editierbares ComboBox mit Fuzzy-Suche (Levenshtein)."""
        from qgis.PyQt.QtWidgets import QCompleter
        from qgis.PyQt.QtCore import QStringListModel, Qt

        combo.clear()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

        for lyr in QgsProject.instance().mapLayers().values():
            if not isinstance(lyr, QgsVectorLayer): continue
            if lyr.name().lower() != layer_name.lower(): continue
            for f in lyr.getFeatures():
                eid  = f.attribute("entityid")
                term = f.attribute("term") or ""
                combo.addItem(term, eid)
            break

        # QCompleter mit MatchContains
        terms = [combo.itemText(i) for i in range(combo.count())]
        completer = QCompleter(terms, combo)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        combo.setCompleter(completer)

        # Vorauswahl auf Default setzen
        for i in range(combo.count()):
            if combo.itemData(i) == default_eid:
                combo.setCurrentIndex(i)
                break

        # Beim Tippen: Levenshtein-Fallback wenn kein MatchContains-Treffer
        combo._all_terms = list(zip(terms,
                                    [combo.itemData(i) for i in range(combo.count())]))
        combo.lineEdit().textEdited.connect(
            lambda text, cb=combo: self._fuzzy_combo_update(cb, text)
        )

    def _fuzzy_combo_update(self, combo, text):
        """Wählt via Levenshtein den besten Treffer wenn kein exakter Match."""
        if not text.strip(): return
        # Prüfe ob ein exakter Contains-Treffer existiert
        t = text.lower()
        for term, eid in combo._all_terms:
            if t in term.lower():
                return   # Completer kümmert sich darum
        # Kein Contains-Treffer → Levenshtein über normalisierte Strings
        q = _normalize(text)
        best_dist = 3; best_idx = -1
        for i, (term, eid) in enumerate(combo._all_terms):
            d = _levenshtein(q, _normalize(term))
            if d < best_dist:
                best_dist, best_idx = d, i
        if best_idx >= 0:
            # Popup mit bestem Treffer füllen
            combo.completer().setCompletionPrefix(
                combo._all_terms[best_idx][0]
            )
            combo.completer().complete()

    def _resolve_combo_eid(self, combo):
        """Gibt die entityid des aktuell gewählten/getippten Combo-Eintrags zurück.
        Bei editierbarem Combo: Fuzzy-Match auf eingetippten Text.
        """
        # Wenn Index gültig und Text passt → direkter Wert
        idx = combo.currentIndex()
        if idx >= 0 and combo.currentText() == combo.itemText(idx):
            return combo.itemData(idx)
        # Freier Text → Fuzzy-Match
        text = combo.currentText().strip()
        if not text: return combo.itemData(0)
        lookup = {_normalize(term): (str(eid), term)
                  for term, eid in combo._all_terms}
        eid, matched, dist = _fuzzy_match(text, lookup)
        if eid:
            if dist > 0:
                self._log(f"  ~ {combo.objectName()} '{text}' → '{matched}' (Lev={dist})")
            return int(eid) if eid.isdigit() else eid
        # Kein Treffer → ersten Eintrag (keine Angabe)
        return combo.itemData(0)

    def _log(self, msg):
        self.log.append(msg)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _run(self):
        self.run_btn.setEnabled(False)
        self.log.clear()

        src_lyr = self.src_combo.currentData()
        dst_lyr = self.dst_combo.currentData()
        ref_lyr = self.ref_combo.currentData()

        if not src_lyr or not dst_lyr:
            self._log("⚠ Bitte Quell- und Ziel-Layer auswählen.")
            self.run_btn.setEnabled(True)
            return

        # Projektvariablen
        proj = QgsProject.instance()
        kartierer_name   = QgsExpressionContextUtils.projectScope(proj).variable("kartierer")   or ""
        institution_name = QgsExpressionContextUtils.projectScope(proj).variable("institution") or ""

        # Institution: term → entityid (Fund.Institution speichert entityid)
        institution_eid = institution_name   # Fallback: Name falls kein Lookup
        kartierer_eid   = kartierer_name
        for ref in QgsProject.instance().mapLayers().values():
            if isinstance(ref, QgsVectorLayer) and ref.name().lower() == "institution":
                for rf in ref.getFeatures():
                    if (rf.attribute("term") or "").strip() == institution_name.strip():
                        institution_eid = rf.attribute("entityid")
                        break
                break

        # Referenz aufbauen: wiss_name / Name_deutsch → entityid
        art_lookup = {}   # _normalize(name) → (entityid, orig_term)
        if ref_lyr:
            for feat in ref_lyr.getFeatures():
                eid  = str(feat.attribute("entityid") or "")
                wiss = (feat.attribute("term")         or "").strip()
                de   = (feat.attribute("Name_deutsch") or "").strip()
                if wiss: art_lookup[_normalize(wiss)] = (eid, wiss)
                if de:   art_lookup[_normalize(de)]   = (eid, de)

        # CRS-Transformation Source → Ziel
        src_crs = src_lyr.crs()
        dst_crs = dst_lyr.crs()
        transform = QgsCoordinateTransform(src_crs, dst_crs, proj)

        # Ziel-Felder
        dst_fields = dst_lyr.fields()

        total   = src_lyr.featureCount()
        created = 0
        skipped = 0

        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(0)
        self.bar.setVisible(True)

        dst_lyr.startEditing()

        for i, pr_feat in enumerate(src_lyr.getFeatures()):
            self.bar.setValue(i + 1)

            # Centroid berechnen + transformieren
            centroid_geom = pr_feat.geometry().centroid()
            if dst_crs != src_crs:
                centroid_geom.transform(transform)

            # Artname aus Papierreviere
            vogel_art_raw = (pr_feat.attribute("Vogel_Art") or "").strip()
            if not vogel_art_raw and self.skip_no_art.isChecked():
                skipped += 1
                continue

            art_eid, matched_term, lev_dist = _fuzzy_match(vogel_art_raw, art_lookup)
            if not art_eid:
                self._log(f"  ⚠ Art '{vogel_art_raw}' – kein Treffer, leer gesetzt")
            elif lev_dist > 0:
                self._log(f"  ~ '{vogel_art_raw}' → '{matched_term}' (Levenshtein={lev_dist})")

            # Neuen Fund-Eintrag anlegen
            new_feat = QgsFeature(dst_fields)
            new_feat.setGeometry(centroid_geom)

            def _set(name, val):
                idx = dst_fields.indexFromName(name)
                if idx >= 0:
                    new_feat.setAttribute(idx, val)

            _set("Kennung",         str(_uuid.uuid4()))  # UUID generieren
            _set("Status",          self._resolve_combo_eid(self.status_combo))
            _set("Stadium",         self._resolve_combo_eid(self.stadium_combo))
            _set("Zaehleinheit",    self._resolve_combo_eid(self.zaehleinheit_combo))
            _set("Artname",         art_eid)
            _set("Artname_deutsch", pr_feat.attribute("Vogel_Art") or "")
            _set("Artengruppe",     VOEGEL_LISTITEMID)
            _set("Anzahl",          pr_feat.attribute("Anzahl"))
            _set("Bemerkung",       pr_feat.attribute("Bemerkung") or "")
            _set("Kartierer",       kartierer_name)   # Text-Feld
            _set("Institution",     institution_eid)  # entityid (ValueRelation-Key)

            if self.use_utm.isChecked():
                pt = centroid_geom.asPoint()
                # UTM32 falls Ziel bereits EPSG:25832
                if dst_crs.authid() == "EPSG:25832":
                    _set("Utm_east",  round(pt.x(), 1))
                    _set("Utm_north", round(pt.y(), 1))
                else:
                    utm_crs   = QgsCoordinateReferenceSystem("EPSG:25832")
                    utm_xform = QgsCoordinateTransform(dst_crs, utm_crs, proj)
                    utm_geom  = QgsGeometry(centroid_geom)
                    utm_geom.transform(utm_xform)
                    utm_pt    = utm_geom.asPoint()
                    _set("Utm_east",  round(utm_pt.x(), 1))
                    _set("Utm_north", round(utm_pt.y(), 1))

            dst_lyr.addFeature(new_feat)
            created += 1

        dst_lyr.commitChanges()
        self.bar.setValue(total)

        self._log(f"\n✓ {created} Fundpunkte angelegt  |  {skipped} übersprungen")
        self.run_btn.setEnabled(True)
