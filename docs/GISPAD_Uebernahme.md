# GISPAD-Exporte übernehmen

Werkzeuge, um GISPAD-Daten aus einem File-Geodatabase-Export in GeoPackages
zu überführen — **ohne GISPAD, ohne ODBC-Treiber, ohne Access**. Gelesen wird
die `.gdb` direkt über GDALs `OpenFileGDB`-Treiber, der in QGIS enthalten ist.

## Warum

GISPAD lässt sich nicht mehr dauerhaft betreiben (ODBC-Treiber und alte
Windows-Kernel-Funktionen; con terra kann es nicht weiter unterstützen). Was
nicht aus den Projekten herausgeholt wird, ist danach nicht mehr zugänglich.
Diese Werkzeuge sind deshalb in erster Linie eine **Sicherungsfunktion** und
erst in zweiter Linie eine Arbeitserleichterung.

## Für die Stationen: der Menüpunkt

*Erweiterungen → Fundpunkte Tiere → **GISPAD-Export übernehmen …***

Der Dialog führt in drei Schritten:

1. **Export wählen** — zwei Knöpfe: *Ordner …* für einen ausgepackten
   Export, *ZIP-Datei …* für einen gepackten. Beide sind nötig, weil Qt
   zwei Dateidialoge hat: Im Ordnerdialog sind Dateien nicht zu sehen, im
   Dateidialog keine Ordner.

   Erkannt wird der Export durch *Öffnen*, nicht am Namen. Gesucht wird im
   gewählten Ordner, im Ordner darüber (falls man hineinnavigiert ist) und
   eine Ebene darunter — ausgepackt wie gepackt; bei mehreren Treffern
   fragt das Plugin nach. Das Plugin sieht dann selbst nach, was darin
   steckt, und zeigt es an.
2. **Was übernommen wird** — voreingestellt ist *Alles sichern*. Die
   fachliche Auswahl einer Objektklasse ist die Zusatzoption, nicht
   umgekehrt: Was jetzt nicht herausgeholt wird, ist später nicht mehr
   zugänglich. Dazu kommt der *kuratierte Biotoptypen-Layer* (siehe unten),
   wenn im Export Biotoptypen stecken.
3. **Zieldatei** — wird neben dem Export vorgeschlagen. Auf Wunsch landen
   die Layer anschließend direkt in QGIS.

Die Übernahme läuft im Hintergrund, QGIS bleibt bedienbar.

### Der kuratierte Biotoptypen-Layer

Die Fachauswahl gibt wieder, was im Export steht. Der kuratierte Layer ist
das, was man einer Station in die Hand gibt: zwölf Spalten mit sprechenden
Anzeigenamen, Wahrheitswerte als Text, und keine Platzhalter, die wie
Inhalte aussehen.

| Feld | Anzeigename | Herkunft |
|---|---|---|
| `KENNUNG` | Objektkennung | Geometrielayer |
| `BT_CODE` | Biotoptyp (Code) | `BtypHtyp.Biotoptyp` |
| `BT_TEXT` | Biotoptyp | OSIRIS-Liste 13 |
| `FL_HA` | Fläche (ha) | Geometrielayer, auf 4 Stellen gerundet |
| `LR_Typ` | Lebensraumtyp (Code) | `BtypHtyp.Oekotyp` |
| `LR_Typ_Text` | Lebensraumtyp | OSIRIS-Liste 19 |
| `FFH_LRT` | FFH-Lebensraumtyp? | `BtypHtyp.ist_FFHLRT`, als Ja/Nein |
| `P62` | § 62 geschützt? | `BtypHtyp.ist_P62_typ`, als Ja/Nein |
| `P62_Typ` | §-62-Biotoptyp | `BtypHtyp.P62_Typ` |
| `Zusatzcodes` | Zusatzcodes (Code) | Tabelle `Zusatzcodes`, aggregiert |
| `Zusatzcodes_Text` | Zusatzcodes (Klartext) | OSIRIS-Liste 14 |
| `Ohne_BT_Code` | ohne Biotoptyp | abgeleitet |

Die Anzeigenamen landen in `gpkg_data_columns`, der Schema-Erweiterung des
GeoPackage-Formats, und damit *in* der Datei — QGIS zeigt sie als
Feldaliase. Sie hängen nicht am Projekt und gehen beim Weitergeben nicht
verloren. Die Feldnamen selbst bleiben die der Fachauswahl, damit der
LANUK-Stil greift; er liegt auch auf diesem Layer.

Vier Eingriffe beim Aufbereiten:

* **„kein LRT" wird zur leeren Zelle.** Das ist ein regulärer
  OSIRIS-Eintrag (Liste 19, Atom 168820) und steht im Export als Text in
  `Oekotyp` — im Testdatensatz bei 261 von 759 Objekten. Als Text sieht er
  wie ein Lebensraumtyp aus und wird in Auswertungen mitgezählt; gemeint ist
  das Gegenteil.
* **Wahrheitswerte als Ja/Nein** statt 0/1. Leer bleibt leer: „nicht
  erhoben" ist weder Ja noch Nein.
* **Die Fläche auf vier Nachkommastellen.** Das sind Quadratzentimeter, und
  mehr behauptet keine Kartierung. (Der LANUK-Konverter liefert sie
  ungerundet.)
* **Objekte ohne Biotoptyp bleiben drin, gekennzeichnet.** Im
  Testdatensatz 78 von 759. Der LANUK-Konverter lässt sie fallen; bei einer
  Notfallsicherung wären sie damit verloren. `Ohne_BT_Code` trennt sie mit
  einem Filter wieder ab.

### Darstellung

Die Fachauswahl der Objektklasse **BT** bringt den Layerstil des LANUK mit:
`BIOTOP_v2020_polygon.qml`, das Original, unverändert. Es liegt im Plugin
unter `data/gispad/` und wird nach der Übernahme als *Vorgabestil* in die
Tabelle `layer_styles` des erzeugten GeoPackages geschrieben. QGIS nimmt ihn
beim Laden von dort selbst — es ist nichts anzuklicken.

Der Stil steckt bewusst *im* GeoPackage und liegt nicht als QML daneben: So
bleibt er an den Daten, wenn die Datei weitergegeben oder verschoben wird.

Dass er ohne Anpassung greift, ist kein Zufall, sondern der Grund für die
Feldnamen der Übernahme: Der Stil kategorisiert über `BT_CODE` und
beschriftet aus `KENNUNG` und `BT_CODE`. In einem Testdatensatz waren alle
91 vorkommenden `BT_CODE`-Werte von den 1811 Kategorien des Stils abgedeckt.

Zwei Einschränkungen, beide beabsichtigt:

* Nur der **Polygonlayer** bekommt ihn. Ein Flächenstil auf Linien oder
  Punkten wäre wirkungslos.
* Die **Vollsicherung bleibt ungestylt.** Sie führt die GISPAD-Rohfelder und
  kennt kein `BT_CODE` — ein darauf kategorisierender Stil fände nichts.

Fehlt die Stildatei im Plugin, gibt es einen Hinweis im Protokoll und keinen
Abbruch: Die Daten sind dann übernommen und nur ungestylt, und bei einer
Notfallsicherung zählen die Daten.

### Gepackte Exporte

Eine File-Geodatabase ist ein Ordner mit hunderten Dateien. Wer sie
weitergibt, packt sie — und beim Verschicken bleibt es oft dabei: Auf der
Platte liegt dann ein ZIP-Archiv, kein Ordner. Das Plugin packt es selbst
aus (in einen temporären Ordner, der beim Schließen des Fensters wieder
entfernt wird; das GeoPackage bleibt natürlich).

Zwei Dinge, die in der Praxis Zeit gekostet haben:

* **Der Windows-Explorer blendet bekannte Endungen aus.** Was dort
  `Export.gdb` heißt und in der Spalte *Typ* als ZIP-Archiv steht, ist in
  Wahrheit `Export.gdb.zip` — eine Datei, kein Ordner. Im Ordnerdialog ist
  sie deshalb unsichtbar. Darum der Knopf *ZIP-Datei …*; wer stattdessen
  den Ordner wählt, in dem sie liegt, kommt ebenfalls zum Ziel: dort wird
  mit gesucht.
* **Der Lesetreiber besteht auf der Endung am Ordner.** `OpenFileGDB`
  öffnet nur Ordner, deren Name auf `.gdb` endet. Ein ausgepackter, aber
  umbenannter Export lässt sich nicht lesen — das Plugin erkennt diesen
  Fall und sagt, dass umbenannt werden muss, statt „nichts gefunden" zu
  melden. Beim eigenen Auspacken wird die Endung mit gesetzt, auch wenn
  das Archiv die Tabellendateien ohne Ordner enthält.

## Für den Stapelbetrieb: die Kommandozeile

Gleiche Logik, andere Oberfläche — etwa wenn mehrere Projektordner auf
einmal gesichert werden:

`--gdb` nimmt dasselbe an wie der Dialog: den `.gdb`-Ordner, einen Ordner
darüber oder darunter, ein ZIP-Archiv des Exports oder einen Ordner mit
solchen Archiven.

```bash
# 1. Sichten: was steckt im Export, wie hängt es zusammen?
python3 tools/gispad_export.py --gdb Export.gdb --modus beziehungen

# 2. Sichern: alles, vollständig, verlustfrei
python3 tools/gispad_export.py --gdb Export.gdb --modus alles \
    --out Sicherung.gpkg

# 3. Arbeiten: die fachliche Auswahl je Objektklasse
python3 tools/gispad_export.py --gdb Export.gdb --modus fachlich \
    --klasse BT --out BT.gpkg

# 4. Weitergeben: der kuratierte Biotoptypen-Layer
python3 tools/gispad_export.py --gdb Export.gdb --modus kuratiert \
    --out BT_kuratiert.gpkg
```

Objektklassen: `BT` (Biotoptypen), `BK` (Biotopkataster), `FFH` (FFH-Gebiete), `MAS` (Maßnahmen).

**Bei einem unbekannten Export immer mit `--modus beziehungen` anfangen.**

Das Skript ist nur die Kommandozeile; die Logik liegt im Plugin
(`core/gispad.py`, `core/gispad_klassen.py`). Zwei Fassungen würden
auseinanderlaufen.

## Das Datenmodell

GISPAD speichert nach dem OSIRIS-Modell: `LINFOS` ist die Haupttabelle, die
übrigen hängen daran, teils über mehrere Stufen. Im Geodatabase-Export
erscheint LINFOS als die Geometrie-Layer der Objektklasse (`BT_Polygon`,
`BT_Polyline`, `BT_Point`).

Für BT ergibt sich — aus den Daten abgeleitet und deckungsgleich mit dem
Schema der DV-Verfahrensbeschreibung V2020a, S. 30:

```
LINFOS  (BT_Polygon / BT_Polyline / BT_Point)
├─ BtypHtyp            1:1    Biotoptyp, LR-Typ, §30/62, Bewertung
│   ├─ Vegetationstyp  1:n
│   │   └─ Schichtung  1:n
│   │       ├─ Pflanzenliste  1:n
│   │       └─ Tierliste      1:n
│   ├─ Zusatzcodes     1:n
│   └─ Wuchsklasse     1:n
├─ adressrolle → adressen → Termine     (wer, wann, welcher Arbeitsschritt)
└─ PRJ_ID · HINWEIS · Waldstruktur · LINFOS2 · MASSN · BESITZ · …
```

### Zwei Fallen

**GISPADID taugt nicht zum Verknüpfen.** Sie ist in allen Tabellen eines
Objektes gleich. Bei `1:n:n` lässt sich damit nicht mehr sagen, welche
Pflanzenzeile zu welcher Schicht gehörte — die Hierarchie geht verloren.
Verknüpft wird über `FKEY → PKEY`, Ebene für Ebene. So steht es auch in der
DV-Verfahrensbeschreibung BT (V2020a, S. 29).

**PKEY ist nur innerhalb einer Tabelle eindeutig.** Die Wertebereiche
verschiedener Tabellen überlappen stark, deshalb „trifft" ein FKEY rein
zufällig auch in falschen Tabellen. Eine hohe Trefferquote beweist nichts:
`Termine → adressrolle` erreichte 99,2 % und war trotzdem falsch — richtig ist
`Termine → adressen` (2104 von 2104, ohne einen Widerspruch).

Deshalb prüft die Ableitung nicht die Trefferquote, sondern die
**Widerspruchsfreiheit der GISPADID**: Passt der über FKEY gefundene
Elternsatz zu einem anderen Objekt, war der Treffer Zufall. Ein einziger
Widerspruch schließt einen Kandidaten aus.

### Warum abgeleitet statt fest verdrahtet

Der Export liefert die Beziehungen nicht mit; die DV-Verfahrensbeschreibung
hält auf S. 35 ausdrücklich fest, die „relationship classes werden nicht
exportiert und müssen weiterhin nachträglich definiert werden". Sie aus den
Daten zu bestimmen hat den Vorteil, dass auch Objektklassen funktionieren,
deren Schema nicht vorliegt — die BK-Beschreibung v2019a etwa führt keine
Tabellenspalte. Das Verfahren wurde gegen das dokumentierte BT-Schema geprüft
und hat es vollständig reproduziert.

Die Sicherung (`--modus alles`) legt die abgeleiteten Beziehungen als Tabelle
`gispad_beziehungen` mit ins GeoPackage. Sie dokumentiert sich damit selbst.

## Referenzlisten (OSIRIS)

Der Export enthält nur Schlüssel (`CA4`, `NEC0`, `str`). Der Klartext steht in
der OSIRIS-Datenbank `v_osiris*.mdb`. Die wird einmalig ausgelesen:

```bash
apt-get install mdbtools        # bzw. unter Windows einmalig auf einem Linux-Rechner
python3 tools/osiris_listen_export.py --mdb v_osiris54_2025a.mdb
```

Geschrieben wird nach `<Plugin>/data/osiris/` — dort findet der Dialog die
Listen ohne Zutun der Anwenderinnen und Anwender, und sie reisen mit dem
Plugin-Paket mit. Die `.mdb` (68 MB, Access) wird danach nicht mehr
gebraucht.

Mehrdeutige Schlüssel sind markiert (Spalte `mehrdeutig`) und tragen alle
Lesarten: `AV1` ist in der Biotoptypen-Liste sowohl „Ausbreitungskorridor,
Vernetzungsachse" als auch „Waldmantel". Das soll auffallen statt
stillschweigend zu einer willkürlichen Bedeutung zu werden.

## Verträglich mit dem LANUK-Konverter

Die ersten Felder tragen bewusst die Namen, die der LANUK-Konverter vergibt:

| Objektklasse | Felder wie beim LANUK-Konverter |
| --- | --- |
| BT | `KENNUNG`, `BT_CODE`, `FL_HA`, `GISPADID` |
| FFH | `KENNUNG`, `OBJBEZ`, `GISPADID` |

Damit lässt sich das mitgelieferte `BIOTOP_v2020_polygon.qml` **ohne jede
Änderung** auf das Ergebnis legen — es kategorisiert über `BT_CODE`.

Gegen die Ausgabe des offiziellen Konverters geprüft: `KENNUNG`, `BT_CODE`
und `FL_HA` stimmten bei **allen 681 Objekten** eines Testdatensatzes überein,
ebenso die FFH-Gebietsangaben. Ein Unterschied bleibt bewusst: Der
LANUK-Konverter lässt Objekte **ohne Biotoptyp weg** (78 von 759 im Test),
hier bleiben sie erhalten — eine Sicherung soll nichts verlieren.

## Gefährdung und Beeinträchtigung

Die Tabelle `GEFAEHRD` bedient zwei Ebenen, unterschieden allein dadurch,
woran sie hängt:

| hängt an | Bedeutung | Feld |
| --- | --- | --- |
| Gebietsobjekt (FFH) | Gefährdung des **ganzen Gebiets** | `Gef_Code` (EU-Codes des Natura-2000-Standarddatenbogens) |
| Biotopfläche (BT) | Beeinträchtigung **der Fläche** | `GEFAEHRD` (Referenzlisten-Klartext) |

Im Testdatensatz war die Trennung vollständig: 27 Zeilen am Gebiet trugen nur
`Gef_Code`, 2 Zeilen an Flächen nur `GEFAEHRD`.

## Was BT übernimmt

| Zielfeld | Quelle |
| --- | --- |
| Geometrie | `BT_Polygon` / `BT_Polyline` / `BT_Point`, EPSG:25832 |
| `Kennung` | LINFOS `KENNUNG` (Objektkennung, z. B. `BT-0161`) |
| `Gispad_ID` | `GISPADID` (Herkunftsnachweis, **kein** Join-Schlüssel) |
| `Biotoptyp` + `_Text` | `BtypHtyp.Biotoptyp` + OSIRIS-Liste 13 |
| `LR_Typ` + `_Text` + `LR_Art` | `BtypHtyp.Oekotyp` + OSIRIS-Liste 19 |
| `P62` / `P62_Typ` | `BtypHtyp.ist_P62_typ` / `.P62_Typ` |
| `Zusatzcodes` + `_Text` | `Zusatzcodes` über FKEY, aggregiert + OSIRIS-Liste 14 |

**Der LR-Typ steht in `Oekotyp`**, nicht in den `FFH_*`-Feldern — so die
DV-Verfahrensbeschreibung S. 4. Die `FFH_*`-Felder dienen anderen Zwecken und
sind in Exporten meist leer; wer dort sucht, hält den LR-Typ fälschlich für
nicht enthalten. `LR_Art` unterscheidet FFH-LRT (vierstelliger FFH-Code, auch
mit Buchstabe wie `91D0`) von N-LRT (beginnt mit `N`).

## Fallstricke in den Quelldaten

- `GK_RW` / `GK_HW` heißen „Rechtswert"/„Hochwert", enthalten aber
  **UTM-Werte als Text, mit angehängtem Komma** (`'360842,'`). Wer sie als
  Gauß-Krüger liest, bekommt Unsinn. `UTM_East`/`UTM_North` sind sauberes
  Integer — oder gleich die Geometrie.
- Die BT-Datumsfelder (`Kartierung`, `E_DAT`, `DatumAusgZust`) sind oft leer.
  Das Kartierdatum steht in `Termine.K_Termin` als `TT.MM.JJJJ`.
- Wahrheitswerte kommen als deutscher Text `Wahr` / `Falsch`. Unbekanntes
  wird als NULL übernommen, nicht als „nein".
- `BtypHtyp` deckt Polygon **und** Linie ab. Wer nur `BT_Polygon` liest, hält
  die Linienzeilen fälschlich für verwaist.

## Prüfstand

Gegen einen echten Export (Biotopkartierung, 1314 Polygone + 8 Linien,
10.739 Pflanzenzeilen):

- Beziehungsableitung: alle 14 Sachtabellen eindeutig, keine Toleranz nötig,
  deckungsgleich mit dem offiziellen Schema
- Fachlicher BT-Import: satzweiser Vergleich mit der Quelle über alle 1314
  Datensätze — keine Abweichung
- Klartextauflösung: 37/37 Biotoptypen, 14/14 LR-Typen, 55/55 Zusatzcodes
- Vollsicherung: 16 Tabellen, alle Zeilen, alle Felder, Schlüsselspalten
  erhalten
- BK und MAS gegen eine synthetische Geodatabase geprüft (die Pfade laufen;
  die Feldauswahl ist mangels echter Daten noch eine Erwartung)
- Dialog mit QGIS-Attrappen konstruiert, Kommandozeile gegen dieselbe
  Plugin-Logik gefahren — beide liefern dasselbe Ergebnis

## Empfehlung für die Stationen

Solange für BK und MAS keine echten Exporte geprüft sind, für diese beiden
Klassen **nur „Alles sichern"** verwenden. Die Sicherung ist von der
Feldauswahl unabhängig und rettet alles; die fachliche Ebene lässt sich
später jederzeit aus der gesicherten Geodatabase nachziehen.
