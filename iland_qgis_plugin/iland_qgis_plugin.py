# /********************************************************************************************
##
# iLAND Workbench — QGIS plugin for iLAND‑based ecological modeling
# Copyright (C) 2026 Sushil Paudel
#
# This plugin is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# A full copy of the license can be found in the <a href="LICENSE">LICENSE file</a>.
#
# This plugin integrates iLand, an individual‑based forest landscape and disturbance model.
# Copyright (C) 2009-2026 Werner Rammer, Rupert Seidl
# For more information on the original iLand model, see https://iland-model.org
# ********************************************************************************************/

"""Main plugin bootstrap for the iLAND Workbench QGIS plugin."""

from __future__ import annotations

import importlib.util
from pathlib import Path

try:
    from qgis.PyQt.QtCore import QCoreApplication, QLocale, Qt, QTranslator, QUrl  # type: ignore[import-not-found]
    from qgis.PyQt.QtGui import QAction, QDesktopServices, QIcon  # type: ignore[import-not-found]
    from qgis.PyQt.QtWidgets import QDockWidget, QMenu  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - non-QGIS fallback for tooling/QGIS4 transition
    from PyQt6.QtCore import QCoreApplication, QLocale, Qt, QTranslator, QUrl  # type: ignore[import-not-found]
    from PyQt6.QtGui import QAction, QDesktopServices, QIcon  # type: ignore[import-not-found]
    from PyQt6.QtWidgets import QDockWidget, QMenu  # type: ignore[import-not-found]

from .config_manager import ILandPluginConfig
from .iland_dock_widget import ILandDockWidget
from .processing_provider import ILandProcessingProvider


class iLandWorkbenchPlugin:
    """QGIS plugin class loaded by classFactory."""

    ACTION_OBJECT_NAME = "ilandWorkbenchAction"
    DOCK_OBJECT_NAME = "iLANDWorkbenchDock"
    MENU_OBJECT_NAME = "iLANDWorkbenchMainMenu"
    MENU_NAME = "&iLAND"
    ACTION_TEXT = "iLAND Workbench"
    HELP_ACTION_OBJECT_NAME = "ilandWorkbenchHelpAction"
    MODULES_ACTION_OBJECT_NAME = "ilandWorkbenchModulesAction"
    PROCESSING_ACTION_PREFIX = "ilandWorkbenchProcessingAction_"

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        self.config = ILandPluginConfig(plugin_dir=self.plugin_dir)
        self.repo_root = self.config.get_repo_root()
        self.action = None
        self.help_action = None
        self.modules_action = None
        self.dock_widget = None
        self.processing_provider = None
        self.translator = None
        self.translator_path = None
        self._new_project_action = None
        self._new_project_source = None
        self._reset_after_new_project = True
        self.processing_actions = []
        self.main_menu = None

    def initGui(self):
        self._cleanup_stale_ui()
        self._init_locale()
        self._ensure_main_menu()

        icon_file = self.plugin_dir / "res" / "icon4.png"
        if not icon_file.exists():
            icon_file = self.plugin_dir / "res" / "icon.svg"
        icon_path = str(icon_file)
        self.action = QAction(QIcon(icon_path), "iLAND Workbench", self.iface.mainWindow())
        self.action.setObjectName(self.ACTION_OBJECT_NAME)
        self.action.setStatusTip("Open iLAND Workbench")
        self.action.setWhatsThis("Open iLAND Workbench dock panel")
        self.action.triggered.connect(self.run)
        action_title = self.tr("iLAND Workbench")
        self.action.setText(action_title)

        self.iface.addToolBarIcon(self.action)
        self._register_processing_provider()
        self._init_processing_menu_actions()
        self._init_modules_action()
        self._init_help_action(icon_path)
        self._connect_new_project_hooks()

    def unload(self):
        self._remove_modules_action()
        self._remove_help_action()

        if self.action is not None:
            self._remove_action_from_menu(self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None

        self._remove_processing_menu_actions()
        self._remove_main_menu()
        self._unregister_processing_provider()
        self._disconnect_new_project_hooks()

        if self.dock_widget is not None:
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget.deleteLater()
            self.dock_widget = None

        self._teardown_locale()

        # Defensive cleanup for stale UI artifacts after plugin reload/update cycles.
        self._cleanup_stale_ui()

    def run(self):
        self.repo_root = self.config.get_repo_root()
        if self.dock_widget is None:
            self.dock_widget = ILandDockWidget(
                repo_root=self.repo_root,
                plugin_dir=self.plugin_dir,
                config=self.config,
                parent=self.iface.mainWindow(),
                iface=self.iface,
            )
            self.dock_widget.setAllowedAreas(
                Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
            )
            self._add_or_tabify_dock_widget(self.dock_widget)
        else:
            self.dock_widget.set_repo_root(self.repo_root)

        self.dock_widget.refresh_modules()
        self.dock_widget.show()
        self.dock_widget.raise_()

    def _add_or_tabify_dock_widget(self, new_dock):
        """Add dock in right area and tabify with an existing visible dock when possible."""
        main_window = self.iface.mainWindow()
        preferred_area = Qt.DockWidgetArea.RightDockWidgetArea
        target_dock = None

        for dock in main_window.findChildren(QDockWidget):
            if dock is None or dock is new_dock or not dock.isVisible():
                continue
            if dock.objectName() == self.DOCK_OBJECT_NAME:
                continue

            try:
                dock_area = main_window.dockWidgetArea(dock)
            except (AttributeError, RuntimeError, TypeError):
                continue

            if dock_area not in (
                Qt.DockWidgetArea.LeftDockWidgetArea,
                Qt.DockWidgetArea.RightDockWidgetArea,
            ):
                continue

            preferred_area = dock_area
            target_dock = dock

            dock_label = f"{dock.objectName()} {dock.windowTitle()}".lower()
            if "processing" in dock_label or "browser" in dock_label:
                break

        self.iface.addDockWidget(preferred_area, new_dock)

        if target_dock is not None:
            try:
                main_window.tabifyDockWidget(target_dock, new_dock)
            except (AttributeError, RuntimeError, TypeError):
                pass

    def _register_processing_provider(self):
        try:
            from qgis.core import QgsApplication  # type: ignore[import-not-found]
        except ImportError:
            return

        if self.processing_provider is None:
            self.processing_provider = ILandProcessingProvider(repo_root=self.repo_root)

        registry = QgsApplication.processingRegistry()
        if registry.providerById(self.processing_provider.id()) is None:
            registry.addProvider(self.processing_provider)

    def _unregister_processing_provider(self):
        if self.processing_provider is None:
            return

        try:
            from qgis.core import QgsApplication  # type: ignore[import-not-found]
        except ImportError:
            self.processing_provider = None
            return

        registry = QgsApplication.processingRegistry()
        registry.removeProvider(self.processing_provider)
        self.processing_provider = None

    def _cleanup_stale_ui(self):
        # Safety guard for QGIS 4 / Qt6.
        # Aggressive action/dock cleanup is primarily needed for plugin reload cycles,
        # but it can destabilize UI objects during startup in some builds.
        try:
            from qgis.core import Qgis  # type: ignore[import-not-found]

            if int(getattr(Qgis, "QGIS_VERSION_INT", 0)) >= 40000:
                return
        except Exception:
            pass

        main_window = self.iface.mainWindow()

        # QGIS 4 / Qt6: deleting QAction objects while toolbars are active can
        # leave dangling C++ references and cause access violations on mouse events.
        # Keep action cleanup non-destructive; unload() handles normal teardown.
        for action in main_window.findChildren(QAction):
            action_name = action.objectName() or ""
            if (
                action_name
                not in {
                    self.ACTION_OBJECT_NAME,
                    self.HELP_ACTION_OBJECT_NAME,
                    self.MODULES_ACTION_OBJECT_NAME,
                }
                and not action_name.startswith(self.PROCESSING_ACTION_PREFIX)
            ):
                continue
            try:
                self.iface.removeToolBarIcon(action)
            except Exception:
                pass
            self._remove_action_from_menu(action)

        # Remove stale top-level iLAND menu from the menu bar.
        for menu in main_window.findChildren(QMenu):
            if menu.objectName() != self.MENU_OBJECT_NAME:
                continue
            try:
                menu_action = menu.menuAction()
                main_window.menuBar().removeAction(menu_action)
            except Exception:
                pass
            try:
                menu.deleteLater()
            except Exception:
                pass

        # Remove stale dock widgets with our known object name.
        for dock in main_window.findChildren(QDockWidget):
            if dock.objectName() != self.DOCK_OBJECT_NAME:
                continue
            try:
                self.iface.removeDockWidget(dock)
            except Exception:
                pass
            try:
                dock.deleteLater()
            except Exception:
                pass

    def _is_our_action(self, action: QAction) -> bool:
        action_name = action.objectName() or ""
        return action_name in {
            self.ACTION_OBJECT_NAME,
            self.HELP_ACTION_OBJECT_NAME,
            self.MODULES_ACTION_OBJECT_NAME,
        } or action_name.startswith(self.PROCESSING_ACTION_PREFIX)

    def _add_action_to_menu(self, action: QAction):
        if self.main_menu is not None:
            self.main_menu.addAction(action)
        else:
            self.iface.addPluginToMenu(self.MENU_NAME, action)

    def _remove_action_from_menu(self, action: QAction):
        try:
            if self.main_menu is not None:
                self.main_menu.removeAction(action)
            else:
                self.iface.removePluginMenu(self.MENU_NAME, action)
        except Exception:
            pass

    def _ensure_main_menu(self):
        main_window = self.iface.mainWindow()
        menu_bar = main_window.menuBar()

        for menu in main_window.findChildren(QMenu):
            if menu.objectName() == self.MENU_OBJECT_NAME:
                self.main_menu = menu
                return

        menu = QMenu(self.MENU_NAME, main_window)
        menu.setObjectName(self.MENU_OBJECT_NAME)

        actions = menu_bar.actions()
        help_index = -1
        for idx, action in enumerate(actions):
            menu_obj = action.menu()
            action_text = (action.text() or "").replace("&", "").lower()
            menu_title = (menu_obj.title() if menu_obj is not None else "").replace("&", "").lower()
            if action_text == "help" or menu_title == "help":
                help_index = idx
                break

        if help_index >= 0 and help_index + 1 < len(actions):
            menu_bar.insertMenu(actions[help_index + 1], menu)
        else:
            menu_bar.addMenu(menu)

        self.main_menu = menu

    def _remove_main_menu(self):
        if self.main_menu is None:
            return

        try:
            self.iface.mainWindow().menuBar().removeAction(self.main_menu.menuAction())
        except Exception:
            pass

        try:
            self.main_menu.deleteLater()
        except Exception:
            pass

        self.main_menu = None

    def tr(self, text: str) -> str:
        return QCoreApplication.translate("iLandWorkbenchPlugin", text)

    def _init_locale(self):
        locale_name = QLocale.system().name()
        i18n_dir = self.plugin_dir / "i18n"
        qm_candidates = [
            i18n_dir / f"iLAND_Workbench_{locale_name}.qm",
            i18n_dir / f"iLAND_Workbench_{locale_name.split('_')[0]}.qm",
            i18n_dir / "iLAND_Workbench_en.qm",
        ]

        for qm_path in qm_candidates:
            if not qm_path.exists():
                continue
            translator = QTranslator()
            if translator.load(str(qm_path)):
                QCoreApplication.installTranslator(translator)
                self.translator = translator
                self.translator_path = qm_path
                break

    def _teardown_locale(self):
        if self.translator is not None:
            QCoreApplication.removeTranslator(self.translator)
            self.translator = None
            self.translator_path = None

    def _init_help_action(self, icon_path: str):
        self.help_action = QAction(QIcon(icon_path), self.tr("iLAND Workbench Help"), self.iface.mainWindow())
        self.help_action.setObjectName(self.HELP_ACTION_OBJECT_NAME)
        self.help_action.setStatusTip(self.tr("Open iLAND Workbench help"))
        self.help_action.setWhatsThis(self.tr("Open local help page, falling back to project website"))
        self.help_action.triggered.connect(self._show_help)

        self._add_action_to_menu(self.help_action)

    def _init_modules_action(self):
        self.modules_action = QAction(self.tr("Get iLAND modules"), self.iface.mainWindow())
        self.modules_action.setObjectName(self.MODULES_ACTION_OBJECT_NAME)
        self.modules_action.setStatusTip(self.tr("List discovered iLAND modules"))
        self.modules_action.setWhatsThis(self.tr("Run module discovery for the configured iLAND source tree"))
        self.modules_action.triggered.connect(
            lambda checked=False: self._run_processing_algorithm("iland:list_modules")
        )

        if self.main_menu is not None:
            self.main_menu.addSeparator()
        self._add_action_to_menu(self.modules_action)

    def _remove_modules_action(self):
        if self.modules_action is None:
            return

        try:
            self.modules_action.triggered.disconnect()
        except Exception:
            pass

        self._remove_action_from_menu(self.modules_action)
        self.modules_action.deleteLater()
        self.modules_action = None

    def _remove_help_action(self):
        if self.help_action is None:
            return

        try:
            self._remove_action_from_menu(self.help_action)
        except Exception:
            pass
        self.help_action.deleteLater()
        self.help_action = None

    def _show_help(self):
        local_help = self.plugin_dir / "help" / "index.html"
        if local_help.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(local_help)))
            return
        QDesktopServices.openUrl(QUrl("https://iland-model.org/"))

    def _processing_menu_items(self):
        return [
            ("iland:validate_native_climate", self.tr("Validate existing iLand climate database")),
            ("iland:future_climate", self.tr("Future Climate")),
            ("iland:historical_climate_data", self.tr("Historical Climate Data")),
            ("iland:validate_climate_netcdf", self.tr("Validate daily climate NetCDF for iLand")),
            ("iland:build_climate_database_netcdf", self.tr("Build iLand climate database from daily NetCDF")),
            ("iland:build_climate_from_geotiff", self.tr("Build iLand climate from WorldClim/CMIP6 GeoTIFF")),
            ("iland:process_disturbance_history", self.tr("Process disturbance history for iLand")),
            ("iland:generate_data_templates", self.tr("Generate field data CSV templates")),
            ("iland:download_stand_grid_source", self.tr("Download stand-grid source data")),
            ("iland:build_landscape_from_plots", self.tr("Build iLand landscape from plot data")),
            ("iland:create_iland_project", self.tr("Create iLAND project")),
            ("iland:soil_data_download", self.tr("Soil Data Download")),
        ]

    def _init_processing_menu_actions(self):
        self._remove_processing_menu_actions()

        for algorithm_id, action_text in self._processing_menu_items():
            action = QAction(action_text, self.iface.mainWindow())
            action.setObjectName(
                f"{self.PROCESSING_ACTION_PREFIX}{algorithm_id.replace(':', '_')}"
            )
            action.triggered.connect(
                lambda checked=False, aid=algorithm_id: self._run_processing_algorithm(aid)
            )
            self._add_action_to_menu(action)
            self.processing_actions.append(action)

    def _remove_processing_menu_actions(self):
        if not self.processing_actions:
            return

        for action in self.processing_actions:
            try:
                action.triggered.disconnect()
            except Exception:
                pass
            self._remove_action_from_menu(action)
            action.deleteLater()

        self.processing_actions = []

    def _run_processing_algorithm(self, algorithm_id: str):
        if importlib.util.find_spec("processing") is None:
            self._push_message(
                self.tr("Processing unavailable"),
                self.tr("QGIS Processing framework is not available."),
                level="warning",
            )
            return

        processing = __import__("processing")  # type: ignore[import-not-found]
        try:
            processing.execAlgorithmDialog(algorithm_id, {})
        except Exception as exc:
            self._push_message(
                self.tr("Could not run processing tool"),
                self.tr(f"{algorithm_id}: {exc}"),
                level="critical",
            )

    def _push_message(self, title: str, text: str, level: str = "info"):
        bar_getter = getattr(self.iface, "messageBar", None)
        if callable(bar_getter):
            bar = bar_getter()
            if bar is not None:
                try:
                    from qgis.core import Qgis  # type: ignore[import-not-found]

                    qgis_level = {
                        "info": Qgis.MessageLevel.Info,
                        "warning": Qgis.MessageLevel.Warning,
                        "critical": Qgis.MessageLevel.Critical,
                    }.get(level, Qgis.MessageLevel.Info)
                    bar.pushMessage(title, text, level=qgis_level)
                    return
                except Exception:
                    pass

        try:
            from qgis.PyQt.QtWidgets import QMessageBox  # type: ignore[import-not-found]
        except Exception:  # pragma: no cover
            from PyQt6.QtWidgets import QMessageBox  # type: ignore[import-not-found]

        QMessageBox.warning(self.iface.mainWindow(), title, text)

    def _connect_new_project_hooks(self):
        action_getter = getattr(self.iface, "actionNewProject", None)
        if callable(action_getter):
            action = action_getter()
            if action is not None:
                try:
                    action.triggered.connect(self._on_qgis_new_project_triggered)
                    self._new_project_action = action
                except Exception:
                    self._new_project_action = None

        if hasattr(self.iface, "newProjectCreated"):
            try:
                self.iface.newProjectCreated.connect(self._on_qgis_new_project_created)
                self._new_project_source = "iface"
                return
            except Exception:
                pass

        try:
            from qgis.core import QgsProject  # type: ignore[import-not-found]
            project = QgsProject.instance()
            if hasattr(project, "cleared"):
                project.cleared.connect(self._on_qgis_new_project_created)
                self._new_project_source = "project"
        except Exception:
            self._new_project_source = None

    def _disconnect_new_project_hooks(self):
        if self._new_project_action is not None:
            try:
                self._new_project_action.triggered.disconnect(self._on_qgis_new_project_triggered)
            except Exception:
                pass
            self._new_project_action = None

        if self._new_project_source == "iface" and hasattr(self.iface, "newProjectCreated"):
            try:
                self.iface.newProjectCreated.disconnect(self._on_qgis_new_project_created)
            except Exception:
                pass
        elif self._new_project_source == "project":
            try:
                from qgis.core import QgsProject  # type: ignore[import-not-found]
                QgsProject.instance().cleared.disconnect(self._on_qgis_new_project_created)
            except Exception:
                pass

        self._new_project_source = None
        self._reset_after_new_project = True

    def _on_qgis_new_project_triggered(self):
        self._reset_after_new_project = True
        if self.dock_widget is None:
            return

        try:
            self._reset_after_new_project = self.dock_widget.prepare_for_qgis_new_project()
        except Exception:
            self._reset_after_new_project = True

    def _on_qgis_new_project_created(self, *args):
        del args
        if self.dock_widget is None:
            self._reset_after_new_project = True
            return

        if not self._reset_after_new_project:
            self._reset_after_new_project = True
            return

        try:
            self.dock_widget.reset_for_qgis_new_project()
        except Exception:
            pass
        finally:
            self._reset_after_new_project = True
