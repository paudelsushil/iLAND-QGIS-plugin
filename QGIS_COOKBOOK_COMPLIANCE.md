# QGIS Cookbook Compliance Checklist

Reference:
- https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/plugins/plugins.html
- https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/plugins/releasing.html
- https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/processing.html

## Plugin Structure

- [x] `metadata.txt` present
- [x] `__init__.py` present with `classFactory(iface)`
- [x] Main plugin class exposes `__init__`, `initGui`, `unload`
- [x] Plugin icon present
- [x] `README.md` present
- [x] `LICENSE` present in plugin root (required for official repository)
- [x] Local help page scaffold present (`help/index.html`)
- [x] i18n scaffold present (`i18n/*.pro`, `i18n/*.ts`)

## Metadata

- [x] Mandatory fields present (`name`, `qgisMinimumVersion`, `description`, `about`, `version`, `author`, `email`, `repository`)
- [x] `category` is valid cookbook value (`Vector`)
- [x] `hasProcessingProvider=True`
- [x] `tracker`, `homepage`, `tags`, `experimental`, `deprecated` set

## GUI and Lifecycle

- [x] Toolbar action added in `initGui`
- [x] Action removed in `unload`
- [x] Action has unique `objectName`
- [x] Plugin dock has unique `objectName`
- [x] Stale action/dock cleanup on reload/update
- [x] Added to standard category menu API (`addPluginToVectorMenu`)
- [x] Help action available in Help -> Plugins menu with fallback behavior

## Processing Provider

- [x] Provider registered on load
- [x] Provider unregistered on unload
- [x] Provider has stable `id()` and `name()`
- [x] Algorithms added via provider `loadAlgorithms()`

## Packaging and Release

- [x] ZIP package contains one plugin top-level folder
- [x] Mandatory files included in ZIP (`metadata.txt`, `__init__.py`, `LICENSE`)
- [x] Packaging script excludes runtime/cache artifacts and includes only release files
- [x] Packaging script includes `help/` and `i18n/` directories when present
- [x] CI workflow scaffold provided (`.github/workflows/qgis-plugin-ci.yml`)

## Ongoing Rules For This Repository

1. Do not remove `LICENSE` from plugin root.
2. Do not change `category` to invalid values.
3. Keep `description` and `about` in metadata updated each release.
4. Keep provider registration/unregistration symmetric.
5. Run packaging script and verify ZIP contents before each shared build.
6. Keep plugin folder ASCII-safe naming and one-root ZIP structure.
