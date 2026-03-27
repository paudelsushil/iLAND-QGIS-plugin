"""QGIS plugin entry point for iLAND Workbench."""


def classFactory(iface):
    """Load iLandWorkbenchPlugin class from file iland_qgis_plugin."""
    from .iland_qgis_plugin import iLandWorkbenchPlugin

    return iLandWorkbenchPlugin(iface)
