# Required iLAND Repository Components

This file defines the minimum components expected in the iLAND repository when packaging and using the QGIS plugin.

## Mandatory For Packaging (preflight)

- `src/`
- `src/iland/`
- `src/iland/mainwindow.ui`
- `src/iland/res/project_file_metadata.txt`
- `src/ilandc/`
- `src/ilandc/main.cpp`
- `iLAND_QGIS_plugin/metadata.txt`
- `iLAND_QGIS_plugin/__init__.py`
- `iLAND_QGIS_plugin/iland_qgis_plugin.py`
- `iLAND_QGIS_plugin/iland_dock_widget.py`
- `iLAND_QGIS_plugin/runtime_manager.py`

If one of these is missing, `package_plugin.ps1` fails before ZIP creation.

## Recommended Runtime Availability

At least one of the following should exist for immediate model execution:

- A local `iLANDc.exe` on disk (for example under repository `build/` or `bin/`)
- A downloadable Windows runtime asset available from the configured GitHub releases

If no local `iLANDc.exe` exists, packaging still succeeds but prints a warning.

## Why This Exists

The plugin is an orchestration layer and depends on iLAND/iLANDc artifacts and source metadata.
This preflight guard prevents shipping a plugin ZIP that cannot discover modules/settings or run the headless engine workflow.
