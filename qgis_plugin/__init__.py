def classFactory(iface):
    # Nachinstallierte Pakete (qpip bzw. abhaengigkeiten.py) auffindbar
    # machen.
    try:
        from .abhaengigkeiten import pfad_einbinden
        pfad_einbinden()
    except Exception:
        pass
    from .new_project_plugin import NewProjectPlugin
    return NewProjectPlugin(iface)
