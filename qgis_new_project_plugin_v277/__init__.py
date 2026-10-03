def classFactory(iface):
    from .new_project_plugin import NewProjectPlugin
    return NewProjectPlugin(iface)
