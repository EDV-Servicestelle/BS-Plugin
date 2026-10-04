# NRW Brutvogel Artsuche – QField Plugin

**Biologische Station Kreis Wesel e.V.** · blinn@bskw.de

---

## Installation

### Als Projekt-Plugin (empfohlen)

Das Plugin muss **gleich heißen wie die Projektdatei**, nur mit `.qml`-Endung:

```
Projektdatei:  QFS_bv.qgz
Plugin:        QFS_bv.qml   ← main.qml umbenennen
               search.qml   ← bleibt so
```

Beide Dateien liegen **neben der Projektdatei** im gleichen Verzeichnis.

**Via QFieldCloud** wird das Plugin automatisch mit dem Projekt paketiert und auf alle Geräte verteilt.

### Manuelle Installation auf dem Gerät

Alternativ neben die `.qgz`-Datei kopieren (USB / Datei-Manager).

---

## Funktionen

### 1. Artname-Suche in der QField-Suchleiste

Präfix: **`va`** (Vogelart)

```
va Ro        → Rotkehlchen, Rohrammer, Rotmilan …
va Turdus    → alle Turdus-Arten (wissenschaftlicher Name)
va Rb        → Rotkehlchen (Kürzel)
```

Ergebnis-Auswahl trägt die Art automatisch in das aktive `Vogel_Art`-Feld ein.

### 2. Schnellzugriff-Panel

Toolbar-Button (🔍) öffnet das Panel mit:
- **Suchfeld** (Deutsch / Wissenschaftlich / Kürzel)
- **Gruppenfilter-Buttons**: Alle · Enten · Greife · Eulen · Spechte · Singvögel · Watvögel
- **Artenliste** – Tippen → Art wird in `Vogel_Art` eingetragen

---

## Technische Details

| Datei | Funktion |
|---|---|
| `main.qml` | UI: Panel, Toolbar-Button, Gruppenfilter |
| `search.qml` | Locator-Suche (läuft im Hintergrundthread) |
| `metadata.txt` | Plugin-Metadaten |

**Voraussetzungen:** QField ≥ 3.3, Layer `Referenzliste_Arten` im Projekt geladen.

---

## Gruppenfilter anpassen

In `main.qml`, Array `gruppen`:

```qml
property var gruppen: [
    { label: "Alle",    icon: "★", filter: "" },
    { label: "Enten",   icon: "🦆", filter: "Ente" },
    // weitere Gruppen: filter = Regex gegen deutschen Namen
]
```
