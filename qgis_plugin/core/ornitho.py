"""
core/ornitho.py - ornitho.de-Export (Basic+, JSON) auswerten
=============================================================

Ohne QGIS-Abhaengigkeit, damit es sich auch ausserhalb von QGIS pruefen
laesst. Der Dialog (ornitho_import_dialog.py) baut daraus den Layer.

Aufbau des Exports (Stand Nov. 2026):

    data.sightings[]            Einzelbeobachtungen
    data.forms[].sightings[]    Beobachtungen aus Listen (z. B. ADEBAR-Liste,
                                vollstaendige Listen aus NaturaList)

Frueher wurden nur data.sightings gelesen - alle Beobachtungen aus Listen
fehlten (Testexport: 508 von 749 Beobachtungen).

Zusaetzlich wird der Excel-Export (.xlsx) gelesen: ein Blatt, Zeile 1 mit
technischen Spaltennamen (ID_SIGHTING, ...), Zeile 2 mit deutschen
Bezeichnungen, danach eine Zeile je Beobachtung - Einzelbeobachtungen und
Listen gemeinsam. Vorteil fuer die Praxis: Die Datei laesst sich vor dem
Import in Excel pruefen und von Hand ausduennen.
"""

import re

# estimation_code -> Anzeige. NO_VALUE heisst "nicht gezaehlt": Die Anzahl
# bleibt dann LEER (NULL) und ist so von einer echten Nullzaehlung zu trennen.
ERFASSUNG = {
    "EXACT_VALUE": "exakt",
    "MINIMUM":     "mindestens",
    "MAXIMUM":     "höchstens",
    "ESTIMATION":  "geschätzt",
    "ESTIMATE":    "geschätzt",
    "NO_VALUE":    "nicht gezählt",
}

# Alterscodes, die als "jung" zaehlen (Pullus, juvenil, 1. Kalenderjahr)
JUNG = {"PULL", "JUV", "1Y"}

ORTSTYP = {"square": "Rasterfeld", "place": "Ort"}

# Ausgabefelder in Reihenfolge: (Name, Typ)  Typ: "str" | "int"
FELDER = [
    ("ornitho_id", "str"),
    ("art", "str"),
    ("art_lat", "str"),
    ("art_id", "int"),
    ("datum", "str"),
    ("uhrzeit", "str"),
    ("jahr", "int"),
    ("anzahl", "int"),          # leer bei "nicht gezählt"
    ("erfassung", "str"),
    ("anzahl_adult", "int"),
    ("anzahl_jung", "int"),
    ("anzahl_m", "int"),
    ("anzahl_w", "int"),
    ("details", "str"),         # alle Detailzeilen im Klartext
    ("verhalten", "str"),       # z. B. "W ziehend"
    ("rasthabitat", "str"),
    ("atlas_code", "str"),
    ("kolonie", "str"),
    ("akustisch", "int"),
    ("kommentar", "str"),
    ("zusatzinfo", "str"),      # extended_info, falls vorhanden
    ("beobachter", "str"),
    ("ort", "str"),
    ("gemeinde", "str"),
    ("kreis", "str"),
    ("ortstyp", "str"),
    ("praezision", "str"),
    ("projekt", "str"),
    ("liste_id", "str"),
    ("liste_vollstaendig", "str"),
    ("liste_zeit", "str"),
    ("eingabedatum", "str"),
    ("quelle", "str"),
    ("medien", "int"),
    ("versteckt", "str"),
    ("zweithand", "str"),
    ("guid", "str"),
    ("ornitho_url", "str"),
]

# Link auf die Beobachtung in ornitho.de
URL = "https://www.ornitho.de/index.php?m_id=54&id={id}"


def _text(v):
    """ornitho-Werte sind oft {"@id": .., "#text": ..}."""
    if isinstance(v, dict):
        return str(v.get("#text", v.get("@id", "")) or "")
    return "" if v is None else str(v)


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def beobachtungen(daten):
    """
    Alle Beobachtungen als Liste von (sighting, form_oder_None).
    daten: das geladene JSON (mit oder ohne Huelle "data").
    """
    d = daten.get("data", daten) if isinstance(daten, dict) else {}
    ergebnis = [(s, None) for s in d.get("sightings", []) or []]
    for form in d.get("forms", []) or []:
        for s in form.get("sightings", []) or []:
            ergebnis.append((s, form))
    return ergebnis


def zeile(s, form=None):
    """
    Eine Beobachtung als dict mit allen FELDER plus "lat", "lon".
    lat/lon sind None, wenn keine Koordinate vorhanden ist.
    """
    sp = s.get("species", {}) or {}
    place = s.get("place", {}) or {}
    obs = (s.get("observers") or [{}])[0] or {}

    # Koordinaten: Beobachtungspunkt, sonst GPS, sonst Ort/Rasterfeld
    lat = lon = None
    for kla, klo, quelle in (("coord_lat", "coord_lon", obs),
                             ("gps_lat", "gps_lon", obs),
                             ("coord_lat", "coord_lon", place)):
        try:
            la, lo = float(quelle.get(kla)), float(quelle.get(klo))
        except (TypeError, ValueError):
            continue
        if la or lo:
            lat, lon = la, lo
            break

    iso = (s.get("date", {}) or {}).get("@ISO8601", "") or ""
    timing = obs.get("timing", {}) or {}
    uhrzeit = ""
    if timing.get("@notime") == "0" and len(timing.get("@ISO8601", "")) >= 16:
        uhrzeit = timing["@ISO8601"][11:16]

    est = obs.get("estimation_code", "") or ""
    anzahl = None if est == "NO_VALUE" else _int(obs.get("count"))

    # Details: Anzahl je Geschlecht/Alter
    adult = jung = m = w = 0
    hat_details = False
    texte = []
    for det in obs.get("details", []) or []:
        n = _int(det.get("count")) or 0
        sex = det.get("sex", {}) or {}
        age = det.get("age", {}) or {}
        sid, aid = sex.get("@id", ""), age.get("@id", "")
        hat_details = True
        if aid == "AD":
            adult += n
        elif aid in JUNG:
            jung += n
        if sid == "M":
            m += n
        elif sid == "F":
            w += n
        texte.append(f"{n}× {_text(sex)} {_text(age)}".strip())

    zusatz = obs.get("extended_info")
    if isinstance(zusatz, dict) and zusatz:
        zusatz = "; ".join(f"{k}: {_text(v)}" for k, v in zusatz.items())
    else:
        zusatz = _text(zusatz) if zusatz and not isinstance(zusatz, dict) else ""

    liste_zeit = ""
    if form and (form.get("time_start") or form.get("time_stop")):
        liste_zeit = (f"{(form.get('time_start') or '')[:5]}–"
                      f"{(form.get('time_stop') or '')[:5]}")

    oid = obs.get("id_sighting", "")
    z = {
        "lat": lat, "lon": lon,
        # IDs ohne Plattform-Praefix ("28_..."), wie im Excel-Export
        "ornitho_id": str(oid),
        "art": sp.get("name", ""),
        "art_lat": sp.get("latin_name", ""),
        "art_id": _int(sp.get("@id")),
        "datum": iso[:10],
        "uhrzeit": uhrzeit,
        "jahr": _int(iso[:4]),
        "anzahl": anzahl,
        "erfassung": ERFASSUNG.get(est, est),
        "anzahl_adult": adult if hat_details else None,
        "anzahl_jung": jung if hat_details else None,
        "anzahl_m": m if hat_details else None,
        "anzahl_w": w if hat_details else None,
        "details": "; ".join(texte),
        "verhalten": _text(obs.get("observation_detail")),
        "rasthabitat": _text(obs.get("resting_habitat")),
        "atlas_code": _text(obs.get("atlas_code")),
        "kolonie": "ja" if obs.get("has_colony") == "1" else "",
        "akustisch": _int(obs.get("auditory_contact")) or 0,
        "kommentar": obs.get("comment", "") or "",
        "zusatzinfo": zusatz,
        "beobachter": obs.get("name", "") or "",
        "ort": place.get("name", "") or "",
        "gemeinde": place.get("municipality", "") or "",
        "kreis": place.get("county", "") or "",
        "ortstyp": ORTSTYP.get(place.get("place_type"), place.get("place_type", "")),
        "praezision": obs.get("precision", "") or "",
        "projekt": obs.get("project_name", "") or "",
        "liste_id": re.sub(r"^\d+_", "", str(
            obs.get("id_form_universal")
            or (form or {}).get("id_form_universal", "") or "")),
        "liste_vollstaendig": ({"1": "ja", "0": "nein"}.get(
            (form or {}).get("full_form"), "") if form else ""),
        "liste_zeit": liste_zeit,
        "eingabedatum": ((obs.get("insert_date", {}) or {})
                         .get("@ISO8601", "")[:19].replace("T", " ")),
        "quelle": obs.get("source", "") or "",
        "medien": len(obs.get("medias", []) or []),
        "versteckt": "ja" if obs.get("hidden") == "1" else "",
        "zweithand": "ja" if obs.get("second_hand") == "1" else "",
        "guid": obs.get("guid", "") or "",
        "ornitho_url": URL.format(id=oid) if oid else "",
    }
    return z


# ── Excel-Export ────────────────────────────────────────────────────────────

# Genauigkeit der Anzahl im Excel-Export (Symbol statt Code)
ERFASSUNG_EXCEL = {
    "": "exakt", "=": "exakt",
    ">": "mindestens", "<": "höchstens",
    "~": "geschätzt", "ca.": "geschätzt",
    "x": "nicht gezählt", "X": "nicht gezählt",
}

# Deutsche Spaltenbezeichnung -> technischer Name, falls eine Datei nur die
# deutsche Kopfzeile hat (z. B. nach dem Bearbeiten in Excel)
_SPALTEN_DE = {
    "ID ornitho.de/lu": "ID_SIGHTING", "ID Art": "ID_SPECIES",
    "dt. Artname": "NAME_SPECIES", "wiss. Artname": "LATIN_SPECIES",
    "Datum": "DATE", "Uhrzeit": "TIMING", "ID Liste": "ID_FORM",
    "Beobachtungsliste Beginn": "TIME_START", "Beobachtungsliste Ende": "TIME_STOP",
    "Liste vollständig?": "FULL_FORM", "Ort": "PLACE", "Gemeinde": "MUNICIPALITY",
    "Kreis": "COUNTY", "Y-Koordinate WGS84 (dezimal)": "COORD_LAT",
    "X-Koordinate WGS84 (dezimal)": "COORD_LON", "Art der Verortung": "PRECISION",
    "Genauigkeit Anzahl": "ESTIMATION_CODE", "Anzahl": "TOTAL_COUNT",
    "Alter/Geschlecht": "DETAIL", "Brutzeitcode": "ATLAS_CODE",
    "Rasthabitat": "RESTING_HABITAT", "Präzisierung der Beobachtung": "OBSERVATION_DETAIL",
    "Meldung aus zweiter Hand?": "SECOND_HAND", "Meldung geschützt?": "HIDDEN",
    "Bemerkung": "COMMENT", "Projekt Name": "PROJECT_NAME",
    "with photo/sound file(s)?": "MEDIA_HAS_MEDIA", "Eingabedatum": "INSERT_DATE",
}


def excel_beobachtungen(pfad):
    """Zeilen des Excel-Exports als dicts mit technischen Spaltennamen."""
    import openpyxl
    wb = openpyxl.load_workbook(pfad, read_only=True, data_only=True)
    try:
        zeilen = list(wb.worksheets[0].iter_rows(values_only=True))
    finally:
        wb.close()
    kopf, start = None, 0
    for i, z in enumerate(zeilen[:5]):
        werte = [str(v).strip() if v is not None else "" for v in z]
        if "ID_SIGHTING" in werte:
            kopf, start = werte, i + 1
            break
        if "ID ornitho.de/lu" in werte:
            kopf, start = [_SPALTEN_DE.get(w, w) for w in werte], i + 1
            break
    if kopf is None:
        raise ValueError("Keine ornitho-Kopfzeile gefunden (Spalte ID_SIGHTING "
                         "bzw. „ID ornitho.de/lu“).")
    ergebnis = []
    for z in zeilen[start:]:
        d = dict(zip(kopf, z))
        # deutsche Bezeichnungszeile unter der technischen ueberspringen
        if str(d.get("ID_SIGHTING", "")).startswith("ID "):
            continue
        if d.get("ID_SIGHTING") in (None, ""):
            continue
        ergebnis.append(d)
    return ergebnis


def _detail_excel(text):
    """'2x adult / 1x Pullus / nicht-flügge' -> (adult, jung, m, w, hat)."""
    adult = jung = m = w = 0
    teile = re.split(r"(?:^|\s*/\s*)(?=\d+\s*x\s)", text or "")
    hat = False
    for t in teile:
        mt = re.match(r"\s*(\d+)\s*x\s+(.*)", t)
        if not mt:
            continue
        hat = True
        n, rest = int(mt.group(1)), mt.group(2).lower()
        if "adult" in rest:
            adult += n
        elif any(k in rest for k in ("pull", "juv", "diesjährig", "1. kj")):
            jung += n
        if "männchen" in rest:
            m += n
        elif "weibchen" in rest:
            w += n
    return adult, jung, m, w, hat


def _ja(v):
    return "ja" if str(v).strip().lower() in ("ja", "1", "true") else ""


def _datum(v):
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    return str(v or "")[:10]


def _zeit(v):
    if hasattr(v, "strftime"):
        return v.strftime("%H:%M")
    return str(v or "")[:5]


def zeile_excel(d):
    """Eine Excel-Zeile als dict mit allen FELDER plus "lat", "lon"."""
    try:
        lat, lon = float(d.get("COORD_LAT")), float(d.get("COORD_LON"))
        if not (lat or lon):
            lat = lon = None
    except (TypeError, ValueError):
        lat = lon = None

    est = str(d.get("ESTIMATION_CODE") or "").strip()
    erfassung = ERFASSUNG_EXCEL.get(est, est)
    anzahl = None if erfassung == "nicht gezählt" else _int(d.get("TOTAL_COUNT"))

    adult, jung, m, w, hat = _detail_excel(str(d.get("DETAIL") or ""))
    datum = _datum(d.get("DATE"))
    uhr = _zeit(d.get("TIMING"))
    form = _int(d.get("ID_FORM")) or 0
    liste_zeit = ""
    if form:
        a, b = _zeit(d.get("TIME_START")), _zeit(d.get("TIME_STOP"))
        if (a, b) != ("00:00", "00:00"):
            liste_zeit = f"{a}–{b}"
    ins = d.get("INSERT_DATE")
    eingabe = ins.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ins, "strftime") else str(ins or "")
    prec = str(d.get("PRECISION") or "")
    oid = str(d.get("ID_SIGHTING") or "").strip()
    return {
        "lat": lat, "lon": lon,
        "ornitho_id": oid,
        "art": str(d.get("NAME_SPECIES") or ""),
        "art_lat": str(d.get("LATIN_SPECIES") or ""),
        "art_id": _int(d.get("ID_SPECIES")),
        "datum": datum,
        "uhrzeit": "" if uhr in ("", "00:00") and not str(d.get("TIMING") or "") else uhr,
        "jahr": _int(datum[:4]),
        "anzahl": anzahl,
        "erfassung": erfassung,
        "anzahl_adult": adult if hat else None,
        "anzahl_jung": jung if hat else None,
        "anzahl_m": m if hat else None,
        "anzahl_w": w if hat else None,
        "details": str(d.get("DETAIL") or ""),
        "verhalten": str(d.get("OBSERVATION_DETAIL") or ""),
        "rasthabitat": str(d.get("RESTING_HABITAT") or ""),
        "atlas_code": str(d.get("ATLAS_CODE") or ""),
        "kolonie": "",            # im Excel-Export nicht enthalten
        "akustisch": None,        # im Excel-Export nicht enthalten
        "kommentar": str(d.get("COMMENT") or ""),
        "zusatzinfo": "",
        "beobachter": "",         # im Excel-Export nicht enthalten
        "ort": str(d.get("PLACE") or ""),
        "gemeinde": str(d.get("MUNICIPALITY") or ""),
        "kreis": str(d.get("COUNTY") or ""),
        "ortstyp": "Ort" if prec == "Ort" else "",
        # gleiche Werte wie im JSON, damit der Filter "nur exakt" greift
        "praezision": "precise" if prec.startswith("Exakt") else prec,
        "projekt": str(d.get("PROJECT_NAME") or ""),
        "liste_id": str(form) if form else "",
        "liste_vollstaendig": ({"1": "ja", "0": "nein"}.get(str(d.get("FULL_FORM")), "")
                               if form else ""),
        "liste_zeit": liste_zeit,
        "eingabedatum": eingabe,
        "quelle": "ornitho.de Excel-Export",
        "medien": 1 if _ja(d.get("MEDIA_HAS_MEDIA")) else 0,
        "versteckt": _ja(d.get("HIDDEN")),
        "zweithand": _ja(d.get("SECOND_HAND")),
        "guid": "",
        "ornitho_url": URL.format(id=oid) if oid else "",
    }


def lade(pfad):
    """
    Liest einen ornitho-Export (.json oder .xlsx) und liefert eine Liste von
    Zeilen (dicts wie zeile() bzw. zeile_excel()).
    """
    if str(pfad).lower().endswith((".xlsx", ".xlsm")):
        return [zeile_excel(d) for d in excel_beobachtungen(pfad)]
    import json
    with open(pfad, encoding="utf-8") as f:
        daten = json.load(f)
    return [zeile(s, form) for s, form in beobachtungen(daten)]
