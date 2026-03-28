# iLAND Workbench

Dockable QGIS plugin that surfaces iLAND modules and submodules directly from the repository source tree.

Maintainer: Sushil Paudel

## Core Model Citation

This plugin is an integration layer around the original iLand core model.

- Original iLand authors: Werner Rammer and Rupert Seidl.
- Core model homepage: https://iland-model.org
- Publications and recommended citations: https://iland-model.org/iLand+publications

Suggested citation text for the core model in derivative tool documentation:

"Rammer, W., and Seidl, R. iLand - the individual-based forest landscape and disturbance model. https://iland-model.org"

## Features

- Dock widget opens in the left sidebar when plugin is enabled.
- Qt6-first UI implementation with fallback to QGIS bundled Qt/PyQt runtime.
- Default iLAND logo reused from the repository (`src/iland/res/icon4.png`).
- Black-text visual style for high readability.
- iLAND-style GUI sections mirrored from source files:
  - Workflow (project input and run controls)
  - Settings (Project/System/Model/Output/Modules taxonomy)
  - Visualization (controls aligned with iLAND visualization dock)
  - Scripting (JavaScript editor/workspace placeholders)
  - Modules (full recursive module/submodule explorer)
- Dynamic module and recursive submodule discovery from `src/`.
- Dynamic settings discovery from `src/iland/res/project_file_metadata.txt`.
- Processing Toolbox provider with first-draft algorithms for QGIS test runs.

## Core Processing Strategy

- iLAND/iLANDc core processing remains unchanged in its native implementation.
- JavaScript scripting in iLAND remains in place; the plugin does not replace that logic.
- This plugin does not rewrite model internals into Python.
- QGIS integration layer provides discovery, command preparation, and workflow entry points.
- For new iLAND versions, plugin updates should focus on UI/schema synchronization and command/provider adapters rather than rebuilding model internals.

## Processing Algorithms (Draft)

- `iLAND: List iLAND modules`
: exports discovered modules/submodules to JSON.
- `iLAND: Build iLAND run command`
: builds a launch command preview without executing the model.
- `iLAND: Get latest iLAND release info`
: fetches release metadata from GitHub API to support update-only workflows.

## Runtime Manager (Draft)

The Runtime tab provides a one-click path for non-programmer workflows:

1. Click `Check Latest` to query the latest release from GitHub.
2. Click `Install Latest (Windows)` to download and extract a Windows runtime asset.
3. Select an installed runtime in the local list and click `Activate Selected Runtime`.
4. Use the Workflow tab command copy button; it will prefer the active runtime executable path.

Notes:

- Runtime artifacts are stored in user-local app data (`%LOCALAPPDATA%/iLANDWorkbenchQGIS/runtimes` on Windows).
- Runtime index and active tag are tracked in user-local app data (`config.json` and `runtimes/index.json`).
- If no active runtime is set, command templates fall back to `iLANDc.exe`.

## Professional Repository Layout

To keep sharing lightweight and clean:

1. Keep this plugin folder source-only (Python, metadata, icons, docs).
2. Keep iLAND model source/binaries outside plugin package and reference them via configurable repository root.
3. Keep runtime downloads and user-specific cache/config in local app-data, not inside git-tracked plugin files.
4. Publish plugin as a minimal ZIP package for QGIS install.

This avoids copying the full iLAND repository into the plugin and keeps plugin releases small and professional.

## Plugin Structure

- `__init__.py`: QGIS plugin entry point (`classFactory`).
- `metadata.txt`: QGIS repository metadata.
- `iland_qgis_plugin.py`: plugin lifecycle and dock integration.
- `iland_dock_widget.py`: docked multi-tab iLAND workbench UI.
- `iland_ui_catalog.py`: extraction of dock/action/settings catalogs from iLAND source files.
- `module_registry.py`: iLAND module/submodule discovery logic.
- `runtime_manager.py`: local runtime inventory, release download, install, and activation helpers.
- `config_manager.py`: persistent plugin settings for iLAND root path and GitHub repository.
- `package_plugin.ps1`: creates a slim QGIS plugin ZIP package under `dist/`.
- `i18n/`: translation source files (`.pro`, `.ts`) for plugin localization workflow.
- `help/index.html`: bundled local plugin help page.
- `icon.svg`: plugin icon.

## Development Notes

- The plugin follows standard QGIS repository conventions: metadata, icon, and classFactory loader.
- UI uses Qt widgets and is compatible with repository packaging as a plain Python plugin directory.
- iLAND modules are read from `../src` relative to plugin folder.
- Plugin help is exposed in QGIS Help -> Plugins menu and opens local `help/index.html` with online fallback.
- Translation loading is implemented via `i18n/iLAND_Workbench_<locale>.qm` when compiled files are present.

## Translation Workflow (Cookbook)

1. Edit translation sources in `i18n/`.
2. Generate/update `.ts` using Qt tools (`pylupdate5 iLAND_Workbench.pro`).
3. Compile `.qm` files (`lrelease iLAND_Workbench_en.ts`, etc.).
4. Place generated `.qm` files in `i18n/` before packaging.

## CI Packaging and Release

- GitHub Actions workflow is provided at `.github/workflows/qgis-plugin-ci.yml`.
- Packaging uses `qgis-plugin-ci package` with plugin path `iLAND_QGIS_plugin`.
- Optional release publishing uses `qgis-plugin-ci release` and requires secrets:
  - `OSGEO_USERNAME`
  - `OSGEO_PASSWORD`

## Local Installation

1. Run `package_plugin.ps1` in `iLAND_QGIS_plugin` to build a clean ZIP.
2. In QGIS, open `Plugins` -> `Manage and Install Plugins...` -> `Install from ZIP`.
3. Select `dist/iLAND_Workbench_QGIS.zip` and enable **iLAND Workbench**.
4. The dock panel opens automatically on the left.

## Packaging Preflight (Required Components)

`package_plugin.ps1` now runs preflight checks before creating the ZIP.

- It fails fast if critical iLAND/plugin components are missing.
- It warns (but does not fail) if no local `iLANDc.exe` is found.

See [REQUIRED_REPO_COMPONENTS.md](REQUIRED_REPO_COMPONENTS.md) for the exact required list.

Optional override:

- `./package_plugin.ps1 -SkipPreflight` to bypass checks (not recommended for release builds).

## Expected Source Path

The plugin can auto-detect local sibling source or use a configured external root. Configure root in Workflow tab:

- repo root
  - `iLAND_QGIS_plugin/`
  - `src/`

If root is set incorrectly, discovery will show no modules until a valid folder containing `src/` is selected.
