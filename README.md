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

### v4.0.5

- Expanded native runtime discovery for macOS/Linux to include common source-build outputs, project-adjacent model folders, and `ILAND_SOURCE_DIR`-driven paths.
- Improved runtime diagnostics and search hints when executable resolution fails, reducing setup friction for non-Windows users.
- Restored robust untitled-QGIS project detection for XML-based Create Model workflows so save/search prompts trigger reliably.
- Added original iLand-inspired default visualization palettes and terrain-derived shading defaults to better align map styling with native iLand behavior.
- Hardened `runtime/macos/build_mac_runtime.sh` with highest-available Qt6 selection, existing-runtime reuse, architecture validation, deterministic qmake usage, and Bash-safe LF formatting.

### v4.0.4

- Fixed macOS runtime publish edge case caused by case-insensitive filesystem symlink collisions (`iLANDc`/`ilandc`), ensuring bundled runtime remains executable.
- Hardened native runtime discovery and stale-path recovery to prevent non-executable/source artifacts from being selected as runtime binaries.
- Improved macOS runtime build helper with Qt/qmake auto-detection and explicit permission prompts before Homebrew dependency installs.
- Included `runtime/macos/build_mac_runtime.sh` in release ZIP payload for end-user runtime rebuild convenience.

### v4.0.3

- Improved cross-platform runtime behavior for iLANDc: OS-aware executable resolution with PATH-first lookup and safer non-Windows handling.
- Added Runtime tab support to register a local native runtime executable for macOS/Linux workflows.
- Added project-folder and bundled-runtime discovery paths for native iLANDc binaries.
- Added first-time legacy XML workflow safeguard: prompt to save a QGIS project when none exists in the XML directory.
- Hardened landscape validation compatibility for original iLAND project inputs (quoted/whitespace environment formats and database path resolution).

### v4.0.2

- Reworked QGIS 4 main-menu integration: iLAND is now exposed as a top-level menu and no longer auto-opens plugin UI at load time.
- Updated menu layout for cleaner navigation: processing tools first, then a separator, followed by Get iLAND modules and iLAND Workbench Help.
- Removed non-essential helper algorithms from Processing provider exposure: Build iLAND run command and Get latest iLAND release info.
- Improved module discovery for nested source layouts (for example, `iland-model-main/src`) and added clearer diagnostics when repo-root configuration is invalid.

### v4.0.1

- Patch release: plugin now marked stable (`experimental=False`) in metadata for QGIS plugin manager.
- Carries forward the full 4.0.0 workflow expansion listed below.

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

Main processing tools (menu order in QGIS Processing > iLAND Workbench):

1. List iLAND modules
2. Validate existing iLand climate database
3. Future Climate
4. Historical Climate Data
5. Validate daily climate NetCDF for iLand
6. Build iLand climate database from daily NetCDF
7. Build iLand climate from WorldClim/CMIP6 GeoTIFF
8. Process disturbance history for iLand
9. Generate field data CSV templates
10. Download stand-grid source data
11. Build iLand landscape from plot data
12. Create iLAND project
13. Soil Data Download


## Citation:
@software{paudel2026iland,
  author       = {Paudel, Sushil},
  title        = {{iLAND Workbench: QGIS-based iLAND Workbench for 
                   hassle-free installation and reproducible analysis 
                   workflows}},
  year         = {2026},
  version      = {4.0.5},
  publisher    = {Zenodo},
  doi          = {10.5281/zenodo.19300115},
  url          = {https://doi.org/10.5281/zenodo.19300115}
}

## References
When using iLAND Workbench, please also cite the original iLand model. **Recommended references:**

- Rammer, W., Thom, D., Baumann, M., Braziunas, K., Dollinger, C., Kerber, J., Mohr, J., Seidl, R. (2024). The individual‑based forest landscape and disturbance model iLand: Overview, progress, and outlook. Ecological Modelling 495, 110785. https://doi.org/10.1016/j.ecolmodel.2024.110785

- Seidl, R. et al. (2012) “An individual-based process model to simulate landscape-scale forest ecosystem dynamics,” Ecological Modelling, 231, pp. 87–100. Available at: https://doi.org/10.1016/j.ecolmodel.2012.02.015.

- Thom, D. et al. (2024) “Parameters of 150 temperate and boreal tree species and provenances for an individual-based forest landscape and disturbance model,” Data in Brief, 55, p. 110662. Available at: https://doi.org/10.1016/j.dib.2024.110662.