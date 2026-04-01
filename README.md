# iLAND Workbench

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19300115.svg)](https://doi.org/10.5281/zenodo.19300115)
[![Latest Release](https://img.shields.io/github/v/release/paudelsushil/iLAND-QGIS-plugin?label=release)](https://github.com/paudelsushil/iLAND-QGIS-plugin/releases)
[![Downloads](https://img.shields.io/github/downloads/paudelsushil/iLAND-QGIS-plugin/total?label=downloads)](https://github.com/paudelsushil/iLAND-QGIS-plugin/releases)
[![QGIS Compatibility](https://img.shields.io/badge/QGIS-3.28%20to%204.99-6aa84f)](https://qgis.org)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Open Issues](https://img.shields.io/github/issues/paudelsushil/iLAND-QGIS-plugin)](https://github.com/paudelsushil/iLAND-QGIS-plugin/issues)
[![Last Commit](https://img.shields.io/github/last-commit/paudelsushil/iLAND-QGIS-plugin)](https://github.com/paudelsushil/iLAND-QGIS-plugin/commits/main)

Dockable QGIS plugin that surfaces iLAND modules and submodules directly from the repository source tree.

Maintainer: Sushil Paudel

## Release Notes

### v4.0.0 (on top of 3.0.2)

This major update expands iLAND Workbench from metadata/runtime utilities into a full data-preparation workflow layer for climate, soil, and stand-grid inputs.

- Added complete climate workflows: Future Climate download, Historical Climate Data with manifest-first outputs, and improved climate conversion/validation pipeline integration.
- Added new soil workflow: Soil Data Download with SSURGO (default) and SoilGrids (global), including source-specific variable/depth selection.
- Added separate stand-grid source workflow: LANDFIRE EVT (default, API) plus global ESA WorldCover option with time-period handling.
- Improved reliability for long-running tasks: stronger cancellation handling, partial-file cleanup, and richer transfer telemetry (MB, %, MB/s).
- Improved project UX: integrated Create Project from workflow UI, safer new-project reset behavior, and better output directory resolution.
- Added landscape pre-flight validation before model creation to block missing mandatory inputs and surface warnings earlier.
- Expanded Processing Provider coverage so new workflows are directly available in QGIS Processing toolbox.
- Added QGIS 4 startup stability hardening for plugin UI/action lifecycle during initialization.

## Plugin Guide

For a complete hands-on walkthrough of all tabs, menus, and workflows, see the plugin guide:

- [Plugin Guide](plugin_guide.md)

## Minimum Requirements and Compatibility

### 1. Minimum requirements for plugin installation

- QGIS Desktop 3.28 or newer.
- A standard QGIS desktop installation (Windows, Linux, or macOS).
- No extra Python package installation is required for plugin installation.
- Install from the plugin ZIP package (not from a full repository ZIP) as publishing in QGIS repo is in process and will be onair soon.

### 2. Minimum requirements for plugin operation (without running simulations)

- The plugin can load and open its UI with QGIS only.
- No separate iLAND executable is required for browsing modules, settings views, and basic plugin navigation.
- Internet access is optional and only needed for features that query online release metadata.

### 3. Minimum requirements for running iLAND simulations from the plugin

- A compatible iLAND console runtime executable (iLANDc) is required.
- You can provide runtime in either of two ways:
  - Install via the Runtime tab (requires internet access).
  - Manually point to an existing local iLANDc executable.
- If iLANDc is not available, the plugin still installs and opens, but model run actions cannot execute.

### 4. Version scenarios (including older versions)

| QGIS version | Expected result | Notes |
|---|---|---|
| Below 3.28 | Not supported for install | Plugin metadata blocks installation. |
| 3.28 to 3.35 | Supported | Standard install and operation expected. |
| 3.36 (LTR) | Supported | Recommended for stable production use. |
| 3.40 to 4.xx | Expected to work | Keep plugin updated to latest release. |



## Core Model

This plugin is an integration layer around the original iLand core model.
- Original iLand authors: Werner Rammer and Rupert Seidl.
- Core model homepage: https://iland-model.org
- Publications and recommended citations: https://iland-model.org/iLand+publications

Suggested citation text for the core model in derivative tool documentation:

"Rammer, W., and Seidl, R. iLand - the individual-based forest landscape and disturbance model. https://iland-model.org"



## Core Processing Strategy

- iLAND/iLANDc core processing remains unchanged in its native implementation.
- JavaScript scripting in iLAND remains in place; the plugin does not replace that logic.
- This plugin does not rewrite model internals into Python.
- QGIS integration layer provides discovery, command preparation, and workflow entry points.
- For new iLAND versions, plugin updates should focus on UI/schema synchronization and command/provider adapters rather than rebuilding model internals.


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

## Citation:
@software{paudel2026iland,
  author       = {Paudel, Sushil},
  title        = {{iLAND Workbench: QGIS-based iLAND Workbench for 
                   hassle-free installation and reproducible analysis 
                   workflows}},
  year         = {2026},
  version      = {4.0.0},
  publisher    = {Zenodo},
  doi          = {10.5281/zenodo.19300115},
  url          = {https://doi.org/10.5281/zenodo.19300115}
}

## References
When using iLAND Workbench, please also cite the original iLand model. **Recommended references:**

- Rammer, W., Thom, D., Baumann, M., Braziunas, K., Dollinger, C., Kerber, J., Mohr, J., Seidl, R. (2024). The individual‑based forest landscape and disturbance model iLand: Overview, progress, and outlook. Ecological Modelling 495, 110785. https://doi.org/10.1016/j.ecolmodel.2024.110785

- Seidl, R. et al. (2012) “An individual-based process model to simulate landscape-scale forest ecosystem dynamics,” Ecological Modelling, 231, pp. 87–100. Available at: https://doi.org/10.1016/j.ecolmodel.2012.02.015.

- Thom, D. et al. (2024) “Parameters of 150 temperate and boreal tree species and provenances for an individual-based forest landscape and disturbance model,” Data in Brief, 55, p. 110662. Available at: https://doi.org/10.1016/j.dib.2024.110662.