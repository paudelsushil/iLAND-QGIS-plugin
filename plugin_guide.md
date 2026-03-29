# iLAND Workbench Hands-On Manual

## 1. Purpose and Scope

This manual is a practical, start-to-finish guide for using the iLAND Workbench QGIS plugin in a real project.

It covers:

1. Installation and first launch.
2. Complete project workflow (from project XML selection to model execution and output loading).
3. Every plugin entry point, tab, button, and major process.
4. Runtime management and compatibility checks.
5. Settings editing workflow.
6. Processing Toolbox algorithms.
7. Common troubleshooting scenarios.

## 2. Minimum Requirements

1. QGIS version:
   `3.28` to `4.99` (plugin metadata range).
2. Platform:
   Runtime installer workflow is currently focused on Windows.
3. iLAND runtime:
   You need `iLANDc.exe` (headless console engine) for create/run operations.
4. Project input:
   A valid iLAND project XML file.

## 3. Installation and First Launch

## 3.1 Install the plugin package

1. Use the packaged plugin ZIP (not the source code ZIP).
2. In QGIS, open Plugin Manager and install from ZIP.
3. Restart QGIS if requested.

## 3.2 Locate plugin UI entry points

After loading, the plugin registers:

1. Vector menu entry:
   `&iLAND -> iLAND Workbench`
2. Toolbar icon:
   `iLAND Workbench`
3. Help menu entry:
   `iLAND Workbench Help`

Important behavior: the dock is opened automatically on plugin load.

## 3.3 Help behavior

1. If local help exists, it opens `help/index.html`.
2. Otherwise, it falls back to `https://iland-model.org/`.

## 4. End-to-End Workflow

Use this exact sequence for a clean project run.

## 4.1 Open Workflow tab and set paths

1. Set `Project XML` using the `...` browse button.
2. Optionally set `Output directory`.
3. Confirm status label is not showing missing path errors.

## 4.2 Configure runtime (first project or new machine)

1. Go to `Runtime` tab.
2. Click `Check Latest` to fetch release metadata.
3. Click `Install Latest (Windows)` to install runtime locally.
4. In `Installed Runtimes`, select one runtime and click `Activate Selected Runtime`.
5. Click `Refresh Compatibility Check`.

## 4.3 Validate project settings

1. Go to `Settings` tab.
2. Click `Open Settings Dialog`.
3. Review tabs and fields.
4. Save with `Save Changes` or `Save as...`.

## 4.4 Create model state

1. Return to `Workflow` tab.
2. Click `Create Model`.
3. Wait for status `Model status: created`.
4. Confirm `Current year` moves to `1`.

## 4.5 Run simulation

1. Click `Run one year` for incremental stepping.
2. Or click `Run Model`, enter number of years, and confirm.
3. Use `Pause` or `Continue` as needed.
4. Use `Stop` to stop the active run loop/process.

## 4.6 Review and load outputs

1. Click `Open Output Folder`.
2. Click `Load Latest Output Layer` to load newest raster output (`.tif`, `.tiff`, `.asc`).
3. Use `Visualization` tab to style/load mode-specific outputs.
4. Use `View` tab to repaint or zoom full extent.

## 4.7 Reset or rerun

1. `Reload` performs destroy + create again.
2. `Destroy` resets model state and clears managed visualization layers.

## 5. Complete UI Reference

## 5.1 Workflow tab

Primary purpose: model lifecycle control and run logs.

Controls:

| Control | What it does |
| --- | --- |
| Project XML | Path to project XML file. Required for create/run. |
| Output directory | Optional override for output path. |
| Current year | Displays tracked simulation year. |
| Create Model | Initializes model state. In legacy runtime mode, it runs compatibility create command. |
| Destroy | Resets model/session state and clears plugin-managed mode layers. |
| Reload | Performs destroy then create. |
| Run one year | Executes one-year advance. |
| Run Model | Prompts for years-to-run and executes run loop. |
| Pause / Continue | Pauses/resumes active run workflow. |
| Stop | Stops running process or session loop. |
| Open Output Folder | Opens output directory in OS file explorer. |
| Load Latest Output Layer | Loads newest raster output file into QGIS. |
| Filter / Clear Filter | Filters workflow log content. |
| clear Text | Clears workflow log text area. |
| Copy to clipboard | Copies full workflow log text. |

Run states and progress bar:

1. `idle`
2. `running`
3. `paused`
4. `success`
5. `failed`

## 5.2 Settings tab

Primary purpose: launch full XML settings editor.

Controls:

| Control | What it does |
| --- | --- |
| Open Settings Dialog | Opens the detailed settings editor, optionally focused on selected tab context. |
| Summary label | Shows instructions and active tab context. |

Notes:

1. The detailed settings tree is built from metadata mappings.
2. The visible editor is the dedicated settings dialog.

## 5.3 Visualization tab

Primary purpose: load and display mode-specific outputs and supporting tables.

Visualization modes:

1. `Light influence field`
2. `dominance grid`
3. `seed availability`
4. `Regeneration`
5. `individual Trees`
6. `Snags`
7. `resource units`
8. `other grid`

Toggle options:

1. based on stems
2. established
3. draw transparent
4. color by species
5. species shares
6. clip to stands
7. Autoscale colors
8. Shading

Additional controls:

| Control | What it does |
| --- | --- |
| other grids | Free text hint for custom grid matching in `other grid` mode. |
| Expression + Run Expression | Validates and applies expression-driven visualization behavior. |
| Value combo | Presets expression templates (`tree.dbh`, `tree.height`, `ru.id`, `species`, species codes). |
| Species combo | Species filtering context loaded from project XML. |
| Refresh Species | Re-reads species list from project XML. |
| Apply Visualization | Saves visualization settings to plugin config. |
| Visualize On QGIS Map | Loads best matching layer into map canvas and updates view. |
| Reset | Resets visualization controls to default state. |

Important process behavior:

1. Selecting a visualization radio mode immediately applies and visualizes.
2. Layer source search is attempted in output rasters first, then project GIS folders.
3. If no raster is found, plugin tries loading output table from `output.sqlite`.
4. When shading is enabled, DEM underlay may be loaded if available.
5. Project CRS may be auto-aligned to loaded layer CRS.

## 5.4 View tab

Primary purpose: quick map canvas controls.

| Control | What it does |
| --- | --- |
| Repaint | Refreshes QGIS map canvas. |
| Show full extent | Zooms to full extent and refreshes map. |
| Copy Image to Clipboard | Captures current view image to clipboard. |

## 5.5 Misc tab

Primary purpose: utility tools and diagnostics.

Log level group:

1. Debug
2. Info
3. Warning
4. Error

Utilities:

| Control | What it does |
| --- | --- |
| Output table description | Scans `src/output` and copies summary list to clipboard. |
| Log timers | Reports elapsed time since last run start. |
| Execute test | Performs quick repository structure checks and logs PASS/FAIL. |
| Expression plotter | Evaluates expression over `x=0..10`, copies CSV result. |
| Update XML file | Ensures missing metadata-mapped XML nodes are created and writes updated XML. |

## 5.6 Scripting tab

Primary purpose: manage JavaScript file content and script run arguments.

| Control | What it does |
| --- | --- |
| Script path field | Holds JS file path. |
| Browse | Selects JS file path. |
| Load | Loads JS content into editor. |
| Save | Saves editor text to file. |
| Script editor | Editable JS workspace. |
| Copy Script Run Args | Copies command fragment: `--script "path"`. |
| Workspace tree | Shows Global/Model placeholders and script line/char counts. |

## 5.7 Runtime tab

Primary purpose: runtime download, activation, and compatibility checks.

| Control | What it does |
| --- | --- |
| GitHub repo | Release source repository (`owner/repo`). |
| Check Latest | Fetches latest release assets from GitHub API. |
| Install Latest (Windows) | Downloads and installs best-scored Windows runtime asset. |
| Refresh Local | Reloads local runtime inventory. |
| Latest Release Assets | Shows asset list from latest release payload. |
| Installed Runtimes | Lists local runtime installs (`*` marks active). |
| Activate Selected Runtime | Sets active runtime tag in runtime index. |
| Refresh Compatibility Check | Rebuilds module compatibility matrix. |
| Compatibility tree | Compares source plugins, XML enabled modules, active runtime module detection. |
| Runtime status label | Shows operation status and errors. |

Windows runtime storage default:

1. `%LOCALAPPDATA%\iLANDWorkbenchQGIS\runtimes`
2. Runtime inventory index: `index.json` in that folder.

Compatibility status meanings:

1. `Aligned`
2. `Enabled in XML but not detected in runtime`
3. `Enabled in XML (activate a runtime to verify)`
4. `Runtime-only module`
5. `Available in source, not enabled in XML`

## 5.8 Debug Data tab

Primary purpose: select debug output categories and generate debug CLI arguments.

Debug data items:

1. Tree NPP
2. Tree Partition
3. Tree Growth
4. Water Output
5. Daily responses Output
6. Establishment
7. Sapling growth
8. Carbon Cycle
9. Performance
10. Dynamic Output

Actions:

| Control | What it does |
| --- | --- |
| Select Data Types | Toggle-select all debug data checkboxes. |
| Clear Debug Output | Clears debug output log panel. |
| Copy Debug Args | Copies selected debug key-value arguments to clipboard. |
| Debug output log | Shows debug actions and copied argument lines. |

Example generated args include:

1. `debug.tree_npp=true`
2. `debug.tree_growth=true`
3. `output.dynamic.enabled=true`

## 5.9 Modules tab

Primary purpose: inspect discovered module and submodule source structure.

| Area | What it does |
| --- | --- |
| Left tree | Shows modules and nested submodules. |
| Summary panel | Shows selected item type, submodule count, file count. |
| Path label | Shows module/submodule path. |
| Files list | Shows source files at selected level. |

## 6. Settings Dialog Deep Guide

Open via `Settings -> Open Settings Dialog`.

## 6.1 Layout

1. Left panel: category/tab tree.
2. Right panel: tab title, description, and field editors.
3. Bottom row: dirty state indicator, save/cancel controls.

## 6.2 Toolbar modes

| Button | Meaning |
| --- | --- |
| Simple view | Only settings marked as simple visibility. |
| Advanced view | Includes simple + advanced settings. |
| Show all | Includes deprecated/all settings. |
| Show changes | Opens changed-values table (new vs old values). |

## 6.3 Save behavior

1. `Save Changes` writes pending edits into current XML and closes dialog.
2. `Save as...` writes edits to a new XML path and switches current project file to that path.
3. `Cancel` closes without writing pending edits.

## 6.4 Change tracking

1. Any edited field is compared against loaded XML value.
2. Changed fields are marked pending.
3. `Show changes` table displays:
   label, new value, old value, parent tab.

## 7. Processing Toolbox Reference

Provider name: `iLAND` / `iLAND Workbench`.

Algorithms:

| Algorithm | Purpose |
| --- | --- |
| List iLAND modules (`list_modules`) | Scans source tree and exports modules/submodules to JSON. |
| Build iLAND run command (`build_run_command`) | Builds command-line preview (does not execute run). |
| Get latest iLAND release info (`latest_release_info`) | Fetches latest release metadata from GitHub API. |

Typical use:

1. Open Processing Toolbox.
2. Expand provider `iLAND`.
3. Run selected algorithm.

## 8. Output and Auto-Load Behavior

After successful run completion, plugin attempts auto-load:

1. GIS rasters from project `gis` folder (`.asc`, `.tif`, `.tiff`).
2. Preferred output tables from `output/output.sqlite`:
   `landscape`, `dynamicstand`, `wind`, `barkbeetle` (if tables exist).
3. Status summary reports loaded layer/table count and linked sqlite file count.

## 9. Compatibility Modes and Runtime Notes

The plugin supports two execution patterns:

1. Persistent session mode (preferred):
   Uses `--session` backend commands such as `CREATE`, `RUN_ONE_YEAR`.
2. Compatibility one-shot mode (legacy runtime fallback):
   Used when runtime does not support session mode.

If wrong executable is selected:

1. Plugin checks that filename is `iLANDc.exe`.
2. GUI executable (`iLAND.exe`) is rejected for run lifecycle operations.

## 10. Troubleshooting

## 10.1 Create/Run buttons do not start

Checklist:

1. Project XML path exists.
2. Active runtime is set in Runtime tab.
3. Active executable is `iLANDc.exe`.
4. No model run is already in progress.

## 10.2 Runtime install fails

Checklist:

1. Confirm network access to GitHub API/releases.
2. Confirm repo string format `owner/repo`.
3. Try `Check Latest` first, then install again.
4. Verify installed runtime appears in local list.

## 10.3 Visualization finds no layer

Checklist:

1. Ensure output folder actually contains rasters.
2. Confirm mode-specific outputs exist for selected mode.
3. For `seed availability`, select species first.
4. Try `other grid` with a specific hint token.

## 10.4 Settings changes not appearing

Checklist:

1. Ensure you clicked `Save Changes` or `Save as...`.
2. Verify you edited the correct tab/field.
3. Use `Show changes` before save to confirm pending modifications.


## 11. Recommended Daily Project Routine

1. Open plugin dock.
2. Set `Project XML` and output path.
3. Refresh species list.
4. Check runtime active selection.
5. Create model.
6. Run one-year smoke step.
7. Run full years.
8. Load latest output layer.
9. Apply visualization mode and inspect map.
10. Archive logs and copy debug/script args when needed.

