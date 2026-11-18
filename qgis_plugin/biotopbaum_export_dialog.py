"""
biotopbaum_export_dialog.py
===========================
Export der Biotopbäume – derselbe Dialog wie für Fundpunkte Tiere
(fundpunkte_export_dialog.py), ergänzt um die Kindtabelle der Baumhöhlen.

  • GeoPackage: Layer »Biotopbaeume« (Punkte) + Tabelle »Baumhoehlen«.
    In den Feldern stehen die IDs der Referenzlisten (Abgabe an das LANUK).
  • XLSX: Blatt »Biotopbaeume« + Blatt »Baumhoehlen«.
  • CSV: <name>.csv + <name>_Baumhoehlen.csv.

Exportiert werden nur die Höhlen der exportierten Bäume (Verknüpfung über
die Projekt-Relation, sonst Baum_ObjektID → Objektid). Ist im Baum-Layer ein
Feld »Sensibel« vorhanden, gilt dieselbe Regel wie bei den Fundpunkten.
"""

import os

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsVectorFileWriter, QgsFeature,
    QgsCoordinateTransformContext, QgsWkbTypes,
)
from qgis.PyQt.QtWidgets import QCheckBox

from .fundpunkte_export_dialog import FundpunkteExportDialog, _fmt_val, _ist_null


# Klartext-Spalten für CSV/XLSX: Feld → (Referenzliste, [(neue Spalte, Listenspalte)])
# Schlüssel ist jeweils entityid (wie in den ValueRelations der Fachschale).
BAUM_LOOKUPS = {
    "baumart": ("Baeume_BAUM", [("Baumart_deutsch", "langname"),
                                ("Baumart_wiss",    "kurzname")]),
}
HOEHLEN_LOOKUPS = {
    "Baumhoehlen_Typ": ("Baumhoehlen", [("Baumhoehlen_Typ_Text", "kurzname")]),
}

# Rückfall, falls das Projekt keine Relation Baum → Höhlen enthält
HOEHLEN_LAYER   = "hoehlen"
HOEHLEN_FK      = "Baum_ObjektID"
BAUM_PK         = "Objektid"
HOEHLEN_AUSGABE = "Baumhoehlen"


def _feld(lyr, name):
    """Tatsächlicher Feldname (case-insensitiv, ohne Leerzeichen/Umbrüche)."""
    for f in lyr.fields():
        if f.name().strip().lower() == name.lower():
            return f.name()
    return None


class BiotopbaumExportDialog(FundpunkteExportDialog):

    TITEL           = "Biotopbäume – Export"
    INFO            = (
        "Exportiert die Biotopbäume samt Baumhöhlen in verschiedene Formate.\n"
        "GeoPackage: Bäume und Höhlen als zwei Tabellen in einer Datei,\n"
        "in den Feldern stehen die IDs der Referenzlisten.\n"
        "CSV/XLSX: Baumart und Höhlentyp optional zusätzlich im Klartext."
    )
    AUFLOESEN_LABEL = "Klartexte ergänzen (Baumart, Höhlentyp – nur CSV/XLSX)"
    GPKG_LAYER      = "Biotopbaeume"
    XLSX_BLATT      = "Biotopbaeume"
    DATEI_PREFIX    = "Biotopbaeume_Export"

    # ── Layer-Auswahl ────────────────────────────────────────────────────────

    @staticmethod
    def _passt_layer(lyr):
        # Am Datenmodell erkennen, nicht am Namen: »Baeume_BAUM« ist eine
        # Referenzliste, der Erfassungslayer heißt (Tippfehler) »Baueme«.
        return (lyr.isSpatial()
                and _feld(lyr, BAUM_PK) is not None
                and _feld(lyr, "baumart") is not None)

    def _weitere_optionen(self, opt_lo):
        self.hoehlen_check = QCheckBox("Baumhöhlen mitexportieren")
        self.hoehlen_check.setChecked(True)
        opt_lo.addRow("", self.hoehlen_check)

    # ── Klartexte ────────────────────────────────────────────────────────────

    @staticmethod
    def _ref_layer(name):
        for ref in QgsProject.instance().mapLayers().values():
            if isinstance(ref, QgsVectorLayer) and ref.name().lower() == name.lower():
                return ref
        return None

    def _build_lookup(self):
        """{Feld: {entityid: [Klartexte]}} für Bäume und Höhlen."""
        lookup = {}
        for feld, (liste, spalten) in {**BAUM_LOOKUPS, **HOEHLEN_LOOKUPS}.items():
            ref = self._ref_layer(liste)
            if ref is None:
                self._log(f"ℹ Referenzliste »{liste}« nicht im Projekt – "
                          f"keine Klartexte für {feld}.")
                continue
            werte = {}
            for f in ref.getFeatures():
                eid = self._schluessel(f.attribute("entityid"))
                if not eid:
                    continue
                werte[eid] = [_fmt_val(f.attribute(sp)) if sp in ref.fields().names()
                                   else "" for _neu, sp in spalten]
            lookup[feld] = werte
        return lookup

    @staticmethod
    def _schluessel(val):
        """entityid-Vergleich unabhängig von int/float/text (z. B. 3453 vs. '3453')."""
        if _ist_null(val):
            return ""
        if isinstance(val, float) and val.is_integer():
            val = int(val)
        return str(val).strip()

    def _tabelle(self, lyr, feats, felder, lookups, lookup, wkt):
        """Header + Zeilen; Klartextspalten direkt hinter dem jeweiligen Feld."""
        header, plan = [], []
        for f in felder:
            name = f.name()
            header.append(name.strip())
            plan.append((name, None))
            key = name.strip()
            if self.art_check.isChecked() and key in lookups and key in lookup:
                for i, (neu, _sp) in enumerate(lookups[key][1]):
                    header.append(neu)
                    plan.append((name, (key, i)))
        if wkt:
            header.append("WKT")

        rows = []
        for feat in feats:
            row = []
            for name, aufl in plan:
                val = feat.attribute(name)
                if aufl is None:
                    row.append(_fmt_val(val))
                else:
                    key, i = aufl
                    texte = lookup[key].get(self._schluessel(val))
                    row.append(texte[i] if texte else "")
            if wkt:
                geom = feat.geometry()
                row.append(geom.asWkt(2) if geom else "")
            rows.append(row)
        return header, rows

    def _rows(self, lyr, feats, art_lookup):
        flag = self._resolve_flag_field(lyr)
        felder = [f for f in lyr.fields()
                  if f.name() != flag
                  and (self.field_checks.get(f.name()) is None
                       or self.field_checks[f.name()].isChecked())]
        return self._tabelle(lyr, feats, felder, BAUM_LOOKUPS, art_lookup,
                             self.geom_check.isChecked())

    # ── Baumhöhlen ───────────────────────────────────────────────────────────

    def _hoehlen(self, lyr, feats):
        """(Höhlen-Layer, [Features]) der exportierten Bäume oder (None, [])."""
        if not self.hoehlen_check.isChecked():
            return None, []

        kind, fk, pk = None, None, None
        for rel in QgsProject.instance().relationManager().referencedRelations(lyr):
            paare = rel.fieldPairs()          # {referencingField: referencedField}
            if rel.referencingLayer() and len(paare) == 1:
                kind = rel.referencingLayer()
                fk, pk = next(iter(paare.items()))
                break
        if kind is None:
            for cand in QgsProject.instance().mapLayers().values():
                if (isinstance(cand, QgsVectorLayer)
                        and cand.name().lower() == HOEHLEN_LAYER
                        and _feld(cand, HOEHLEN_FK)):
                    kind, fk, pk = cand, _feld(cand, HOEHLEN_FK), _feld(lyr, BAUM_PK)
                    break
        if kind is None or pk is None:
            self._log("ℹ Keine Baumhöhlen-Tabelle im Projekt gefunden – "
                      "nur die Bäume werden exportiert.")
            return None, []

        ids = {self._schluessel(f.attribute(pk)) for f in feats}
        ids.discard("")
        kinder = [f for f in kind.getFeatures()
                  if self._schluessel(f.attribute(fk)) in ids]
        return kind, kinder

    def _hoehlen_tabelle(self, kind, kinder, lookup):
        felder = [f for f in kind.fields() if f.name().lower() != "fid"]
        return self._tabelle(kind, kinder, felder, HOEHLEN_LOOKUPS, lookup, False)

    def _csv_weitere(self, lyr, path, feats, art_lookup):
        kind, kinder = self._hoehlen(lyr, feats)
        if kind is None:
            return
        stamm, ext = os.path.splitext(path)
        ziel = f"{stamm}_{HOEHLEN_AUSGABE}{ext or '.csv'}"
        header, rows = self._hoehlen_tabelle(kind, kinder, art_lookup)
        try:
            self._csv_schreiben(ziel, header, rows)
            self._log(f"✓ CSV: {len(rows)} Baumhöhlen → {ziel}")
        except Exception as e:
            self._log(f"✗ Fehler Baumhöhlen: {e}")

    def _xlsx_weitere(self, wb, lyr, feats, art_lookup):
        kind, kinder = self._hoehlen(lyr, feats)
        if kind is None:
            return
        header, rows = self._hoehlen_tabelle(kind, kinder, art_lookup)
        self._xlsx_blatt(wb.create_sheet(HOEHLEN_AUSGABE), header, rows)
        self._log(f"✓ XLSX: {len(rows)} Baumhöhlen im Blatt »{HOEHLEN_AUSGABE}«")

    def _gpkg_weitere(self, lyr, path, feats):
        kind, kinder = self._hoehlen(lyr, feats)
        if kind is None:
            return
        # Gefilterte Höhlen in einen Memory-Layer kopieren, damit der Original-
        # Layer unberührt bleibt (Subset-String scheitert im Bearbeitungsmodus).
        felder = [f for f in kind.fields() if f.name().lower() != "fid"]
        if kind.isSpatial():
            uri = (f"{QgsWkbTypes.displayString(kind.wkbType())}"
                   f"?crs={kind.crs().authid()}")
        else:
            uri = "None"
        tmp = QgsVectorLayer(uri, HOEHLEN_AUSGABE, "memory")
        prov = tmp.dataProvider()
        prov.addAttributes(felder)
        tmp.updateFields()
        neu = []
        for f in kinder:
            nf = QgsFeature(tmp.fields())
            nf.setAttributes([f.attribute(fd.name()) for fd in felder])
            if kind.isSpatial():
                nf.setGeometry(f.geometry())
            neu.append(nf)
        prov.addFeatures(neu)

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName   = "GPKG"
        options.layerName    = HOEHLEN_AUSGABE
        options.fileEncoding = "UTF-8"
        options.actionOnExistingFile = \
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
        err, msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
            tmp, path, QgsCoordinateTransformContext(), options)
        if err == QgsVectorFileWriter.WriterError.NoError:
            self._log(f"✓ GPKG: {len(neu)} Baumhöhlen → Tabelle »{HOEHLEN_AUSGABE}«")
        else:
            self._log(f"✗ GPKG-Fehler Baumhöhlen: {msg}")
