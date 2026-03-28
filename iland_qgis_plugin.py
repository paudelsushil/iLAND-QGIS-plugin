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

from pathlib import Path

try:
    from PyQt6.QtCore import QCoreApplication, QLocale, Qt, QTranslator, QUrl  # type: ignore[import-not-found]
    from PyQt6.QtGui import QAction, QDesktopServices, QIcon  # type: ignore[import-not-found]
    from PyQt6.QtWidgets import QDockWidget  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - runtime fallback for QGIS 3.x
    from qgis.PyQt.QtCore import QCoreApplication, QLocale, Qt, QTranslator, QUrl  # type: ignore[import-not-found]
    from qgis.PyQt.QtGui import QAction, QDesktopServices, QIcon  # type: ignore[import-not-found]
    from qgis.PyQt.QtWidgets import QDockWidget  # type: ignore[import-not-found]

from .config_manager import ILandPluginConfig
from .iland_dock_widget import ILandDockWidget
from .processing_provider import ILandProcessingProvider


class iLandWorkbenchPlugin:
    """QGIS plugin class loaded by classFactory."""

    ACTION_OBJECT_NAME = "ilandWorkbenchAction"
    DOCK_OBJECT_NAME = "iLANDWorkbenchDock"
    MENU_NAME = "&iLAND"
    ACTION_TEXT = "iLAND Workbench"
    HELP_ACTION_OBJECT_NAME = "ilandWorkbenchHelpAction"

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        self.config = ILandPluginConfig(plugin_dir=self.plugin_dir)
        self.repo_root = self.config.get_repo_root()
        self.action = None
        self.help_action = None
        self.dock_widget = None
        self.processing_provider = None
        self.translator = None
        self.translator_path = None

    def initGui(self):
        self._cleanup_stale_ui()
        self._init_locale()

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
        self._add_action_to_menu(self.action)
        self._init_help_action(icon_path)
        self._register_processing_provider()

        # User requirement: open plugin tools in a dock sidebar immediately on load.
        self.run()

    def unload(self):
        self._remove_help_action()

        if self.action is not None:
            self._remove_action_from_menu(self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None

        self._unregister_processing_provider()

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
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_widget)
        else:
            self.dock_widget.set_repo_root(self.repo_root)

        self.dock_widget.refresh_modules()
        self.dock_widget.show()
        self.dock_widget.raise_()

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
        main_window = self.iface.mainWindow()

        # Remove stale toolbar/menu actions from previous plugin instances.
        for action in main_window.findChildren(QAction):
            if not self._is_our_action(action):
                continue
            try:
                self.iface.removeToolBarIcon(action)
            except Exception:
                pass
            self._remove_action_from_menu(action)
            try:
                action.deleteLater()
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
        return action.objectName() in {
            self.ACTION_OBJECT_NAME,
            self.HELP_ACTION_OBJECT_NAME,
        } or action.text() in {
            self.ACTION_TEXT,
            self.tr("iLAND Workbench Help"),
        }

    def _add_action_to_menu(self, action: QAction):
        if hasattr(self.iface, "addPluginToVectorMenu"):
            self.iface.addPluginToVectorMenu(self.MENU_NAME, action)
        else:
            self.iface.addPluginToMenu(self.MENU_NAME, action)

    def _remove_action_from_menu(self, action: QAction):
        try:
            if hasattr(self.iface, "removePluginVectorMenu"):
                self.iface.removePluginVectorMenu(self.MENU_NAME, action)
            else:
                self.iface.removePluginMenu(self.MENU_NAME, action)
        except Exception:
            pass

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

        if hasattr(self.iface, "pluginHelpMenu"):
            self.iface.pluginHelpMenu().addAction(self.help_action)
        else:
            self.iface.addPluginToMenu(self.MENU_NAME, self.help_action)

    def _remove_help_action(self):
        if self.help_action is None:
            return

        try:
            if hasattr(self.iface, "pluginHelpMenu"):
                self.iface.pluginHelpMenu().removeAction(self.help_action)
            else:
                self.iface.removePluginMenu(self.MENU_NAME, self.help_action)
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
