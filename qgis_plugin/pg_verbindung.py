"""
pg_verbindung.py – eine Stelle für Verbindungsparameter zur Fachdatenbank
=========================================================================
Die Wizard-Seiten, die Loader und der Projektaufbau benutzen dieselben
Parameter (dict mit host, port, dbname, user, password, service, sslmode).
Hier werden sie einheitlich in psycopg2-Argumente bzw. eine QGIS-
Datenquelle übersetzt.

Dienst (pg_service.conf):
    Ist ein Dienst angegeben, kommen Host, Port, Datenbank und sslmode aus
    der pg_service.conf. In die Layerquelle des QGIS-Projekts wird dann
    nur der Dienstname geschrieben – kein Benutzer, kein Passwort. QGIS
    fragt beim Öffnen nach (oder nimmt die Daten aus der pgpass-Datei bzw.
    dem QGIS-Kennwortspeicher); QFieldCloud nimmt sie aus dem Secret
    gleichen Namens. So landen keine Zugangsdaten in .qgz-Dateien.

sslmode:
    Der zentrale Server nimmt nur verschlüsselte Verbindungen an. Für
    entfernte Hosts gilt daher 'require', für localhost 'prefer'
    (Entwicklungsdatenbanken ohne TLS).
"""

_LOKAL = ("", "localhost", "127.0.0.1", "::1")


def _wert(p: dict, key: str):
    v = (p or {}).get(key)
    if isinstance(v, str):
        v = v.strip() if key != "password" else v
    return v if v not in (None, "") else None


def sslmode_fuer(p: dict) -> str:
    """Ausdrücklich gesetzter sslmode, sonst require für entfernte Hosts."""
    explizit = _wert(p, "sslmode")
    if explizit:
        return explizit
    if _wert(p, "service"):
        return ""            # kommt aus der pg_service.conf
    return "prefer" if (_wert(p, "host") or "") in _LOKAL else "require"


def connect_kwargs(p: dict, timeout: int = 5) -> dict:
    """Argumente für psycopg2.connect(**…) – leere Werte werden weggelassen,
    damit libpq seine Vorgaben (bzw. die des Dienstes) nimmt."""
    kw = {}
    for key in ("service", "host", "port", "dbname", "user", "password"):
        v = _wert(p, key)
        if v is not None:
            kw[key] = str(v) if key == "port" else v
    if kw.get("service"):
        # Host/Port liefert der Dienst; ein zusätzlich eingetragener
        # Standardwert 'localhost' würde ihn sonst überstimmen.
        if (kw.get("host") or "") in _LOKAL:
            kw.pop("host", None)
            kw.pop("port", None)
    ssl = sslmode_fuer(p)
    if ssl:
        kw["sslmode"] = ssl
    kw["connect_timeout"] = timeout
    return kw


def connect(p: dict, timeout: int = 5):
    """psycopg2-Verbindung mit autocommit (jede Abfrage für sich)."""
    import psycopg2
    con = psycopg2.connect(**connect_kwargs(p, timeout))
    con.autocommit = True
    return con


def _ssl_enum(name: str):
    from qgis.core import QgsDataSourceUri
    attr = {
        "disable": "SslDisable", "allow": "SslAllow", "prefer": "SslPrefer",
        "require": "SslRequire", "verify-ca": "SslVerifyCa",
        "verify-full": "SslVerifyFull",
    }.get(name or "", "SslPrefer")
    scoped = getattr(QgsDataSourceUri, "SslMode", None)
    if scoped is not None and hasattr(scoped, attr):
        return getattr(scoped, attr)
    return getattr(QgsDataSourceUri, attr)


def datenquelle(p: dict, schema: str, table: str, geom_col: str = "",
                filter_sql: str = "", key_col: str = ""):
    """QgsDataSourceUri für einen PostGIS-Layer.
    Mit Dienst: ohne Passwort in der Quelle (siehe Modulkopf)."""
    from qgis.core import QgsDataSourceUri
    uri = QgsDataSourceUri()
    service = _wert(p, "service")
    ssl = _ssl_enum(sslmode_fuer(p) or "prefer")
    if service:
        # Nur der Dienstname kommt in die Quelle – auch kein Benutzer:
        # in QFieldCloud liefert das Secret gleichen Namens Benutzer und
        # Passwort (je Projekt oder je Person); ein Benutzer in der Quelle
        # würde es überstimmen. Datenbank ebenfalls aus dem Dienst.
        uri.setConnection(service, "", "", "", ssl)
    else:
        uri.setConnection(_wert(p, "host") or "localhost",
                          str(_wert(p, "port") or 5432),
                          _wert(p, "dbname") or "",
                          _wert(p, "user") or "",
                          _wert(p, "password") or "",
                          ssl)
    uri.setDataSource(schema, table, geom_col or "", filter_sql or "", key_col or "")
    if service and _wert(p, "user") and _wert(p, "password"):
        # Anmeldung für diese QGIS-Sitzung hinterlegen (nicht im Projekt):
        # QGIS nimmt sie, wenn der Dienst selbst keine Zugangsdaten hat.
        try:
            from qgis.core import QgsCredentials
            QgsCredentials.instance().put(uri.connectionInfo(False),
                                          _wert(p, "user"), _wert(p, "password"))
        except Exception:
            pass
    return uri


def sql_text(wert: str) -> str:
    """Zeichenkette als SQL-Literal (für Layerfilter)."""
    return "'" + str(wert).replace("'", "''") + "'"


def bezeichner_sql(vorlage: str, **namen):
    """SQL mit sicher gequoteten Bezeichnern (Schema, Tabelle, Datenbank …).

    Werte gehören nie hierher, sondern als Parameter an execute().
    namen: Platzhalter -> Name oder Tupel (schema, tabelle).
    Gibt None zurück, wenn psycopg2 fehlt (dann wird ohnehin nichts
    ausgeführt).

        bezeichner_sql('CREATE SCHEMA IF NOT EXISTS {s}', s='gemeinsam')
    """
    try:
        from psycopg2 import sql
    except ImportError:
        return None
    teile = {k: sql.Identifier(*v) if isinstance(v, tuple) else sql.Identifier(v)
             for k, v in namen.items()}
    return sql.SQL(vorlage).format(**teile)
