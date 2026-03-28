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
  version      = {3.0.0},
  publisher    = {Zenodo},
  doi          = {10.5281/zenodo.19300115},
  url          = {https://doi.org/10.5281/zenodo.19300115}
}

## References
When using iLAND Workbench, please also cite the original iLand model. **Recommended references:**

- Rammer, W., Thom, D., Baumann, M., Braziunas, K., Dollinger, C., Kerber, J., Mohr, J., Seidl, R. (2024). The individual‑based forest landscape and disturbance model iLand: Overview, progress, and outlook. Ecological Modelling 495, 110785. https://doi.org/10.1016/j.ecolmodel.2024.110785

- Seidl, R. et al. (2012) “An individual-based process model to simulate landscape-scale forest ecosystem dynamics,” Ecological Modelling, 231, pp. 87–100. Available at: https://doi.org/10.1016/j.ecolmodel.2012.02.015.

- Thom, D. et al. (2024) “Parameters of 150 temperate and boreal tree species and provenances for an individual-based forest landscape and disturbance model,” Data in Brief, 55, p. 110662. Available at: https://doi.org/10.1016/j.dib.2024.110662.