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
"""

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
        "ornitho_id": obs.get("id_universal", oid),
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
        "liste_id": (obs.get("id_form_universal")
                     or (form or {}).get("id_form_universal", "") or ""),
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
