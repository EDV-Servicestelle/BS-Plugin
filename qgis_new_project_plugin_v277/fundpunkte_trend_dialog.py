"""
Fundpunkte Tiere – Fundhäufigkeit
===================================
Zeitreihen-Diagramm für Fund-Layer.
Öffnet interaktives Chart.js-Diagramm im Standard-Browser.
Kein Qt WebEngine nötig.
"""

import os, json, tempfile, webbrowser
from collections import defaultdict

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QComboBox, QPushButton, QGroupBox,
    QDialogButtonBox, QListWidget, QListWidgetItem,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _get_art(feat):
    """Artname aus Feature lesen – Fallback-Kette."""
    for field in ("Artname_wiss", "Artname_deutsch", "Artname", "ARTNAME"):
        try:
            v = feat[field]
            if v and str(v).strip() and str(v).upper() != "NULL":
                return str(v).strip()
        except Exception:
            pass
    return ""


def _get_datum(feat):
    """Beobachtungsdatum lesen – Fallback auf Aenderungsdatum."""
    for field in ("Beobachtungsdatum", "K_DATUM", "Datum", "DATUM",
                  "Aenderungsdatum"):
        try:
            v = feat[field]
            if v and str(v).strip() and str(v).upper() not in ("NULL", ""):
                s = str(v).strip()
                # ISO-Datum oder Jahreszahl
                if len(s) >= 4 and s[:4].isdigit():
                    return s
        except Exception:
            pass
    return ""


# ── Daten aggregieren ─────────────────────────────────────────────────────────

def aggregate_fund_trends(layer, species_list, group_by="year", value="count"):
    """
    Aggregiert Funde zeitlich.
    Gibt zurück: ({art: {periode: wert}}, sortierte Perioden-Liste)
    """
    data        = defaultdict(lambda: defaultdict(int))
    all_periods = set()
    skipped     = 0

    for feat in layer.getFeatures():
        art   = _get_art(feat)
        datum = _get_datum(feat)

        if not art or not datum:
            skipped += 1
            continue
        if species_list and art not in species_list:
            continue

        try:
            year  = int(datum[:4])
            month = int(datum[5:7]) if len(datum) >= 7 else 1
        except (ValueError, IndexError):
            skipped += 1
            continue

        if   group_by == "year":   period = str(year)
        elif group_by == "month":  period = f"{year}-{month:02d}"
        else:                      period = f"{(year // 10) * 10}er"

        try:
            anzahl = int(feat["Anzahl"] or 0) or 1
        except Exception:
            anzahl = 1

        data[art][period] += anzahl if value == "sum" else 1
        all_periods.add(period)

    return dict(data), sorted(all_periods), skipped


# ── HTML-Chart ────────────────────────────────────────────────────────────────

def build_chart_html(data, periods, title, y_label):
    colors = [
        "#2196F3","#4CAF50","#FF5722","#9C27B0","#FF9800",
        "#00BCD4","#E91E63","#8BC34A","#607D8B","#F44336",
        "#3F51B5","#009688",
    ]
    datasets = []
    for i, (art, values) in enumerate(data.items()):
        c = colors[i % len(colors)]
        datasets.append({
            "label": art,
            "data":  [values.get(p, 0) for p in periods],
            "borderColor": c,
            "backgroundColor": c + "33",
            "tension": 0.3, "fill": False,
            "pointRadius": 4, "pointHoverRadius": 7,
        })
    cd = json.dumps({"labels": periods, "datasets": datasets},
                    ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
body{{margin:0;padding:12px;background:#fafafa;font-family:sans-serif;}}
h3{{margin:4px 0 12px;font-size:14px;color:#333;}}
.w{{position:relative;height:calc(100vh - 60px);}}
</style></head><body>
<h3>{title}</h3><div class="w"><canvas id="c"></canvas></div>
<script>
new Chart(document.getElementById('c').getContext('2d'),{{
  type:'line', data:{cd},
  options:{{
    responsive:true, maintainAspectRatio:false,
    interaction:{{mode:'index',intersect:false}},
    plugins:{{legend:{{position:'top',labels:{{boxWidth:12,font:{{size:11}}}}}}}},
    scales:{{
      x:{{ticks:{{maxRotation:60,font:{{size:10}}}}}},
      y:{{beginAtZero:true,
         title:{{display:true,text:'{y_label}'}},
         ticks:{{font:{{size:10}}}}}}
    }}
  }}
}});
</script></body></html>"""


# ── Dialog ────────────────────────────────────────────────────────────────────

class FundpunkteTrendDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fundpunkte Tiere – Fundhäufigkeit")
        self.setMinimumWidth(420)
        self._build_ui()
        self._populate_layers()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        lf = QFormLayout()
        self.layer_combo = QComboBox()
        self.layer_combo.currentIndexChanged.connect(self._on_layer_changed)
        lf.addRow("Fund-Layer:", self.layer_combo)
        layout.addLayout(lf)

        opt_box = QGroupBox("Optionen")
        of = QFormLayout()
        self.group_combo = QComboBox()
        self.group_combo.addItem("Jahr",      "year")
        self.group_combo.addItem("Monat",     "month")
        self.group_combo.addItem("Jahrzehnt", "decade")
        self.value_combo = QComboBox()
        self.value_combo.addItem("Anzahl Datensätze", "count")
        self.value_combo.addItem("Summe Anzahl",      "sum")
        of.addRow("Gruppierung:", self.group_combo)
        of.addRow("Wert:",        self.value_combo)
        opt_box.setLayout(of)
        layout.addWidget(opt_box)

        art_box = QGroupBox("Arten (mehrfach auswählen)")
        av = QVBoxLayout()
        self.species_list = QListWidget()
        self.species_list.setSelectionMode(
            QListWidget.SelectionMode.MultiSelection)
        self.species_list.setMinimumHeight(180)
        av.addWidget(self.species_list)
        sel_row = QHBoxLayout()
        sel_all  = QPushButton("Alle");  sel_all.setFixedHeight(24)
        sel_none = QPushButton("Keine"); sel_none.setFixedHeight(24)
        sel_all.clicked.connect(self.species_list.selectAll)
        sel_none.clicked.connect(self.species_list.clearSelection)
        sel_row.addWidget(sel_all); sel_row.addWidget(sel_none)
        av.addLayout(sel_row)
        art_box.setLayout(av)
        layout.addWidget(art_box)

        self.info_label = QLabel(
            "Das Diagramm wird im Standard-Webbrowser geöffnet.")
        self.info_label.setStyleSheet("color:gray;font-size:11px;")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        btn_box = QDialogButtonBox()
        self.chart_btn = btn_box.addButton(
            "Diagramm öffnen", QDialogButtonBox.ButtonRole.AcceptRole)
        close_btn = btn_box.addButton(
            "Schließen", QDialogButtonBox.ButtonRole.RejectRole)
        self.chart_btn.clicked.connect(self._open_chart)
        close_btn.clicked.connect(self.reject)
        layout.addWidget(btn_box)

    def _populate_layers(self):
        """Alle Punkt-Layer mit Artname-Feld aufnehmen."""
        self.layer_combo.clear()
        for lyr in QgsProject.instance().mapLayers().values():
            if not isinstance(lyr, QgsVectorLayer):
                continue
            fields = [lyr.fields().at(i).name()
                      for i in range(lyr.fields().count())]
            has_art  = any(f in fields for f in
                           ("Artname_wiss","Artname_deutsch","Artname","ARTNAME"))
            has_date = any(f in fields for f in
                           ("Beobachtungsdatum","K_DATUM","Datum","DATUM",
                            "Aenderungsdatum"))
            if has_art and has_date:
                self.layer_combo.addItem(lyr.name(), lyr)
        for i in range(self.layer_combo.count()):
            if "fund" in self.layer_combo.itemText(i).lower():
                self.layer_combo.setCurrentIndex(i); break
        self._on_layer_changed()

    def _on_layer_changed(self):
        lyr = self.layer_combo.currentData()
        if lyr is None:
            return
        species = set()
        for feat in lyr.getFeatures():
            art = _get_art(feat)
            if art:
                species.add(art)
        self.species_list.clear()
        for art in sorted(species):
            self.species_list.addItem(QListWidgetItem(art))
        self.species_list.selectAll()
        n = self.species_list.count()
        self.info_label.setText(
            f"{n} Arten gefunden. "
            "Das Diagramm wird im Standard-Webbrowser geöffnet.")

    def _open_chart(self):
        lyr = self.layer_combo.currentData()
        if lyr is None:
            self.info_label.setText("⚠ Kein Layer gewählt."); return

        selected = [self.species_list.item(i).text()
                    for i in range(self.species_list.count())
                    if self.species_list.item(i).isSelected()]
        if not selected:
            self.info_label.setText("⚠ Bitte mindestens eine Art wählen.")
            return

        warn = ""
        if len(selected) > 12:
            counts = {}
            for feat in lyr.getFeatures():
                art = _get_art(feat)
                if art in selected:
                    counts[art] = counts.get(art, 0) + 1
            selected = sorted(counts, key=counts.get, reverse=True)[:12]
            warn = f" (Top 12 von {len(selected)} gewählten)"

        group_by = self.group_combo.currentData()
        value    = self.value_combo.currentData()
        y_label  = "Anzahl Datensätze" if value == "count" else "Summe Anzahl"

        data, periods, skipped = aggregate_fund_trends(
            lyr, selected, group_by, value)

        if not data or not periods:
            self.info_label.setText(
                f"⚠ Keine auswertbaren Daten gefunden "
                f"({skipped} Datensätze ohne Datum/Artname übersprungen).")
            return

        grp_label = {"year": "Jahr", "month": "Monat", "decade": "Jahrzehnt"}
        title = (f"Fundhäufigkeit nach {grp_label[group_by]}"
                 f" – {len(selected)} Arten{warn}")
        html = build_chart_html(data, periods, title, y_label)

        tmp = tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8")
        tmp.write(html)
        tmp.close()
        url = "file:///" + tmp.name.replace("\\", "/")
        webbrowser.open(url)
        skip_info = f"  ({skipped} ohne Datum übersprungen)" if skipped else ""
        self.info_label.setText(f"✓ Diagramm geöffnet.{skip_info}")
