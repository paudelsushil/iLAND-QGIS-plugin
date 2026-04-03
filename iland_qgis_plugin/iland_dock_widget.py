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

"""Dockable iLAND workbench UI that mirrors the desktop app structure."""

# pyright: reportMissingImports=false

from __future__ import annotations

import os
import re
import signal
import shutil
import shlex
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
import xml.etree.ElementTree as ET


def _resolve_qt_attr(root, dotted_name: str):
    current = root
    for part in dotted_name.split("."):
        if not hasattr(current, part):
            return None
        current = getattr(current, part)
    return current


def _first_qt_attr(root, names: List[str]):
    for name in names:
        value = _resolve_qt_attr(root, name)
        if value is not None:
            return value
    raise AttributeError(f"Could not resolve Qt attributes: {names}")

try:
    from qgis.PyQt.QtCore import QTimer, Qt  # type: ignore[import-not-found]
    from qgis.PyQt.QtGui import QGuiApplication, QIcon, QPalette, QPixmap
    from qgis.PyQt.QtWidgets import (
        QButtonGroup,
        QCheckBox,
        QDialog,
        QComboBox,
        QDockWidget,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGroupBox,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QInputDialog,
        QListWidget,
        QListWidgetItem,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QRadioButton,
        QSplitter,
        QTabWidget,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
        QMessageBox,
    )  # type: ignore[import-not-found]

except ImportError:  # pragma: no cover - non-QGIS fallback for tooling/QGIS4 transition
    from PyQt6.QtCore import QTimer, Qt  # type: ignore[import-not-found]
    from PyQt6.QtGui import QGuiApplication, QIcon, QPalette, QPixmap
    from PyQt6.QtWidgets import (
        QButtonGroup,
        QCheckBox,
        QDialog,
        QComboBox,
        QDockWidget,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGroupBox,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QInputDialog,
        QListWidget,
        QListWidgetItem,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QRadioButton,
        QSplitter,
        QTabWidget,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
        QMessageBox,
    )  # type: ignore[import-not-found]


USER_ROLE = _first_qt_attr(Qt, ["ItemDataRole.UserRole", "UserRole"])
HORIZONTAL = _first_qt_attr(Qt, ["Orientation.Horizontal", "Horizontal"])
ASPECT_KEEP = _first_qt_attr(Qt, ["AspectRatioMode.KeepAspectRatio", "KeepAspectRatio"])
TRANSFORM_SMOOTH = _first_qt_attr(
    Qt,
    ["TransformationMode.SmoothTransformation", "SmoothTransformation"],
)
MSGBOX_YES = _resolve_qt_attr(QMessageBox, "StandardButton.Yes") or getattr(QMessageBox, "Yes")
MSGBOX_NO = _resolve_qt_attr(QMessageBox, "StandardButton.No") or getattr(QMessageBox, "No")

from .config_manager import ILandPluginConfig
from .iland_ui_catalog import ILandUICatalog
from .landscape_validation import ILandLandscapeValidator
from .module_registry import ILandModuleRegistry, ModuleInfo, SubmoduleInfo
from .runtime_manager import ILandRuntimeManager
from .settings_dialog import ILandSettingsDialog

try:
    from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    QgsProject = None
    QgsRasterLayer = None
    QgsVectorLayer = None


class ILandDockWidget(QDockWidget):
    """Main dock widget for iLAND workflow, settings, and module exploration."""

    DEBUG_DATA_ITEMS = [
        "Tree NPP",
        "Tree Partition",
        "Tree Growth",
        "Water Output",
        "Daily responses Output",
        "Establishment",
        "Sapling growth",
        "Carbon Cycle",
        "Performance",
        "Dynamic Output",
    ]

    def __init__(self, repo_root: Path, plugin_dir: Path, config: ILandPluginConfig, parent=None, iface=None):
        super().__init__("iLAND Workbench", parent)
        self.repo_root = Path(repo_root)
        self.plugin_dir = Path(plugin_dir)
        self.config = config
        self.iface = iface
        self.registry = ILandModuleRegistry(repo_root=self.repo_root)
        self.ui_catalog = ILandUICatalog(repo_root=self.repo_root)
        self.runtime_manager = ILandRuntimeManager(data_dir=self.config.data_dir)

        self.modules: List[ModuleInfo] = []
        self.settings_tab_map: Dict[str, List[str]] = {}
        self.settings_tab_layout: Dict[str, List[Dict[str, str]]] = {}
        self.settings_tab_titles: Dict[str, str] = {}
        self.settings_tab_descriptions: Dict[str, str] = {}
        self.settings_field_meta: Dict[str, Dict[str, str]] = {}
        self.settings_widget_map: Dict[str, Dict[str, object]] = {}
        self.settings_dirty_keys: Set[str] = set()
        self.settings_pending_values: Dict[str, str] = {}
        self.settings_loaded_values: Dict[str, str] = {}
        self.settings_current_tab_name: str = ""
        self.settings_current_tab_keys: List[str] = []
        self._settings_xml_tree: Optional[ET.ElementTree] = None
        self._settings_xml_path: Optional[Path] = None
        self.selected_module_payload: Optional[Dict[str, object]] = None
        self.latest_release_payload: Optional[Dict[str, object]] = None
        self.visual_mode_buttons: Dict[str, QRadioButton] = {}
        self.visual_toggle_boxes: Dict[str, QCheckBox] = {}
        self.debug_action_boxes: Dict[str, QCheckBox] = {}
        self.last_run_process: Optional[subprocess.Popen] = None
        self._session_process: Optional[subprocess.Popen] = None
        self._session_project_file: str = ""
        self._session_run_thread: Optional[threading.Thread] = None
        self._session_lock = threading.Lock()
        self._session_stop_requested = False
        self._session_last_error = ""
        self._session_run_requested_years = 0
        self._session_run_completed_years = 0
        self._session_run_finalize_pending = False
        self.last_run_started_at: Optional[datetime] = None
        self._model_paused = False
        self._model_created = False
        self._active_run_mode = ""
        self._current_year = 0
        self._active_target_year = 0
        self._active_requested_years = 0
        self._runtime_reported_year = 0
        self._last_run_year_request = 10
        self._legacy_cli_executable = ""
        self._is_loading_ui_state = False
        self._model_poll_timer = None
        self._workflow_log_full_backup = ""
        self._last_visual_value_preset = ""
        self._known_species_codes: List[str] = []
        self._runtime_module_cache_key = ""
        self._runtime_module_cache: Set[str] = set()
        self._model_progress_state = "idle"

        self.setObjectName("iLANDWorkbenchDock")
        self.setMinimumWidth(520)

        container = QWidget(self)
        root_layout = QVBoxLayout(container)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        splash = QLabel()
        splash.setMinimumHeight(96)
        splash.setMinimumWidth(170)
        splash_candidates = [
            self.plugin_dir / "res" / "iland_splash3.jpg",
        ]
        for splash_path in splash_candidates:
            if not splash_path.exists() or not splash_path.is_file():
                continue
            pixmap = QPixmap(str(splash_path))
            if pixmap.isNull():
                continue
            splash.setPixmap(pixmap.scaledToHeight(96, TRANSFORM_SMOOTH))
            break
        title = QLabel("iLAND Workbench")
        title.setObjectName("ilandTitle")
        title.setStyleSheet("font-size: 28px; font-weight: 700;")
        title.setAlignment(
            _first_qt_attr(Qt, ["AlignmentFlag.AlignLeft", "AlignLeft"])
            | _first_qt_attr(Qt, ["AlignmentFlag.AlignVCenter", "AlignVCenter"])
        )
        title.setMinimumHeight(96)
        header_row.addWidget(
            splash,
            0,
            _first_qt_attr(Qt, ["AlignmentFlag.AlignLeft", "AlignLeft"])
            | _first_qt_attr(Qt, ["AlignmentFlag.AlignVCenter", "AlignVCenter"]),
        )
        header_row.addWidget(
            title,
            1,
            _first_qt_attr(Qt, ["AlignmentFlag.AlignLeft", "AlignLeft"])
            | _first_qt_attr(Qt, ["AlignmentFlag.AlignVCenter", "AlignVCenter"]),
        )

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("summaryLabel")
        self.status_label.setWordWrap(True)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_workflow_tab(), "Workflow")
        self.tabs.addTab(self._build_settings_tab(), "Settings")
        self.tabs.addTab(self._build_visualization_tab(), "Visualization")
        self.tabs.addTab(self._build_view_tab(), "View")
        self.tabs.addTab(self._build_misc_tab(), "Misc")
        self.tabs.addTab(self._build_scripting_tab(), "Scripting")
        self.tabs.addTab(self._build_runtime_tab(), "Runtime")
        self.tabs.addTab(self._build_debug_data_tab(), "Debug Data")
        self.tabs.addTab(self._build_modules_tab(), "Modules")

        root_layout.addLayout(header_row)
        root_layout.addWidget(self.status_label)
        root_layout.addWidget(self.tabs)

        self.setWidget(container)
        self._apply_theme()
        self.refresh_modules()
        self._load_persisted_ui_state()

    def showEvent(self, event):
        self._apply_theme()
        super().showEvent(event)

    def closeEvent(self, event):
        self._stop_session()
        super().closeEvent(event)

    def _build_workflow_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setLabelAlignment(
            _first_qt_attr(Qt, ["AlignmentFlag.AlignRight", "AlignRight"])
            | _first_qt_attr(Qt, ["AlignmentFlag.AlignVCenter", "AlignVCenter"])
        )
        self.project_file_edit = QLineEdit()
        self.project_file_edit.setPlaceholderText("Path to xml project file...")
        self.project_file_create_button = QPushButton("Create Project")
        self.project_file_create_button.setMinimumHeight(28)
        self.project_file_create_button.setToolTip("Create iLAND project and load its XML")
        self.project_file_create_button.clicked.connect(self._create_project_from_workflow)
        self.project_file_browse_button = QPushButton("...")
        self.project_file_browse_button.setFixedSize(28, 28)
        self.project_file_browse_button.setToolTip("Load existing iLAND project XML")
        self.project_file_browse_button.clicked.connect(self._browse_project_xml)
        project_row = QHBoxLayout()
        project_row_widget = QWidget()
        project_row_widget.setLayout(project_row)
        project_row.addWidget(self.project_file_create_button)
        project_row.addWidget(self.project_file_edit)
        project_row.addWidget(self.project_file_browse_button)

        self.output_dir_edit = QLineEdit("")
        self.output_dir_edit.setPlaceholderText("Optional output directory (leave empty to use project output)")
        self.output_dir_browse_button = QPushButton("...")
        self.output_dir_browse_button.setFixedWidth(28)
        self.output_dir_browse_button.clicked.connect(self._browse_output_dir)
        output_row = QHBoxLayout()
        output_row_widget = QWidget()
        output_row_widget.setLayout(output_row)
        output_row.addWidget(self.output_dir_edit)
        output_row.addWidget(self.output_dir_browse_button)

        form.addRow(project_row_widget)
        form.addRow("Output directory", output_row_widget)
        self.current_year_label = QLabel("1")
        form.addRow("Current year", self.current_year_label)

        workflow_buttons = QHBoxLayout()
        self.create_button = QPushButton("Create Model")
        self.create_button.clicked.connect(self._create_model)
        self.destroy_button = QPushButton("Destroy")
        self.destroy_button.clicked.connect(self._destroy_model_state)
        self.reload_button = QPushButton("Reload")
        self.reload_button.clicked.connect(self._reload_model_state)
        self.run_one_year_button = QPushButton("Run one year")
        self.run_one_year_button.clicked.connect(self._run_one_year)
        self.run_button = QPushButton("Run Model")
        self.run_button.clicked.connect(self._run_model)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self._pause_or_continue_model)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self._stop_model)

        self._set_button_icon(self.create_button, "www.png")
        self._set_button_icon(self.destroy_button, "user-trash.png")
        self._set_button_icon(self.reload_button, "Backup Green Button.png")
        self._set_button_icon(self.run_one_year_button, "Play.png")
        self._set_button_icon(self.run_button, "Play All.png")
        self._set_button_icon(self.pause_button, "Pause.png")
        self._set_button_icon(self.stop_button, "process-stop.png")

        workflow_buttons.addWidget(self.create_button)
        workflow_buttons.addWidget(self.destroy_button)
        workflow_buttons.addWidget(self.reload_button)
        workflow_buttons.addWidget(self.run_one_year_button)
        self.open_output_button = QPushButton("Open Output Folder")
        self.open_output_button.clicked.connect(self._open_output_folder)
        self.load_layer_button = QPushButton("Load Latest Output Layer")
        self.load_layer_button.clicked.connect(self._load_latest_output_layer)
        workflow_buttons.addWidget(self.run_button)
        workflow_buttons.addWidget(self.pause_button)
        workflow_buttons.addWidget(self.stop_button)

        aux_buttons = QHBoxLayout()
        aux_buttons.addWidget(self.open_output_button)
        aux_buttons.addWidget(self.load_layer_button)

        status_row = QHBoxLayout()
        self.model_status_label = QLabel("Model status: idle")
        self.model_run_progress = QProgressBar()
        self.model_run_progress.setObjectName("modelRunProgress")
        self.model_run_progress.setTextVisible(False)
        self.model_run_progress.setMinimum(0)
        self.model_run_progress.setMaximum(1)
        self.model_run_progress.setValue(0)
        self._set_model_progress_state("idle")
        status_row.addWidget(self.model_status_label)
        status_row.addWidget(self.model_run_progress)

        log_controls = QHBoxLayout()
        self.log_filter_edit = QLineEdit()
        self.log_filter_edit.setPlaceholderText("Filter")
        self.log_filter_button = QPushButton("Filter")
        self.log_filter_button.clicked.connect(self._on_log_filter_execute)
        self.log_filter_clear_button = QPushButton("Clear Filter")
        self.log_filter_clear_button.clicked.connect(self._on_log_filter_clear)
        self.log_filter_clear_button.setEnabled(False)
        self.log_clear_button = QPushButton("clear Text")
        self.log_clear_button.clicked.connect(self._on_log_clear_text)
        self.log_copy_button = QPushButton("Copy to clipboard")
        self.log_copy_button.clicked.connect(self._on_log_copy)
        log_controls.addWidget(QLabel("Filter:"))
        log_controls.addWidget(self.log_filter_edit)
        log_controls.addWidget(self.log_filter_button)
        log_controls.addWidget(self.log_filter_clear_button)
        log_controls.addWidget(self.log_clear_button)
        log_controls.addWidget(self.log_copy_button)

        self.workflow_log_output = QPlainTextEdit()
        self.workflow_log_output.setReadOnly(True)
        self.workflow_log_output.setMinimumHeight(120)
        self.workflow_log_output.setPlaceholderText("Log output")

        layout.addLayout(form)
        layout.addLayout(workflow_buttons)
        layout.addLayout(aux_buttons)
        layout.addLayout(status_row)
        layout.addLayout(log_controls)
        layout.addWidget(self.workflow_log_output)
        self._update_run_controls_state()
        return widget

    def _build_settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        action_row = QHBoxLayout()
        self.settings_dialog_button = QPushButton("Open Settings Dialog")
        self._set_button_icon(self.settings_dialog_button, "load-settings.png")
        self.settings_dialog_button.clicked.connect(lambda: self._open_settings_dialog(self.settings_current_tab_name))
        action_row.addWidget(self.settings_dialog_button)
        action_row.addStretch(1)

        self.settings_summary = QLabel("Use Open Settings Dialog to edit project settings.")
        self.settings_summary.setWordWrap(True)

        # Keep an internal tree model for metadata mapping, but do not show it in the tab UI.
        self.settings_tree = QTreeWidget()
        self.settings_tree.setHeaderLabels(["iLAND Settings", "Type"])
        self.settings_tree.itemSelectionChanged.connect(self._on_settings_selection)
        self.settings_tree.hide()

        layout.addLayout(action_row)
        layout.addWidget(self.settings_summary)
        layout.addStretch(1)
        return widget

    def _build_visualization_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        mode_grid = QGridLayout()
        mode_grid.setHorizontalSpacing(16)
        mode_grid.setVerticalSpacing(6)
        mode_labels = [
            "Light influence field",
            "dominance grid",
            "seed availability",
            "Regeneration",
            "individual Trees",
            "Snags",
            "resource units",
            "other grid",
        ]
        self.visual_mode_group = QButtonGroup(widget)
        self.visual_mode_group.setExclusive(True)
        for idx, label in enumerate(mode_labels):
            button = QRadioButton(label)
            self.visual_mode_group.addButton(button)
            self.visual_mode_buttons[label] = button
            button.toggled.connect(self._on_visual_mode_toggled)
            mode_grid.addWidget(button, idx, 0)

        toggle_labels = [
            "based on stems",
            "established",
            "draw transparent",
            "color by species",
            "species shares",
            "clip to stands",
            "Autoscale colors",
            "Shading",
        ]
        for idx, label in enumerate(toggle_labels):
            box = QCheckBox(label)
            self.visual_toggle_boxes[label] = box
            mode_grid.addWidget(box, idx, 1)

        self.visual_other_grid_edit = QLineEdit()
        self.visual_other_grid_edit.setPlaceholderText("other grids")
        self.visual_expression_edit = QLineEdit()
        self.visual_expression_edit.setPlaceholderText("Expression")
        self.visual_expression_run_button = QPushButton("Run Expression")
        self.visual_expression_run_button.clicked.connect(self._run_visual_expression)
        self.visual_value_combo = QComboBox()
        self.visual_value_combo.addItems(["(value)", "tree.dbh", "tree.height", "ru.id", "species"])
        self.visual_value_combo.currentIndexChanged.connect(self._on_visual_value_changed)

        species_row = QHBoxLayout()
        self.visual_species_combo = QComboBox()
        self.visual_species_combo.addItem("<all species>", "")
        self.visual_species_refresh_button = QPushButton("Refresh Species")
        self.visual_species_refresh_button.clicked.connect(self._refresh_species_controls)
        self.visual_species_count_label = QLabel("0 species")
        species_row.addWidget(QLabel("Species"))
        species_row.addWidget(self.visual_species_combo, 1)
        species_row.addWidget(self.visual_species_refresh_button)
        species_row.addWidget(self.visual_species_count_label)

        action_row = QHBoxLayout()
        self.visual_apply_button = QPushButton("Apply Visualization")
        self.visual_apply_button.clicked.connect(self._apply_visualization_settings)
        self.visual_draw_button = QPushButton("Visualize On QGIS Map")
        self.visual_draw_button.clicked.connect(self._visualize_on_qgis_canvas)
        self.visual_reset_button = QPushButton("Reset")
        self.visual_reset_button.clicked.connect(self._reset_visualization_settings)
        action_row.addWidget(self.visual_apply_button)
        action_row.addWidget(self.visual_draw_button)
        action_row.addWidget(self.visual_reset_button)

        layout.addLayout(mode_grid)
        layout.addWidget(self.visual_other_grid_edit)
        expression_row = QHBoxLayout()
        expression_row.addWidget(self.visual_expression_edit)
        expression_row.addWidget(self.visual_expression_run_button)
        layout.addLayout(expression_row)
        layout.addWidget(self.visual_value_combo)
        layout.addLayout(species_row)
        layout.addLayout(action_row)
        return widget

    def _build_view_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        button_row = QHBoxLayout()
        self.view_repaint_button = QPushButton("Repaint")
        self.view_repaint_button.clicked.connect(self._on_view_repaint)
        self.view_full_extent_button = QPushButton("Show full extent")
        self.view_full_extent_button.clicked.connect(self._on_view_full_extent)
        self.view_copy_image_button = QPushButton("Copy Image to Clipboard")
        self.view_copy_image_button.clicked.connect(self._on_misc_copy_image)
        button_row.addWidget(self.view_repaint_button)
        button_row.addWidget(self.view_full_extent_button)
        button_row.addWidget(self.view_copy_image_button)

        self.view_status_label = QLabel("View actions ready.")
        self.view_status_label.setWordWrap(True)

        layout.addLayout(button_row)
        layout.addWidget(self.view_status_label)
        return widget

    def _build_misc_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        log_group = QGroupBox("Log Level")
        log_layout = QHBoxLayout(log_group)
        self.misc_log_level_group = QButtonGroup(log_group)
        self.misc_log_level_group.setExclusive(True)
        self.misc_log_level_buttons: Dict[str, QRadioButton] = {}
        for name in ["Debug", "Info", "Warning", "Error"]:
            button = QRadioButton(name)
            button.toggled.connect(self._on_misc_log_level_changed)
            self.misc_log_level_group.addButton(button)
            self.misc_log_level_buttons[name] = button
            log_layout.addWidget(button)

        action_row_1 = QHBoxLayout()
        self.misc_output_desc_button = QPushButton("Output table description")
        self.misc_output_desc_button.clicked.connect(self._on_misc_output_table_description)
        self.misc_timers_button = QPushButton("Log timers")
        self.misc_timers_button.clicked.connect(self._on_misc_log_timers)
        self.misc_test_button = QPushButton("Execute test")
        self.misc_test_button.clicked.connect(self._on_misc_execute_test)
        action_row_1.addWidget(self.misc_output_desc_button)
        action_row_1.addWidget(self.misc_timers_button)
        action_row_1.addWidget(self.misc_test_button)

        expression_row = QHBoxLayout()
        self.misc_expression_edit = QLineEdit("x^2")
        self.misc_expression_edit.setPlaceholderText("Expression plotter (use variable x)")
        self.misc_expression_button = QPushButton("Expression plotter")
        self.misc_expression_button.clicked.connect(self._on_misc_expression_plotter)
        expression_row.addWidget(self.misc_expression_edit)
        expression_row.addWidget(self.misc_expression_button)

        xml_row = QHBoxLayout()
        self.misc_update_xml_button = QPushButton("Update XML file")
        self.misc_update_xml_button.clicked.connect(self._on_misc_update_xml)
        xml_row.addWidget(self.misc_update_xml_button)

        self.misc_log_output = QPlainTextEdit()
        self.misc_log_output.setReadOnly(True)
        self.misc_log_output.setMinimumHeight(150)
        self.misc_log_output.setPlaceholderText("Misc tools output")

        layout.addWidget(log_group)
        layout.addLayout(action_row_1)
        layout.addLayout(expression_row)
        layout.addLayout(xml_row)
        layout.addWidget(self.misc_log_output)
        return widget

    def _build_scripting_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        path_row = QHBoxLayout()
        self.script_file_edit = QLineEdit()
        self.script_file_edit.setPlaceholderText("Path to JavaScript file used by iLAND workflow...")
        self.script_browse_button = QPushButton("Browse")
        self.script_browse_button.clicked.connect(self._browse_script_file)
        self.script_load_button = QPushButton("Load")
        self.script_load_button.clicked.connect(self._load_script_file)
        self.script_save_button = QPushButton("Save")
        self.script_save_button.clicked.connect(self._save_script_file)
        path_row.addWidget(self.script_file_edit)
        path_row.addWidget(self.script_browse_button)
        path_row.addWidget(self.script_load_button)
        path_row.addWidget(self.script_save_button)

        self.script_editor = QPlainTextEdit()
        self.script_editor.setPlaceholderText("JavaScript workspace (Ctrl+Enter behavior is in core iLAND GUI).")
        self.script_editor.setMinimumHeight(140)
        self.script_editor.textChanged.connect(self._refresh_script_workspace)

        action_row = QHBoxLayout()
        self.script_copy_cmd_button = QPushButton("Copy Script Run Args")
        self.script_copy_cmd_button.clicked.connect(self._copy_script_command_args)
        action_row.addWidget(self.script_copy_cmd_button)

        self.script_tree = QTreeWidget()
        self.script_tree.setHeaderLabels(["Workspace item", "Value"])
        self.script_tree.addTopLevelItem(QTreeWidgetItem(["Global", "object"]))
        self.script_tree.addTopLevelItem(QTreeWidgetItem(["Model", "object"]))

        layout.addLayout(path_row)
        layout.addWidget(self.script_editor)
        layout.addLayout(action_row)
        layout.addWidget(self.script_tree)
        return widget

    def _build_modules_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        splitter = QSplitter(HORIZONTAL)
        splitter.setChildrenCollapsible(False)

        left = QFrame()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.module_tree = QTreeWidget()
        self.module_tree.setHeaderLabels(["Module", "Type"])
        self.module_tree.itemSelectionChanged.connect(self._on_module_selection)
        left_layout.addWidget(self.module_tree)

        right = QFrame()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.module_summary = QLabel("Select a module to inspect details.")
        self.module_summary.setWordWrap(True)
        self.path_label = QLabel("Path: -")
        self.path_label.setWordWrap(True)
        self.files_list = QListWidget()
        right_layout.addWidget(self.module_summary)
        right_layout.addWidget(self.path_label)
        right_layout.addWidget(self.files_list)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        layout.addWidget(splitter)
        return widget

    def _build_runtime_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        repo_form = QFormLayout()
        self.runtime_repo_edit = QLineEdit(self.config.get_github_repo())
        repo_form.addRow("GitHub repo", self.runtime_repo_edit)

        button_row = QHBoxLayout()
        self.runtime_check_button = QPushButton("Check Latest")
        self.runtime_check_button.clicked.connect(self._on_check_latest_release)
        install_label = "Install Latest (Windows)" if os.name == "nt" else "Install Latest (Windows-only)"
        self.runtime_install_button = QPushButton(install_label)
        self.runtime_install_button.clicked.connect(self._on_install_latest_runtime)
        if os.name != "nt":
            self.runtime_install_button.setEnabled(False)
            self.runtime_install_button.setToolTip(
                "Automatic runtime install is currently supported on Windows only."
            )
        self.runtime_refresh_button = QPushButton("Refresh Local")
        self.runtime_refresh_button.clicked.connect(self._refresh_runtime_local_list)
        button_row.addWidget(self.runtime_check_button)
        button_row.addWidget(self.runtime_install_button)
        button_row.addWidget(self.runtime_refresh_button)

        self.runtime_status_label = QLabel("No release metadata loaded.")
        self.runtime_status_label.setWordWrap(True)

        self.runtime_assets_list = QListWidget()
        self.runtime_assets_list.setToolTip("Assets from latest release")

        self.runtime_local_list = QListWidget()
        self.runtime_local_list.setToolTip("Installed runtimes")

        self.runtime_activate_button = QPushButton("Activate Selected Runtime")
        self.runtime_activate_button.clicked.connect(self._on_activate_runtime)
        self.runtime_add_local_button = QPushButton("Add Local Runtime...")
        self.runtime_add_local_button.clicked.connect(self._on_add_local_runtime)

        self.runtime_compat_refresh_button = QPushButton("Refresh Compatibility Check")
        self.runtime_compat_refresh_button.clicked.connect(self._refresh_runtime_compatibility_panel)
        self.runtime_compat_tree = QTreeWidget()
        self.runtime_compat_tree.setHeaderLabels([
            "Module",
            "Source plugins",
            "Project XML",
            "Active runtime",
            "Status",
        ])
        self.runtime_compat_tree.setRootIsDecorated(False)
        self.runtime_compat_tree.setAlternatingRowColors(True)
        self.runtime_compat_summary = QLabel(
            "Compatibility check compares source plugins, project XML settings, and active runtime availability."
        )
        self.runtime_compat_summary.setWordWrap(True)

        layout.addLayout(repo_form)
        layout.addLayout(button_row)
        layout.addWidget(QLabel("Latest Release Assets"))
        layout.addWidget(self.runtime_assets_list)
        layout.addWidget(QLabel("Installed Runtimes"))
        layout.addWidget(self.runtime_local_list)
        layout.addWidget(self.runtime_activate_button)
        layout.addWidget(self.runtime_add_local_button)
        layout.addWidget(self.runtime_compat_refresh_button)
        layout.addWidget(self.runtime_compat_tree)
        layout.addWidget(self.runtime_compat_summary)
        layout.addWidget(self.runtime_status_label)
        return widget

    def _build_debug_data_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        self.debug_select_all_button = QPushButton("Select Data Types")
        self.debug_select_all_button.clicked.connect(self._on_select_all_debug_data)
        self.debug_clear_button = QPushButton("Clear Debug Output")
        self.debug_clear_button.clicked.connect(self._on_clear_debug_output)
        self.debug_copy_args_button = QPushButton("Copy Debug Args")
        self.debug_copy_args_button.clicked.connect(self._copy_debug_command_args)
        top_row.addWidget(self.debug_select_all_button)
        top_row.addWidget(self.debug_clear_button)
        top_row.addWidget(self.debug_copy_args_button)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        for idx, name in enumerate(self.DEBUG_DATA_ITEMS):
            box = QCheckBox(name)
            box.stateChanged.connect(self._on_debug_item_toggled)
            self.debug_action_boxes[name] = box
            row = idx % 5
            col = idx // 5
            grid.addWidget(box, row, col)

        self.debug_output_log = QPlainTextEdit()
        self.debug_output_log.setReadOnly(True)
        self.debug_output_log.setPlaceholderText("Debug output log and generated command previews appear here.")
        self.debug_output_log.setMinimumHeight(140)

        layout.addLayout(top_row)
        layout.addLayout(grid)
        layout.addWidget(self.debug_output_log)
        return widget

    def refresh_modules(self):
        self.modules = self.registry.discover()
        self._rebuild_settings_tree()
        self._rebuild_module_tree()
        self._refresh_runtime_local_list()
        self._refresh_runtime_compatibility_panel()

        module_count = len(self.modules)
        submodule_count = sum(self._count_submodules(module.submodules) for module in self.modules)
        self.status_label.setText(
            f"Discovered {module_count} modules, {submodule_count} submodules, and loaded iLAND UI catalogs."
        )

    def set_repo_root(self, repo_root: Path):
        self.repo_root = Path(repo_root)
        self.output_dir_edit.clear()
        self.registry = ILandModuleRegistry(repo_root=self.repo_root)
        self.ui_catalog = ILandUICatalog(repo_root=self.repo_root)
        self.refresh_modules()

    def _rebuild_settings_tree(self):
        self._load_settings_metadata()
        catalog = self.ui_catalog.discover_settings_catalog()
        if self.settings_tab_map:
            catalog.tab_settings = dict(self.settings_tab_map)
        else:
            self.settings_tab_map = catalog.tab_settings
        self.settings_tree.clear()

        for category, tabs in catalog.categories.items():
            category_item = QTreeWidgetItem([category, "category"])
            category_item.setData(0, USER_ROLE, {"kind": "category", "name": category})

            for tab in tabs:
                settings = catalog.tab_settings.get(tab, [])

                tab_item = QTreeWidgetItem([tab, "tab"])
                tab_item.setData(0, USER_ROLE, {"kind": "tab", "name": tab})
                tab_item.addChild(QTreeWidgetItem([f"{len(settings)} settings", "info"]))
                category_item.addChild(tab_item)

            if category_item.childCount() > 0:
                self.settings_tree.addTopLevelItem(category_item)

        self.settings_tree.expandToDepth(1)
        if self.settings_tree.topLevelItemCount() > 0:
            self.settings_tree.setCurrentItem(self.settings_tree.topLevelItem(0))

    def _settings_metadata_file(self) -> Path:
        candidates = [
            self.plugin_dir / "res" / "project_file_metadata.txt",
            self.ui_catalog.metadata_file,
            self.repo_root / "res" / "project_file_metadata.txt",
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate
        return candidates[0]

    def _normalize_tab_token(self, text: str) -> str:
        return "".join(ch for ch in text.lower() if ch.isalnum())

    def _tab_name_from_id(self, tab_id: str) -> str:
        raw = tab_id.strip()
        if raw.lower().startswith("tab"):
            raw = raw[3:]
        if not raw:
            return tab_id
        parts: List[str] = []
        token = raw[0]
        for ch in raw[1:]:
            if ch.isupper() and token:
                parts.append(token)
                token = ch
            else:
                token += ch
        if token:
            parts.append(token)
        pretty = " ".join(part.strip() for part in parts if part.strip())
        return pretty if pretty else tab_id

    def _canonical_settings_tab_name(self, tab_id: str, tab_label: str) -> str:
        known_tabs = self.ui_catalog.known_settings_tabs()
        normalized_known = {self._normalize_tab_token(name): name for name in known_tabs}

        candidates = [tab_label, self._tab_name_from_id(tab_id), tab_id]
        for candidate in candidates:
            normalized = self._normalize_tab_token(candidate)
            if normalized in normalized_known:
                return normalized_known[normalized]
        return tab_label or tab_id

    def _parse_metadata_value_parts(self, raw_value: str) -> List[str]:
        parts = [part.strip() for part in raw_value.split("|")]
        while len(parts) < 5:
            parts.append("")
        return parts

    def _load_settings_metadata(self):
        metadata_file = self._settings_metadata_file()
        if not metadata_file.exists():
            self.settings_tab_map = {}
            self.settings_tab_layout = {}
            self.settings_tab_titles = {}
            self.settings_tab_descriptions = {}
            self.settings_field_meta = {}
            return

        tab_map: Dict[str, List[str]] = {}
        tab_layout: Dict[str, List[Dict[str, str]]] = {}
        tab_titles: Dict[str, str] = {}
        tab_descriptions: Dict[str, str] = {}
        field_meta: Dict[str, Dict[str, str]] = {}

        current_tab = "General"

        for raw_line in metadata_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith(";") or "=" not in line:
                continue
            key, value = [part.strip() for part in line.split("=", 1)]
            parts = self._parse_metadata_value_parts(value)
            input_type = parts[0]

            if key == "gui.layout":
                if input_type == "tab":
                    tab_id = parts[1] or "tabUnknown"
                    tab_label = parts[2] or tab_id
                    tab_desc = parts[3]
                    current_tab = self._canonical_settings_tab_name(tab_id, tab_label)
                    tab_map.setdefault(current_tab, [])
                    tab_layout.setdefault(current_tab, [])
                    tab_titles[current_tab] = tab_label
                    if tab_desc:
                        tab_descriptions[current_tab] = tab_desc
                elif input_type in {"group", "layout"}:
                    tab_layout.setdefault(current_tab, []).append(
                        {
                            "kind": input_type,
                            "label": parts[1],
                            "description": parts[2],
                        }
                    )
                continue

            if key in field_meta:
                # Keep first definition for full metadata and treat subsequent references as connected aliases.
                if input_type == "connected":
                    tab_layout.setdefault(current_tab, []).append(
                        {
                            "kind": "connected",
                            "key": key,
                            "label": parts[1],
                            "description": "",
                        }
                    )
                continue

            field_meta[key] = {
                "type": input_type,
                "default": parts[1],
                "label": parts[2] or key,
                "tooltip": parts[3],
                "visibility": parts[4] or "simple",
            }
            tab_map.setdefault(current_tab, []).append(key)
            tab_layout.setdefault(current_tab, []).append(
                {
                    "kind": "field",
                    "key": key,
                }
            )

        self.settings_tab_map = tab_map
        self.settings_tab_layout = tab_layout
        self.settings_tab_titles = tab_titles
        self.settings_tab_descriptions = tab_descriptions
        self.settings_field_meta = field_meta

    def _ensure_settings_xml_loaded(self, force_reload: bool = False, silent: bool = False) -> bool:
        xml_path_raw = self.project_file_edit.text().strip()
        if not xml_path_raw:
            if not silent:
                self.status_label.setText("Select Project XML in Workflow tab before editing settings.")
            self._settings_xml_tree = None
            self._settings_xml_path = None
            return False

        xml_path = Path(xml_path_raw)
        if not xml_path.exists() or not xml_path.is_file():
            if not silent:
                self.status_label.setText(f"Settings XML not found: {xml_path}")
            self._settings_xml_tree = None
            self._settings_xml_path = None
            return False

        if (
            not force_reload
            and self._settings_xml_tree is not None
            and self._settings_xml_path is not None
            and self._settings_xml_path.resolve() == xml_path.resolve()
        ):
            return True

        try:
            self._settings_xml_tree = ET.parse(xml_path)
            self._settings_xml_path = xml_path
            self.settings_loaded_values = {}
            self.settings_pending_values = {}
            self.settings_dirty_keys.clear()

            root = self._settings_xml_tree.getroot()
            for key in self.settings_field_meta.keys():
                node = self._ensure_xml_node(root, key)
                self.settings_loaded_values[key] = (node.text or "").strip()

            self._update_settings_dirty_state()
            self.status_label.setText(f"Loaded settings from: {xml_path.name}")
            return True
        except Exception as exc:
            self._settings_xml_tree = None
            self._settings_xml_path = None
            if not silent:
                self.status_label.setText(f"Could not load settings XML: {exc}")
            return False

    def _ensure_xml_node(self, root: ET.Element, key: str) -> ET.Element:
        node = root
        for part in [part for part in key.split(".") if part]:
            child = node.find(part)
            if child is None:
                child = ET.SubElement(node, part)
                child.text = ""
            node = child
        return node

    def _clear_settings_editor_layout(self):
        while self.settings_editor_layout.count():
            item = self.settings_editor_layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                while child_layout.count():
                    child_item = child_layout.takeAt(0)
                    child_widget = child_item.widget()
                    if child_widget is not None:
                        child_widget.deleteLater()

    def _on_settings_load_xml(self):
        if self.settings_pending_values and self.settings_dirty_keys:
            choice = QMessageBox.question(
                self,
                "Discard unsaved changes?",
                "Reloading XML will discard pending settings changes. Continue?",
                MSGBOX_YES | MSGBOX_NO,
            )
            if choice != MSGBOX_YES:
                return

        if self._ensure_settings_xml_loaded(force_reload=True):
            if self.settings_current_tab_name:
                self._render_settings_tab(self.settings_current_tab_name)
            self._update_settings_dirty_state()

    def _on_settings_save_changes(self):
        if not self.settings_pending_values:
            self.status_label.setText("No settings changes to save.")
            return
        if not self._ensure_settings_xml_loaded(silent=False):
            return
        if self._settings_xml_tree is None or self._settings_xml_path is None:
            self.status_label.setText("Settings XML is not loaded.")
            return

        try:
            root = self._settings_xml_tree.getroot()
            for key, value in self.settings_pending_values.items():
                node = self._ensure_xml_node(root, key)
                node.text = value
                self.settings_loaded_values[key] = value

            self._settings_xml_tree.write(self._settings_xml_path, encoding="utf-8", xml_declaration=True)
            changed_count = len(self.settings_pending_values)
            self.settings_pending_values.clear()
            self.settings_dirty_keys.clear()
            self._update_settings_dirty_state()
            self.status_label.setText(f"Saved {changed_count} settings to {self._settings_xml_path.name}.")
        except Exception as exc:
            self.status_label.setText(f"Could not save settings XML: {exc}")

    def _on_settings_revert_tab(self):
        if not self.settings_current_tab_name:
            return
        for key in self.settings_current_tab_keys:
            self.settings_pending_values.pop(key, None)
            self.settings_dirty_keys.discard(key)
        self._render_settings_tab(self.settings_current_tab_name)
        self._update_settings_dirty_state()
        self.status_label.setText(f"Reverted pending changes for '{self.settings_current_tab_name}'.")

    def _on_settings_update_xml(self):
        if not self._ensure_settings_xml_loaded(silent=False):
            return
        if self._settings_xml_tree is None or self._settings_xml_path is None:
            return

        root = self._settings_xml_tree.getroot()
        created = 0
        for key in self.settings_field_meta.keys():
            had_value = root.find("./" + "/".join(key.split("."))) is not None
            self._ensure_xml_node(root, key)
            if not had_value:
                created += 1

        try:
            self._settings_xml_tree.write(self._settings_xml_path, encoding="utf-8", xml_declaration=True)
            self.status_label.setText(
                f"Update XML complete: {created} missing keys added to {self._settings_xml_path.name}."
            )
            self._append_misc_log(
                f"Update XML from Settings tab: added {created} missing keys to {self._settings_xml_path.name}."
            )
        except Exception as exc:
            self.status_label.setText(f"Could not write updated XML: {exc}")

    def _format_settings_value_for_widget(self, key: str, value: str) -> str:
        meta = self.settings_field_meta.get(key, {})
        input_type = str(meta.get("type", "string")).lower()
        if input_type == "boolean":
            return "true" if value.strip().lower() in {"1", "true", "yes"} else "false"
        return value

    def _set_widget_value(self, widget_info: Dict[str, object], value: str):
        control = widget_info.get("control")
        widget_type = str(widget_info.get("type", "string")).lower()

        if isinstance(control, QCheckBox):
            control.setChecked(value.strip().lower() in {"1", "true", "yes"})
            return

        if isinstance(control, QComboBox):
            idx = control.findText(value)
            if idx < 0 and value:
                control.addItem(value)
                idx = control.findText(value)
            if idx >= 0:
                control.setCurrentIndex(idx)
            return

        if isinstance(control, QLineEdit):
            if widget_type in {"file", "directory", "path"}:
                control.setText(value)
            else:
                control.setText(value)

    def _get_widget_value(self, widget_info: Dict[str, object]) -> str:
        control = widget_info.get("control")
        if isinstance(control, QCheckBox):
            return "true" if control.isChecked() else "false"
        if isinstance(control, QComboBox):
            return control.currentText().strip()
        if isinstance(control, QLineEdit):
            return control.text().strip()
        return ""

    def _update_settings_dirty_state(self):
        dirty_count = len(self.settings_dirty_keys)
        if hasattr(self, "settings_dirty_label"):
            if dirty_count:
                self.settings_dirty_label.setText(f"Pending changes: {dirty_count}")
            else:
                self.settings_dirty_label.setText("No pending changes.")
        if hasattr(self, "settings_save_button"):
            self.settings_save_button.setEnabled(dirty_count > 0)
        if hasattr(self, "settings_revert_button"):
            self.settings_revert_button.setEnabled(bool(self.settings_current_tab_name))

    def _on_setting_widget_changed(self, key: str):
        widget_info = self.settings_widget_map.get(key)
        if not widget_info:
            return
        new_value = self._get_widget_value(widget_info)
        base_value = self.settings_loaded_values.get(key, "")
        if new_value == base_value:
            self.settings_pending_values.pop(key, None)
            self.settings_dirty_keys.discard(key)
        else:
            self.settings_pending_values[key] = new_value
            self.settings_dirty_keys.add(key)
        self._update_settings_dirty_state()

    def _create_settings_widget(self, key: str, field_meta: Dict[str, str]) -> Dict[str, object]:
        input_type = field_meta.get("type", "string").lower()
        tooltip = field_meta.get("tooltip", "")

        if input_type == "boolean":
            control = QCheckBox()
            control.stateChanged.connect(lambda _state, k=key: self._on_setting_widget_changed(k))
            control.setToolTip(tooltip)
            return {"type": input_type, "control": control}

        if input_type == "combo":
            control = QComboBox()
            for option in [part.strip() for part in field_meta.get("default", "").split(";") if part.strip()]:
                control.addItem(option)
            control.currentTextChanged.connect(lambda _value, k=key: self._on_setting_widget_changed(k))
            control.setToolTip(tooltip)
            return {"type": input_type, "control": control}

        if input_type in {"file", "directory", "path"}:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)

            line_edit = QLineEdit()
            line_edit.textChanged.connect(lambda _text, k=key: self._on_setting_widget_changed(k))
            line_edit.setToolTip(tooltip)
            browse_button = QPushButton("...")
            browse_button.setFixedWidth(28)
            browse_button.clicked.connect(lambda _checked=False, k=key, t=input_type: self._browse_settings_path(k, t))

            row_layout.addWidget(line_edit)
            row_layout.addWidget(browse_button)
            return {"type": input_type, "control": line_edit, "container": row_widget}

        line_edit = QLineEdit()
        line_edit.textChanged.connect(lambda _text, k=key: self._on_setting_widget_changed(k))
        line_edit.setToolTip(tooltip)
        return {"type": input_type, "control": line_edit}

    def _browse_settings_path(self, key: str, input_type: str):
        widget_info = self.settings_widget_map.get(key)
        if not widget_info:
            return
        control = widget_info.get("control")
        if not isinstance(control, QLineEdit):
            return

        start_dir = control.text().strip() or str(self.repo_root)
        if input_type == "directory":
            selected = QFileDialog.getExistingDirectory(self, "Select directory", start_dir)
            if selected:
                control.setText(selected)
            return

        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select file",
            start_dir,
            "All files (*)",
        )
        if selected:
            control.setText(selected)

    def _render_settings_tab(self, tab_name: str):
        self.settings_current_tab_name = tab_name
        self.settings_widget_map = {}
        self.settings_current_tab_keys = []
        self._clear_settings_editor_layout()

        layout_spec = self.settings_tab_layout.get(tab_name, [])
        self.settings_tab_description.setText(self.settings_tab_descriptions.get(tab_name, ""))

        if not layout_spec:
            self.settings_editor_layout.addWidget(QLabel("No settings mapped for this tab."))
            self.settings_editor_layout.addStretch(1)
            self._update_settings_dirty_state()
            return

        if not self._ensure_settings_xml_loaded(silent=True):
            self.settings_editor_layout.addWidget(QLabel("Load/select a Project XML to edit settings values."))
            self.settings_editor_layout.addStretch(1)
            self._update_settings_dirty_state()
            return

        active_form_widget = QWidget()
        active_form_layout = QFormLayout(active_form_widget)
        active_form_layout.setContentsMargins(0, 0, 0, 0)
        active_form_layout.setSpacing(4)
        self.settings_editor_layout.addWidget(active_form_widget)

        seen_keys: Set[str] = set()
        for item in layout_spec:
            kind = item.get("kind", "")

            if kind == "layout" and item.get("label", "") == "hl":
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setFrameShadow(QFrame.Shadow.Sunken)
                self.settings_editor_layout.addWidget(line)
                continue

            if kind == "group":
                group_label = item.get("label", "").strip()
                if group_label:
                    heading = QLabel(group_label)
                    heading.setStyleSheet("font-weight: 700;")
                    self.settings_editor_layout.addWidget(heading)
                group_desc = item.get("description", "").strip()
                if group_desc:
                    desc = QLabel(group_desc)
                    desc.setWordWrap(True)
                    self.settings_editor_layout.addWidget(desc)
                group_widget = QWidget()
                active_form_layout = QFormLayout(group_widget)
                active_form_layout.setContentsMargins(0, 0, 0, 0)
                active_form_layout.setSpacing(4)
                self.settings_editor_layout.addWidget(group_widget)
                continue

            if kind not in {"field", "connected"}:
                continue

            key = item.get("key", "")
            if not key or key in seen_keys:
                continue
            field_meta = self.settings_field_meta.get(key)
            if not field_meta:
                continue
            seen_keys.add(key)

            widget_info = self._create_settings_widget(key, field_meta)
            self.settings_widget_map[key] = widget_info
            self.settings_current_tab_keys.append(key)

            label_text = item.get("label", "").strip() or field_meta.get("label", key)
            label_widget = QLabel(label_text)
            label_widget.setToolTip(field_meta.get("tooltip", ""))
            container_widget = widget_info.get("container", widget_info.get("control"))
            if isinstance(container_widget, QWidget):
                active_form_layout.addRow(label_widget, container_widget)

            value = self.settings_pending_values.get(key, self.settings_loaded_values.get(key, ""))
            value = self._format_settings_value_for_widget(key, value)
            self._set_widget_value(widget_info, value)

        self.settings_editor_layout.addStretch(1)
        self._update_settings_dirty_state()

    def _rebuild_module_tree(self):
        self.module_tree.clear()

        for module in self.modules:
            child_matches = self._matching_submodules(module.submodules, "")

            module_item = QTreeWidgetItem([module.name, "module"])
            module_item.setData(0, USER_ROLE, self._module_payload(module))
            for submodule in child_matches:
                module_item.addChild(self._build_submodule_item(submodule))
            self.module_tree.addTopLevelItem(module_item)

        self.module_tree.expandToDepth(1)
        if self.module_tree.topLevelItemCount() > 0:
            self.module_tree.setCurrentItem(self.module_tree.topLevelItem(0))

    def _count_submodules(self, submodules: List[SubmoduleInfo]) -> int:
        count = 0
        for submodule in submodules:
            count += 1 + self._count_submodules(submodule.children)
        return count

    def _matching_submodules(self, submodules: List[SubmoduleInfo], query: str) -> List[SubmoduleInfo]:
        if not query:
            return list(submodules)
        matched: List[SubmoduleInfo] = []
        for submodule in submodules:
            children = self._matching_submodules(submodule.children, query)
            if query in submodule.name.lower() or children:
                matched.append(
                    SubmoduleInfo(
                        name=submodule.name,
                        path=submodule.path,
                        files=list(submodule.files),
                        children=children,
                    )
                )
        return matched

    def _build_submodule_item(self, submodule: SubmoduleInfo) -> QTreeWidgetItem:
        item = QTreeWidgetItem([submodule.name, "submodule"])
        item.setData(0, USER_ROLE, self._submodule_payload(submodule))
        for child in submodule.children:
            item.addChild(self._build_submodule_item(child))
        return item

    def _module_payload(self, module: ModuleInfo) -> Dict[str, object]:
        return {
            "name": module.name,
            "path": module.path,
            "kind": "module",
            "files": module.files,
            "submodule_count": self._count_submodules(module.submodules),
        }

    def _submodule_payload(self, submodule: SubmoduleInfo) -> Dict[str, object]:
        return {
            "name": submodule.name,
            "path": submodule.path,
            "kind": "submodule",
            "files": submodule.files,
            "submodule_count": self._count_submodules(submodule.children),
        }

    def _on_module_selection(self):
        selected_items = self.module_tree.selectedItems()
        if not selected_items:
            return
        payload: Optional[Dict[str, object]] = selected_items[0].data(0, USER_ROLE)
        self.selected_module_payload = payload
        if not payload:
            return
        files = list(payload.get("files", []))
        self.module_summary.setText(
            f"{payload.get('name')} ({payload.get('kind')}) - submodules: "
            f"{payload.get('submodule_count', 0)}, files: {len(files)}"
        )
        self.path_label.setText(f"Path: {payload.get('path', '-')}")
        self.files_list.clear()
        if not files:
            self.files_list.addItem(QListWidgetItem("No source files found at this level."))
            return
        for file_name in files:
            self.files_list.addItem(QListWidgetItem(file_name))

    def _on_settings_selection(self):
        selected_items = self.settings_tree.selectedItems()
        if not selected_items:
            return
        payload = selected_items[0].data(0, USER_ROLE)
        if not payload:
            return

        kind = payload.get("kind")
        name = payload.get("name")

        if kind == "category":
            self.settings_summary.setText(f"{name}: select a tab to open the Settings dialog.")
            self.settings_current_tab_name = ""
            return

        if kind == "tab":
            keys = self.settings_tab_map.get(name, [])
            self.settings_summary.setText(f"{name}: {len(keys)} settings mapped from project_file_metadata.txt")
            self.settings_current_tab_name = str(name)
            self._open_settings_dialog(str(name))

    def _open_settings_dialog(self, initial_tab: str = ""):
        self._load_settings_metadata()
        catalog = self.ui_catalog.discover_settings_catalog()
        dialog = ILandSettingsDialog(
            self.repo_root,
            self.plugin_dir,
            self.project_file_edit.text().strip(),
            dict(catalog.categories),
            dict(self.settings_tab_map),
            dict(self.settings_tab_layout),
            dict(self.settings_tab_titles),
            dict(self.settings_tab_descriptions),
            dict(self.settings_field_meta),
            initial_tab,
            self,
        )

        if hasattr(dialog, "exec"):
            result = dialog.exec()
        else:
            result = dialog.exec_()
        accepted = _resolve_qt_attr(QDialog, "DialogCode.Accepted") or getattr(QDialog, "Accepted", 1)
        if result != accepted:
            return

        new_file = str(dialog.current_project_file).strip()
        if new_file and new_file != self.project_file_edit.text().strip():
            self.project_file_edit.setText(new_file)
            self._refresh_species_controls()
            self._refresh_runtime_compatibility_panel()
            self._update_run_controls_state()

        self._ensure_settings_xml_loaded(force_reload=True, silent=True)
        self.status_label.setText("Settings dialog changes applied.")

    def _browse_project_xml(self):
        start_dir = str(self.repo_root)
        current = self.project_file_edit.text().strip()
        if current:
            start_dir = str(Path(current).parent)
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select iLAND project XML",
            start_dir,
            "XML files (*.xml);;All files (*)",
        )
        if file_path:
            self.project_file_edit.setText(file_path)
            self._refresh_species_controls()
            self._refresh_runtime_compatibility_panel()
            self._update_run_controls_state()

    def _create_project_from_workflow(self):
        import importlib.util

        if importlib.util.find_spec("processing") is None:
            QMessageBox.warning(
                self,
                "Processing unavailable",
                "QGIS Processing framework is not available. Open Processing Toolbox and run iLAND > Create iLAND project.",
            )
            return

        processing = __import__("processing")  # type: ignore[import-not-found]
        result = processing.execAlgorithmDialog("iland:create_iland_project", {})

        if not isinstance(result, dict) or not result:
            return

        xml_path = str(
            result.get("OUTPUT_PROJECT_XML")
            or result.get("project_xml")
            or result.get("Project XML")
            or ""
        ).strip()
        if not xml_path:
            return

        self.project_file_edit.setText(xml_path)
        self.output_dir_edit.clear()
        self._refresh_species_controls()
        self._refresh_runtime_compatibility_panel()
        self._update_run_controls_state()
        self.status_label.setText("Created and loaded iLAND project XML.")

    def has_active_workflow_state(self) -> bool:
        project_file = self.project_file_edit.text().strip()
        output_dir = self.output_dir_edit.text().strip()
        has_log_text = bool(self.workflow_log_output.toPlainText().strip())
        return bool(project_file or output_dir or has_log_text or self._model_created or self._is_model_running())

    def prepare_for_qgis_new_project(self) -> bool:
        if not self.has_active_workflow_state():
            return True

        is_running = self._is_model_running()
        dialog = QMessageBox(self)
        dialog.setWindowTitle("New QGIS project detected")
        dialog.setIcon(
            _first_qt_attr(QMessageBox, ["Icon.Warning", "Warning"])
            if is_running
            else _first_qt_attr(QMessageBox, ["Icon.Question", "Question"])
        )
        dialog.setText("Reset iLAND Workbench for the new QGIS project?")
        if is_running:
            dialog.setInformativeText(
                "Model processing is currently running. Choose Save/Save As first, then iLAND will stop and reset."
            )
        else:
            dialog.setInformativeText(
                "Choose Save, Save As, or Discard to reset plugin state for the new project."
            )

        save_button = dialog.addButton(
            "Save",
            _first_qt_attr(QMessageBox, ["ButtonRole.AcceptRole", "AcceptRole"]),
        )
        save_as_button = dialog.addButton(
            "Save As...",
            _first_qt_attr(QMessageBox, ["ButtonRole.ActionRole", "ActionRole"]),
        )
        discard_button = dialog.addButton(
            "Discard",
            _first_qt_attr(QMessageBox, ["ButtonRole.DestructiveRole", "DestructiveRole"]),
        )
        keep_button = dialog.addButton(
            "Keep Current iLAND State",
            _first_qt_attr(QMessageBox, ["ButtonRole.RejectRole", "RejectRole"]),
        )
        dialog.exec()

        clicked = dialog.clickedButton()
        if clicked == keep_button:
            self.status_label.setText("Keeping current iLAND state for now.")
            return False

        if clicked == save_button and not self._save_current_qgis_project(mode="save"):
            self.status_label.setText("Project save was canceled; iLAND reset skipped.")
            return False
        if clicked == save_as_button and not self._save_current_qgis_project(mode="save_as"):
            self.status_label.setText("Save As was canceled; iLAND reset skipped.")
            return False
        if clicked not in {save_button, save_as_button, discard_button}:
            return False

        if self._is_model_running():
            self._stop_model()
            if self._is_model_running():
                QMessageBox.warning(
                    self,
                    "Reset deferred",
                    "Model is still stopping. Wait a moment and create a new project again.",
                )
                return False

        return True

    def reset_for_qgis_new_project(self):
        if self._is_model_running():
            self._stop_model()
            if self._is_model_running():
                self.status_label.setText("Model still running; reset deferred.")
                return

        if self._model_created or self._session_is_alive():
            self._destroy_model_state()

        self.project_file_edit.clear()
        self.output_dir_edit.clear()
        self._settings_xml_tree = None
        self._settings_xml_path = None
        self._known_species_codes = []
        self.workflow_log_output.clear()
        self._workflow_log_full_backup = ""
        self.log_filter_clear_button.setEnabled(False)
        self._set_current_year_display(0)
        self.model_status_label.setText("Model status: idle")
        self._set_model_progress_state("idle")
        self._refresh_species_controls()
        self._refresh_runtime_compatibility_panel()
        self._update_run_controls_state()
        self.status_label.setText("iLAND Workbench reset for new QGIS project.")

    def _save_current_qgis_project(self, mode: str) -> bool:
        if self.iface is None or QgsProject is None:
            return False

        project = QgsProject.instance()
        if mode == "save":
            if hasattr(self.iface, "actionSaveProject") and callable(self.iface.actionSaveProject):
                action = self.iface.actionSaveProject()
                if action is not None:
                    action.trigger()
            elif project.fileName():
                project.write(project.fileName())
            else:
                return self._save_current_qgis_project(mode="save_as")
        elif mode == "save_as":
            if hasattr(self.iface, "actionSaveProjectAs") and callable(self.iface.actionSaveProjectAs):
                action = self.iface.actionSaveProjectAs()
                if action is not None:
                    action.trigger()
            else:
                file_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "Save QGIS project as",
                    str(self._default_user_workspace_dir()),
                    "QGIS project (*.qgz *.qgs)",
                )
                if not file_path:
                    return False
                return bool(project.write(file_path))
        else:
            return False

        if project.fileName() and not project.isDirty():
            return True
        return False

    def _browse_output_dir(self):
        resolved = self._resolve_effective_output_dir(create=False)
        start_dir = str(resolved) if resolved is not None else str(self._default_user_workspace_dir())
        folder = QFileDialog.getExistingDirectory(self, "Select output directory", start_dir)
        if folder:
            self.output_dir_edit.setText(folder)

    def _default_user_workspace_dir(self) -> Path:
        documents = Path.home() / "Documents"
        if documents.exists():
            return documents
        return Path.home()

    def _resolve_effective_output_dir(self, create: bool = False) -> Optional[Path]:
        raw_override = self.output_dir_edit.text().strip()
        project_file = self.project_file_edit.text().strip()

        project_home: Optional[Path] = None
        project_output_setting = "output"

        if project_file:
            xml_path = Path(project_file)
            if xml_path.exists() and xml_path.is_file():
                project_home = xml_path.resolve().parent
                try:
                    root = ET.parse(xml_path).getroot()
                    home_node = root.find("./system/path/home")
                    if home_node is not None and (home_node.text or "").strip():
                        home_text = (home_node.text or "").strip()
                        candidate_home = Path(home_text)
                        if not candidate_home.is_absolute():
                            candidate_home = (project_home / candidate_home)
                        project_home = candidate_home.resolve()

                    output_node = root.find("./system/path/output")
                    if output_node is not None and (output_node.text or "").strip():
                        project_output_setting = (output_node.text or "").strip()
                except (ET.ParseError, OSError, ValueError):
                    pass

        if raw_override:
            candidate = Path(raw_override).expanduser()
            if not candidate.is_absolute():
                base = project_home or self._default_user_workspace_dir()
                candidate = base / candidate
            resolved = candidate.resolve()
        else:
            base = project_home or self._default_user_workspace_dir()
            output_candidate = Path(project_output_setting).expanduser()
            if output_candidate.is_absolute():
                resolved = output_candidate.resolve()
            else:
                resolved = (base / output_candidate).resolve()

        if create:
            resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    def _set_button_icon(self, button: QPushButton, icon_name: str):
        icon_path = self.plugin_dir / "res" / icon_name
        if icon_path.exists() and icon_path.is_file():
            button.setIcon(QIcon(str(icon_path)))

    def _is_model_running(self) -> bool:
        if self._session_run_thread is not None and self._session_run_thread.is_alive():
            return True
        return self.last_run_process is not None and self.last_run_process.poll() is None

    def _session_is_alive(self) -> bool:
        return self._session_process is not None and self._session_process.poll() is None

    def _parse_session_reply(self, line: str) -> Dict[str, str]:
        parts = line.strip().split("|")
        reply: Dict[str, str] = {"status": "ERR", "raw": line.strip()}
        if len(parts) < 2:
            return reply
        reply["status"] = parts[1].strip()
        for part in parts[2:]:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            reply[key.strip()] = value.strip()
        return reply

    def _parse_session_progress(self, line: str) -> Optional[int]:
        match = re.search(r"year=(\d+)", line)
        if not match:
            return None
        try:
            return int(match.group(1))
        except Exception:
            return None

    def _read_session_reply(self, timeout_seconds: int) -> Dict[str, str]:
        if not self._session_is_alive() or self._session_process is None or self._session_process.stdout is None:
            return {"status": "ERR", "msg": "session_not_running"}

        boot_lines: List[str] = []
        deadline = time.time() + max(1, timeout_seconds)
        while time.time() < deadline:
            line = self._session_process.stdout.readline()
            if line == "":
                reply: Dict[str, str] = {"status": "ERR", "msg": "session_closed"}
                if boot_lines:
                    reply["boot"] = "\n".join(boot_lines[-8:])
                return reply
            text = line.strip()
            if not text:
                continue
            if text.startswith("SESSION_PROGRESS|"):
                progress_year = self._parse_session_progress(text)
                if progress_year is not None:
                    self._runtime_reported_year = max(self._runtime_reported_year, progress_year)
                    self._set_current_year_display(max(self._current_year, self._runtime_reported_year))
                continue
            if text.startswith("SESSION|"):
                return self._parse_session_reply(text)
            self._append_workflow_log(text)
            boot_lines.append(text)

        return {"status": "ERR", "msg": "session_timeout"}

    def _normalized_executable_path(self, executable: Path | str) -> str:
        try:
            resolved = Path(executable).resolve()
        except Exception:
            resolved = Path(str(executable))
        return str(resolved).replace("\\", "/").lower()

    def _classify_session_startup_failure(self, ready: Dict[str, str], executable: Path) -> str:
        msg = str(ready.get("msg", "")).lower()
        boot = str(ready.get("boot", "")).lower()

        if "invalid number of years to run" in boot:
            return (
                "Selected iLANDc runtime uses legacy CLI signature and does not support --session mode. "
                "Workbench will use compatibility one-shot mode for create/run commands. "
                f"Current executable: {executable}"
            )
        if "usage:" in boot and "ilandc.exe <xml-project-file> <years>" in boot:
            return (
                "Selected iLANDc runtime is legacy CLI-only and does not support persistent session mode. "
                "Workbench will use compatibility one-shot mode."
            )
        if msg == "session_closed":
            return (
                "Session backend closed before handshake. This usually means an incompatible runtime binary or missing runtime dependencies. "
                f"Executable: {executable}"
            )
        return "iLAND runtime does not support persistent session mode. Install updated runtime."

    def _is_legacy_session_startup_failure(self, ready: Dict[str, str]) -> bool:
        boot = str(ready.get("boot", "")).lower()
        return (
            "invalid number of years to run" in boot
            or ("usage:" in boot and "ilandc.exe <xml-project-file> <years>" in boot)
        )

    def _session_command(self, command: str, timeout_seconds: int = 120) -> Dict[str, str]:
        with self._session_lock:
            if not self._session_is_alive() or self._session_process is None:
                return {"status": "ERR", "msg": "session_not_running"}
            if self._session_process.stdin is None:
                return {"status": "ERR", "msg": "session_stdin_unavailable"}
            try:
                self._session_process.stdin.write(command + "\n")
                self._session_process.stdin.flush()
            except Exception as exc:
                return {"status": "ERR", "msg": f"session_write_failed:{exc}"}
            return self._read_session_reply(timeout_seconds=timeout_seconds)

    def _stop_session(self):
        if not self._session_is_alive() or self._session_process is None:
            self._session_process = None
            self._session_project_file = ""
            return
        try:
            self._session_command("QUIT", timeout_seconds=10)
        except Exception:
            pass
        try:
            self._session_process.terminate()
            self._session_process.wait(timeout=3)
        except Exception:
            try:
                self._session_process.kill()
            except Exception:
                pass
        self._session_process = None
        self._session_project_file = ""

    def _ensure_session(self, project_file: str) -> bool:
        if self._session_is_alive() and self._session_project_file == project_file:
            return True

        self._stop_session()
        executable = self._resolve_or_install_executable()
        if executable is None:
            return False

        executable_key = self._normalized_executable_path(executable)
        if self._legacy_cli_executable and self._legacy_cli_executable != executable_key:
            self._legacy_cli_executable = ""
        if self._legacy_cli_executable == executable_key:
            self.model_status_label.setText("Model status: compatibility mode (legacy CLI)")
            self._set_model_progress_state("idle")
            self.status_label.setText("Legacy iLANDc detected. Using compatibility one-shot mode.")
            return False

        output_dir = self.output_dir_edit.text().strip()
        component_name = "all"
        if self.selected_module_payload:
            component_name = str(self.selected_module_payload.get("name", "all"))

        args = ["--session", project_file, "output.dynamic.enabled=true", f"component={component_name}"]
        if output_dir:
            args.append(f"system.path.output={output_dir}")

        project_dir = str(Path(project_file).resolve().parent)
        try:
            runtime_env = self._runtime_env_for_executable(executable)
            self._session_process = subprocess.Popen(
                [str(executable)] + args,
                cwd=project_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=runtime_env,
            )
            self._session_project_file = project_file
            ready = self._read_session_reply(timeout_seconds=30)
            if ready.get("status") != "OK":
                is_legacy = self._is_legacy_session_startup_failure(ready)
                if is_legacy:
                    self._legacy_cli_executable = executable_key
                    self._append_workflow_log(
                        "Runtime does not support --session mode; switching to compatibility one-shot CLI mode."
                    )
                    self._stop_session()
                    self.status_label.setText(self._classify_session_startup_failure(ready, executable))
                    self.model_status_label.setText("Model status: compatibility mode (legacy CLI)")
                    self._set_model_progress_state("idle")
                    return False
                else:
                    self._append_workflow_log(f"Session startup failed: {ready}")
                self._stop_session()
                self.status_label.setText(self._classify_session_startup_failure(ready, executable))
                self.model_status_label.setText("Model status: session start failed")
                self._set_model_progress_state("failed")
                return False

            self._append_workflow_log("Started persistent iLAND session backend.")
            self._legacy_cli_executable = ""
            self.config.set_string("workflow_last_project", project_file)
            if output_dir:
                self.config.set_string("workflow_output_dir", output_dir)
            self.config.set_string("workflow_executable_path", str(executable))
            return True
        except Exception as exc:
            self._stop_session()
            self.status_label.setText(f"Could not start session backend: {exc}")
            self.model_status_label.setText("Model status: session start failed")
            self._set_model_progress_state("failed")
            self._append_workflow_log(f"Session start failed: {exc}")
            return False

    def _update_run_controls_state(self):
        running = self._is_model_running()
        has_project = bool(self.project_file_edit.text().strip())
        can_run = self._model_created and (not running) and (not self._model_paused)

        if hasattr(self, "create_button"):
            self.create_button.setEnabled(has_project and (not running) and (not self._model_created))

        if hasattr(self, "run_button"):
            self.run_button.setEnabled(can_run)
        if hasattr(self, "run_one_year_button"):
            self.run_one_year_button.setEnabled(can_run)
        if hasattr(self, "reload_button"):
            self.reload_button.setEnabled(self._model_created and (not running))
        if hasattr(self, "destroy_button"):
            self.destroy_button.setEnabled(self._model_created and (not running))
        if hasattr(self, "pause_button"):
            self.pause_button.setEnabled(running)
            self.pause_button.setText("Continue" if self._model_paused else "Pause")
        if hasattr(self, "stop_button"):
            self.stop_button.setEnabled(running)

    def _set_current_year_display(self, year: int):
        self._current_year = max(0, int(year))
        if hasattr(self, "current_year_label"):
            self.current_year_label.setText(str(self._current_year))

    def _set_model_progress_state(self, state: str):
        if not hasattr(self, "model_run_progress"):
            return

        normalized = state if state in {"idle", "running", "paused", "success", "failed"} else "idle"
        if normalized == self._model_progress_state:
            return

        self._model_progress_state = normalized
        self.model_run_progress.setProperty("runState", normalized)
        style = self.model_run_progress.style()
        if style is not None:
            style.unpolish(self.model_run_progress)
            style.polish(self.model_run_progress)
        self.model_run_progress.update()

    def _run_one_year(self):
        if self._is_model_running():
            self.status_label.setText("A model run is already in progress.")
            return
        if not self._model_created:
            self.status_label.setText("Create Model first, then run one year.")
            return
        project_file = self.project_file_edit.text().strip()
        if not self._ensure_session(project_file):
            if self._legacy_cli_executable:
                target_year = max(1, self._current_year + 1)
                self._append_workflow_log(
                    f"Run one year: compatibility mode active, executing one-shot run to year {target_year}."
                )
                self._start_model_process(
                    project_file=project_file,
                    years_int=target_year,
                    run_mode="run",
                    requested_increment=1,
                    target_year=target_year,
                )
                return
            self._update_run_controls_state()
            return

        reply = self._session_command("RUN_ONE_YEAR", timeout_seconds=3600)
        if reply.get("status") != "OK":
            self.status_label.setText(f"Run one year failed: {reply.get('msg', 'unknown error')}")
            self.model_status_label.setText("Model status: run failed")
            self._set_model_progress_state("failed")
            self._append_workflow_log(f"RUN_ONE_YEAR failed: {reply}")
            self._update_run_controls_state()
            return

        year_value = int(reply.get("year", str(self._current_year + 1)))
        self._set_current_year_display(year_value)
        self._runtime_reported_year = year_value
        self.model_status_label.setText("Model status: completed one year")
        self._set_model_progress_state("success")
        self.status_label.setText(f"Model advanced to year {year_value}.")
        self._append_workflow_log(f"RUN_ONE_YEAR completed. Current year: {year_value}")
        self._autoload_project_data_on_success()
        self._update_run_controls_state()

    def _pause_or_continue_model(self):
        process = self.last_run_process
        if self._session_run_thread is not None and self._session_run_thread.is_alive():
            self._model_paused = not self._model_paused
            if self._model_paused:
                self.model_status_label.setText("Model status: paused")
                self._set_model_progress_state("paused")
                self._append_workflow_log("Pause requested. Execution will continue after current yearly step.")
            else:
                self.model_status_label.setText("Model status: running")
                self._set_model_progress_state("running")
                self._append_workflow_log("Continue requested.")
            self._update_run_controls_state()
            return

        if process is None or process.poll() is not None:
            self.status_label.setText("No running model process to pause/resume.")
            self._update_run_controls_state()
            return

        pid = process.pid
        try:
            if not self._model_paused:
                if os.name == "nt":
                    subprocess.run(
                        ["powershell", "-NoProfile", "-Command", f"Suspend-Process -Id {pid} -ErrorAction Stop"],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                else:
                    sigstop = getattr(signal, "SIGSTOP", None)
                    if sigstop is None:
                        raise RuntimeError("SIGSTOP is not available on this platform.")
                    os.kill(pid, sigstop)
                self._model_paused = True
                self.model_status_label.setText("Model status: paused")
                self._set_model_progress_state("paused")
                self._append_workflow_log(f"Model process paused (PID {pid}).")
            else:
                if os.name == "nt":
                    subprocess.run(
                        ["powershell", "-NoProfile", "-Command", f"Resume-Process -Id {pid} -ErrorAction Stop"],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                else:
                    sigcont = getattr(signal, "SIGCONT", None)
                    if sigcont is None:
                        raise RuntimeError("SIGCONT is not available on this platform.")
                    os.kill(pid, sigcont)
                self._model_paused = False
                self.model_status_label.setText("Model status: running")
                self._set_model_progress_state("running")
                self._append_workflow_log(f"Model process resumed (PID {pid}).")
        except Exception as exc:
            self.status_label.setText(f"Pause/Continue failed: {exc}")
            self._set_model_progress_state("failed")
            self._append_workflow_log(f"Pause/Continue operation failed for PID {pid}: {exc}")

        self._update_run_controls_state()

    def _stop_model(self):
        if self._session_run_thread is not None and self._session_run_thread.is_alive():
            self._session_stop_requested = True
            self.status_label.setText("Stop requested. Waiting for current year step to finish...")
            self.model_status_label.setText("Model status: stopping...")
            self._set_model_progress_state("running")
            self._append_workflow_log("Stop requested for session run loop.")
            self._update_run_controls_state()
            return

        process = self.last_run_process
        if process is None or process.poll() is not None:
            self.status_label.setText("No running model process to stop.")
            self._update_run_controls_state()
            return

        pid = process.pid
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

        if self._model_poll_timer is not None:
            self._model_poll_timer.stop()
        self._model_paused = False
        self._active_run_mode = ""
        self._runtime_reported_year = self._current_year
        self.last_run_process = None
        self.model_run_progress.setMinimum(0)
        self.model_run_progress.setMaximum(1)
        self.model_run_progress.setValue(0)
        self.model_status_label.setText("Model status: stopped")
        self._set_model_progress_state("idle")
        self.status_label.setText("Model stopped.")
        self._append_workflow_log(f"Model process stopped (PID {pid}).")
        self._update_run_controls_state()

    def _destroy_model_state(self):
        if self._is_model_running():
            self.status_label.setText("Stop the running model before destroy.")
            return

        if self._session_is_alive():
            reply = self._session_command("DESTROY", timeout_seconds=30)
            if reply.get("status") != "OK":
                self._append_workflow_log(f"Session destroy command failed: {reply}")
            self._stop_session()

        self._model_paused = False
        self._model_created = False
        self._active_run_mode = ""
        self._active_target_year = 0
        self._active_requested_years = 0
        self._runtime_reported_year = 0
        self._session_stop_requested = False
        self._session_last_error = ""
        self._session_run_requested_years = 0
        self._session_run_completed_years = 0
        self._session_run_finalize_pending = False
        self._session_run_thread = None
        self.last_run_process = None
        self.last_run_started_at = None
        self.model_run_progress.setMinimum(0)
        self.model_run_progress.setMaximum(1)
        self.model_run_progress.setValue(0)
        self.model_status_label.setText("Model status: destroyed/reset")
        self._set_model_progress_state("idle")
        self.status_label.setText("Model state destroyed/reset.")
        self._clear_managed_mode_layers()
        self._set_current_year_display(0)
        self._append_workflow_log("Destroy action: reset run state and cleared managed visualization layers.")
        self._update_run_controls_state()

    def _reload_model_state(self):
        if self._is_model_running():
            self.status_label.setText("Stop the running model before reload.")
            return
        if not self._model_created:
            self.status_label.setText("Create Model first before reload.")
            return

        self._append_workflow_log("Reload action: destroy and create model again.")
        self._destroy_model_state()
        self._create_model()

    def _resolve_or_install_executable(self) -> Optional[Path]:
        executable = self._resolve_executable_path()
        if executable is None:
            if os.name == "nt":
                self._append_workflow_log("Executable missing. Attempting runtime auto-install...")
                try:
                    repo = self.config.get_github_repo()
                    info = self.runtime_manager.install_latest_windows_runtime(repo=repo)
                    installed_exe = str(info.get("executable", ""))
                    if installed_exe:
                        self.config.set_string("workflow_executable_path", installed_exe)
                        self._append_workflow_log(f"Runtime installed. Executable: {installed_exe}")
                    executable = self._resolve_executable_path()
                except Exception as exc:
                    self._append_workflow_log(f"Runtime auto-install failed: {exc}")
            else:
                self._append_workflow_log(
                    "Executable missing. Auto-install is Windows-only; provide native iLANDc via system PATH, project/runtime folders, or Runtime tab -> Add Local Runtime...."
                )

        if executable is None:
            self.model_status_label.setText("Model status: missing executable")
            self._set_model_progress_state("failed")
            self.status_label.setText(
                "iLANDc runtime not found. Ensure 'ilandc' is available in PATH or configure a local runtime in Runtime tab."
            )
            self._append_workflow_log("Run blocked: executable not found after runtime auto-install attempt.")
            return None

        executable_str = str(executable)
        if "ilandc" not in Path(executable_str).name.lower():
            self.model_status_label.setText("Model status: invalid executable")
            self._set_model_progress_state("failed")
            self.status_label.setText("Selected executable is not iLANDc. Headless console engine is required.")
            self._append_workflow_log(
                f"Run blocked: '{executable_str}' appears to be GUI app. Please select iLANDc console executable."
            )
            return None

        if os.name != "nt" and Path(executable_str).suffix.lower() == ".exe":
            self.model_status_label.setText("Model status: invalid executable")
            self._set_model_progress_state("failed")
            self.status_label.setText("Windows runtime (.exe) cannot run on this OS. Select native iLANDc binary.")
            self._append_workflow_log(
                f"Run blocked: '{executable_str}' is a Windows .exe. Configure native iLANDc for this platform."
            )
            return None

        if os.name != "nt":
            try:
                mode = executable.stat().st_mode
                if not (mode & 0o111):
                    executable.chmod(mode | 0o111)
            except Exception:
                pass
        return executable

    def _runtime_env_for_executable(self, executable: Path) -> Dict[str, str]:
        env = dict(os.environ)
        path_parts: List[str] = []

        exe_dir = str(executable.parent)
        if exe_dir:
            path_parts.append(exe_dir)

        freeimage_candidates = [
            self.repo_root / "src" / "3rdparty" / "FreeImage",
            executable.parent / "3rdparty" / "FreeImage",
            executable.parent.parent / "3rdparty" / "FreeImage",
        ]
        for candidate in freeimage_candidates:
            if candidate.exists() and candidate.is_dir():
                path_parts.append(str(candidate))

        existing_path = env.get("PATH", "")
        if existing_path:
            path_parts.append(existing_path)
        env["PATH"] = os.pathsep.join(path_parts)
        return env

    def _start_model_process(
        self,
        project_file: str,
        years_int: int,
        run_mode: str,
        requested_increment: int,
        target_year: int,
    ):
        executable = self._resolve_or_install_executable()
        if executable is None:
            self._update_run_controls_state()
            return

        executable_str = str(executable)
        years = str(years_int)
        output_dir = self.output_dir_edit.text().strip()
        component_name = "all"
        if self.selected_module_payload:
            component_name = str(self.selected_module_payload.get("name", "all"))

        args = [project_file, years, "output.dynamic.enabled=true", f"component={component_name}"]
        if output_dir:
            args.append(f"system.path.output={output_dir}")

        command_preview = " ".join([f'"{executable_str}"'] + [shlex.quote(arg) for arg in args])
        try:
            if run_mode == "create":
                self.model_status_label.setText("Model status: creating...")
            else:
                self.model_status_label.setText("Model status: creating/running...")
            self._set_model_progress_state("running")
            self.model_run_progress.setMinimum(0)
            self.model_run_progress.setMaximum(0)
            project_dir = str(Path(project_file).resolve().parent)
            runtime_env = self._runtime_env_for_executable(executable)
            self.last_run_process = subprocess.Popen(
                [executable_str] + args,
                cwd=project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=runtime_env,
            )
            self.last_run_started_at = datetime.now()
            self._model_paused = False
            self._active_run_mode = run_mode
            self._active_requested_years = max(0, requested_increment)
            self._active_target_year = max(0, target_year)
            self._runtime_reported_year = self._current_year
            self.status_label.setText(f"iLAND started (PID {self.last_run_process.pid}). Command: {command_preview}")
            self._append_workflow_log(f"Started iLAND process PID {self.last_run_process.pid}")
            self._append_workflow_log(f"Execution mode: iLANDc headless (cwd={project_dir})")
            if run_mode == "create":
                self._append_workflow_log("Create Model: launching iLANDc with years=0 (build initial landscape only).")
            else:
                self._append_workflow_log(
                    f"Year semantics: current year {self._current_year}, requested +{requested_increment}, target year {target_year}."
                )
            self._append_workflow_log(f"Command: {command_preview}")
            self.config.set_string("workflow_last_project", project_file)
            self.config.set_string("workflow_output_dir", output_dir)
            self.config.set_string("workflow_last_years", str(max(1, requested_increment)))
            self.config.set_string("workflow_executable_path", executable_str)

            if self._model_poll_timer is None:
                self._model_poll_timer = QTimer(self)
                self._model_poll_timer.setInterval(1000)
                self._model_poll_timer.timeout.connect(self._poll_model_process)
            self._model_poll_timer.start()

            if self.last_run_process.stdout is not None:
                threading.Thread(
                    target=self._consume_model_output,
                    args=(self.last_run_process,),
                    daemon=True,
                ).start()
            self._update_run_controls_state()
        except Exception as exc:
            self.model_status_label.setText("Model status: failed to start")
            self._set_model_progress_state("failed")
            self.model_run_progress.setMinimum(0)
            self.model_run_progress.setMaximum(1)
            self.model_run_progress.setValue(0)
            self.status_label.setText(f"Could not start iLAND command: {exc}")
            self._append_workflow_log(f"Failed to start iLAND process: {exc}")
            if isinstance(exc, FileNotFoundError):
                self._append_workflow_log("Hint: open Runtime tab and install/activate a valid iLANDc runtime.")
            self._active_run_mode = ""
            self._active_requested_years = 0
            self._active_target_year = 0
            self._update_run_controls_state()

    def _consume_model_output(self, process: subprocess.Popen):
        try:
            if process.stdout is None:
                return
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                match = re.search(r"simulating year\s+(\d+)", line)
                if match:
                    reported = int(match.group(1)) + 1
                    # Prevent going backwards when rerunning from baseline to a higher target.
                    self._runtime_reported_year = max(self._current_year, reported)
        except Exception:
            pass

    def _create_model(self):
        if self._is_model_running():
            self.status_label.setText("A model run is already in progress.")
            return
        if self._model_created:
            self.status_label.setText("Model already created. Destroy to create again.")
            self._update_run_controls_state()
            return

        project_file = self.project_file_edit.text().strip()
        if not project_file:
            self.status_label.setText("Project XML is required before creating model.")
            self._update_run_controls_state()
            return
        if not Path(project_file).exists():
            self.status_label.setText("Project XML file does not exist.")
            self._update_run_controls_state()
            return

        if not self._ensure_qgis_project_context_for_xml(project_file):
            self._update_run_controls_state()
            return

        if not self._run_landscape_preflight_validation(project_file):
            self._update_run_controls_state()
            return

        effective_output = self._resolve_effective_output_dir(create=True)
        if effective_output is not None and not self.output_dir_edit.text().strip():
            self._append_workflow_log(f"Using project output directory: {effective_output}")

        if not self._ensure_session(project_file):
            if self._legacy_cli_executable:
                self._append_workflow_log(
                    "Create Model: using compatibility mode (legacy iLANDc without session support)."
                )
                self._start_model_process(
                    project_file=project_file,
                    years_int=0,
                    run_mode="create",
                    requested_increment=0,
                    target_year=max(0, self._current_year),
                )
                return
            self._update_run_controls_state()
            return

        self.model_status_label.setText("Model status: creating...")
        self._set_model_progress_state("running")
        reply = self._session_command("CREATE", timeout_seconds=3600)
        if reply.get("status") != "OK":
            self.model_status_label.setText("Model status: create failed")
            self._set_model_progress_state("failed")
            self.status_label.setText(f"Create Model failed: {reply.get('msg', 'unknown error')}")
            self._append_workflow_log(f"CREATE failed: {reply}")
            self._model_created = False
            self._update_run_controls_state()
            return

        self._model_created = True
        year_value = int(reply.get("year", "1"))
        self._set_current_year_display(max(1, year_value))
        self._runtime_reported_year = self._current_year
        self.model_status_label.setText("Model status: created")
        self._set_model_progress_state("success")
        self.status_label.setText("Model created. Ready to run.")
        self._append_workflow_log("Create Model completed successfully using persistent session backend.")
        self._update_run_controls_state()

    def _run_landscape_preflight_validation(self, project_file: str) -> bool:
        validator = ILandLandscapeValidator(project_file)
        report = validator.validate()

        self._append_workflow_log(f"Landscape pre-flight: {report.summary()}")
        if report.issues:
            for line in report.issues_text().splitlines()[:80]:
                self._append_workflow_log(line)

        if report.has_blockers:
            blocker_text = report.issues_text({"BLOCK"})
            QMessageBox.warning(
                self,
                "Missing mandatory initial landscape components",
                "Create Model is blocked because required iLAND landscape inputs are missing.\n\n"
                f"{blocker_text}",
            )
            self.status_label.setText("Create Model blocked by missing mandatory landscape components.")
            self.model_status_label.setText("Model status: validation blocked")
            self._set_model_progress_state("failed")
            return False

        if report.warning_count > 0:
            warning_text = report.issues_text({"WARN"})
            reply = QMessageBox.question(
                self,
                "Landscape validation warnings",
                "Landscape validation found warnings. You can continue, but results may be unreliable.\n\n"
                f"{warning_text}\n\nProceed with Create Model?",
                MSGBOX_YES | MSGBOX_NO,
                MSGBOX_NO,
            )
            if reply != MSGBOX_YES:
                self.status_label.setText("Create Model canceled after validation warnings.")
                return False

        return True

    def _find_qgis_project_files(self, folder: Path) -> List[Path]:
        if not folder.exists() or not folder.is_dir():
            return []
        files: List[Path] = []
        for pattern in ("*.qgz", "*.qgs"):
            files.extend(p for p in folder.glob(pattern) if p.is_file())
        return sorted(files)

    def _ensure_qgis_project_context_for_xml(self, project_file: str) -> bool:
        if self.iface is None or QgsProject is None:
            return True

        project = QgsProject.instance()
        current_project_path = str(project.fileName() or "").strip()
        if current_project_path:
            return True

        xml_path = Path(project_file)
        try:
            xml_dir = xml_path.resolve().parent
        except Exception:
            xml_dir = xml_path.parent

        existing_qgis_projects = self._find_qgis_project_files(xml_dir)
        if existing_qgis_projects:
            self._append_workflow_log(
                f"Found {len(existing_qgis_projects)} existing QGIS project file(s) in XML folder; continuing."
            )
            return True

        reply = QMessageBox.question(
            self,
            "Save QGIS project",
            "No QGIS project was found in the XML folder, and your current QGIS project is still untitled.\n\n"
            "Do you want to save a QGIS project in this folder before Create Model continues?",
            MSGBOX_YES | MSGBOX_NO,
            MSGBOX_YES,
        )
        if reply != MSGBOX_YES:
            self._append_workflow_log("Create Model: continuing without saving a QGIS project.")
            return True

        default_target = xml_dir / f"{xml_path.stem}.qgz"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save QGIS project as",
            str(default_target),
            "QGIS project (*.qgz *.qgs)",
        )
        if not file_path:
            self._append_workflow_log("Create Model: QGIS save prompt canceled; continuing.")
            return True

        chosen_path = Path(file_path)
        if chosen_path.suffix.lower() not in {".qgz", ".qgs"}:
            chosen_path = chosen_path.with_suffix(".qgz")

        if not project.write(str(chosen_path)):
            QMessageBox.warning(
                self,
                "QGIS project not saved",
                "Could not save the QGIS project file. Create Model will continue with the current untitled project.",
            )
            return True

        self._append_workflow_log(f"Saved QGIS project: {chosen_path}")
        return True

    def _selected_species_code(self) -> str:
        if not hasattr(self, "visual_species_combo"):
            return ""
        data = self.visual_species_combo.currentData()
        if data is None:
            return ""
        return str(data).strip()

    def _refresh_species_controls(self):
        if not hasattr(self, "visual_species_combo"):
            return
        project_file = self.project_file_edit.text().strip()
        if not project_file:
            self._known_species_codes = []
            self.visual_species_combo.clear()
            self.visual_species_combo.addItem("<all species>", "")
            self.visual_species_count_label.setText("0 species")
            self._rebuild_visual_value_combo([])
            return
        xml_path = Path(project_file) if project_file else None

        species_codes: List[str] = []
        if xml_path and xml_path.exists() and xml_path.is_file():
            species_codes = self._extract_species_codes_from_project(xml_path)
        self._known_species_codes = species_codes[:]

        selected = self._selected_species_code()
        self.visual_species_combo.clear()
        self.visual_species_combo.addItem("<all species>", "")
        for code in species_codes:
            self.visual_species_combo.addItem(code, code)

        if selected and selected in species_codes:
            idx = self.visual_species_combo.findData(selected)
            if idx >= 0:
                self.visual_species_combo.setCurrentIndex(idx)

        self.visual_species_count_label.setText(f"{len(species_codes)} species")
        self._rebuild_visual_value_combo(species_codes)
        if species_codes:
            preview = ", ".join(species_codes[:8])
            extra = " ..." if len(species_codes) > 8 else ""
            self._append_workflow_log(
                f"Species discovered ({len(species_codes)}): {preview}{extra}"
            )
        else:
            self._append_workflow_log("Species discovery: no explicit species list found in project XML.")

    def _extract_species_codes_from_project(self, xml_path: Path) -> List[str]:
        codes: List[str] = []
        seen: Set[str] = set()

        def add_tokens(text: str):
            for token in re.findall(r"\b[a-zA-Z]{4}\b", text):
                code = token.lower()
                if code not in seen:
                    seen.add(code)
                    codes.append(code)

        try:
            root = ET.parse(xml_path).getroot()
        except Exception as exc:
            self._append_workflow_log(f"Species discovery parse failed for {xml_path.name}: {exc}")
            return []

        for node in root.findall(".//enabledSpecies"):
            if node.text:
                add_tokens(node.text)

        for node in root.findall(".//externalSeedSpecies"):
            if node.text:
                add_tokens(node.text)

        for node in root.iter():
            tag = str(node.tag).lower()
            if tag.startswith("species_") and node.text:
                add_tokens(node.text)

        return codes

    def _rebuild_visual_value_combo(self, species_codes: List[str]):
        if not hasattr(self, "visual_value_combo"):
            return
        selected = self.visual_value_combo.currentText()
        self.visual_value_combo.blockSignals(True)
        self.visual_value_combo.clear()
        base = ["(value)", "tree.dbh", "tree.height", "ru.id", "species"]
        self.visual_value_combo.addItems(base)
        for code in species_codes:
            self.visual_value_combo.addItem(code)
        idx = self.visual_value_combo.findText(selected)
        self.visual_value_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.visual_value_combo.blockSignals(False)

    def _resolve_executable_path(self) -> Optional[Path]:
        def is_ilandc(path: Path) -> bool:
            name = path.name.lower()
            if os.name == "nt":
                return name == "ilandc.exe"
            if name == "ilandc":
                return True
            return name.startswith("ilandc") and not name.endswith(".exe")

        def first_valid(candidates: List[Path]) -> Optional[Path]:
            for candidate in candidates:
                if candidate.exists() and candidate.is_file() and is_ilandc(candidate):
                    return candidate
            return None

        def expand_candidate(path: Path) -> List[Path]:
            candidates: List[Path] = []
            if path.exists() and path.is_file():
                candidates.append(path)
                return candidates
            if not path.exists() or not path.is_dir():
                return candidates

            base_names = ["iLANDc.exe", "iLANDc", "ilandc"]
            for name in base_names:
                candidates.append(path / name)

            if path.suffix.lower() == ".app":
                macos_dir = path / "Contents" / "MacOS"
                for name in ["iLANDc", "ilandc"]:
                    candidates.append(macos_dir / name)

            for root_name in ["runtime", "runtimes", "bin", "dist", "release", "x64", "Contents", "MacOS"]:
                root = path / root_name
                if not root.exists() or not root.is_dir():
                    continue
                candidates.extend(list(root.rglob("iLANDc.exe")))
                candidates.extend(list(root.rglob("iLANDc")))
                candidates.extend(list(root.rglob("ilandc")))

            return candidates

        platform_key = "windows" if os.name == "nt" else ("macos" if sys.platform == "darwin" else "linux")

        # Prefer system/runtime-independent discovery first so global ilandc works without plugin runtime setup.
        for candidate_name in ["iLANDc.exe", "iLANDc", "ilandc"]:
            which_path = shutil.which(candidate_name)
            if which_path:
                which_candidate = Path(which_path)
                if is_ilandc(which_candidate):
                    return which_candidate

        saved = self.config.get_string("workflow_executable_path", "")
        if saved:
            saved_path = Path(saved)
            found = first_valid(expand_candidate(saved_path))
            if found is not None:
                return found

            # Allow command-style saved values like "ilandc" that resolve via PATH.
            if os.sep not in saved and "/" not in saved and "\\" not in saved:
                which_path = shutil.which(saved)
                if which_path:
                    which_candidate = Path(which_path)
                    if is_ilandc(which_candidate):
                        return which_candidate

        bundled_candidates = [
            self.plugin_dir / "iLANDc.exe",
            self.plugin_dir / "iLANDc",
            self.plugin_dir / "ilandc",
            self.plugin_dir / "runtime" / "iLANDc.exe",
            self.plugin_dir / "runtime" / "iLANDc",
            self.plugin_dir / "runtime" / "ilandc",
            self.plugin_dir / "runtime" / platform_key / "iLANDc.exe",
            self.plugin_dir / "runtime" / platform_key / "iLANDc",
            self.plugin_dir / "runtime" / platform_key / "ilandc",
            self.plugin_dir / "runtimes" / "iLANDc.exe",
            self.plugin_dir / "runtimes" / "iLANDc",
            self.plugin_dir / "runtimes" / "ilandc",
            self.plugin_dir / "runtimes" / platform_key / "iLANDc.exe",
            self.plugin_dir / "runtimes" / platform_key / "iLANDc",
            self.plugin_dir / "runtimes" / platform_key / "ilandc",
            self.plugin_dir / "bin" / "iLANDc.exe",
            self.plugin_dir / "bin" / "iLANDc",
            self.plugin_dir / "bin" / "ilandc",
        ]
        found = first_valid(bundled_candidates)
        if found is not None:
            return found

        for root_name in ["runtime", "runtimes", "bin", "dist", "release", "x64"]:
            root = self.plugin_dir / root_name
            if not root.exists() or not root.is_dir():
                continue
            hits = list(root.rglob("iLANDc.exe")) + list(root.rglob("iLANDc")) + list(root.rglob("ilandc"))
            found = first_valid(hits)
            if found is not None:
                return found

        project_file = self.project_file_edit.text().strip() if hasattr(self, "project_file_edit") else ""
        if project_file:
            project_path = Path(project_file).expanduser()
            if project_path.exists() and project_path.is_file():
                project_dir = project_path.resolve().parent
                project_candidates = [
                    project_dir / "iLANDc.exe",
                    project_dir / "iLANDc",
                    project_dir / "ilandc",
                    project_dir / "runtime" / platform_key / "iLANDc",
                    project_dir / "runtime" / platform_key / "ilandc",
                    project_dir / "runtime" / "iLANDc",
                    project_dir / "runtime" / "ilandc",
                    project_dir / "runtimes" / platform_key / "iLANDc",
                    project_dir / "runtimes" / platform_key / "ilandc",
                    project_dir / "runtimes" / "iLANDc",
                    project_dir / "runtimes" / "ilandc",
                    project_dir / "bin" / "iLANDc",
                    project_dir / "bin" / "ilandc",
                    project_dir / "build" / "iLANDc",
                    project_dir / "build" / "ilandc",
                ]
                found = first_valid(project_candidates)
                if found is not None:
                    return found

                for root_name in ["runtime", "runtimes", "build", "bin", "dist", "release", "x64"]:
                    root = project_dir / root_name
                    if not root.exists() or not root.is_dir():
                        continue
                    hits = list(root.rglob("iLANDc.exe")) + list(root.rglob("iLANDc")) + list(root.rglob("ilandc"))
                    found = first_valid(hits)
                    if found is not None:
                        return found

        common_candidates = [
            self.repo_root / "iLANDc.exe",
            self.repo_root / "build" / "iLANDc.exe",
            self.repo_root / "bin" / "iLANDc.exe",
            self.repo_root / "iLANDc",
            self.repo_root / "build" / "iLANDc",
            self.repo_root / "bin" / "iLANDc",
        ]
        found = first_valid(common_candidates)
        if found is not None:
            return found

        from_runtime = self.runtime_manager.get_active_executable()
        if from_runtime is not None and from_runtime.exists() and is_ilandc(from_runtime):
            return from_runtime

        if sys.platform == "darwin":
            mac_default_candidates: List[Path] = [
                Path("/Applications/iLand.app/Contents/MacOS/iLANDc"),
                Path("/Applications/iLand.app/Contents/MacOS/ilandc"),
                Path("/Applications/iland.app/Contents/MacOS/iLANDc"),
                Path("/Applications/iland.app/Contents/MacOS/ilandc"),
                Path.home() / "Applications" / "iLand.app" / "Contents" / "MacOS" / "iLANDc",
                Path.home() / "Applications" / "iLand.app" / "Contents" / "MacOS" / "ilandc",
            ]
            applications_dir = Path("/Applications")
            if applications_dir.exists() and applications_dir.is_dir():
                for app in applications_dir.glob("*.app"):
                    mac_default_candidates.append(app / "Contents" / "MacOS" / "iLANDc")
                    mac_default_candidates.append(app / "Contents" / "MacOS" / "ilandc")
            found = first_valid(mac_default_candidates)
            if found is not None:
                return found

        if os.name != "nt" and sys.platform != "darwin":
            linux_default_candidates = [
                Path("/usr/local/bin/iLANDc"),
                Path("/usr/local/bin/ilandc"),
                Path("/usr/bin/iLANDc"),
                Path("/usr/bin/ilandc"),
                Path("/opt/iland/iLANDc"),
                Path("/opt/iland/ilandc"),
                Path("/opt/iLand/iLANDc"),
                Path("/opt/iLand/ilandc"),
            ]
            found = first_valid(linux_default_candidates)
            if found is not None:
                return found

        for root_name in ["build", "bin", "dist", "release", "x64"]:
            root = self.repo_root / root_name
            if not root.exists():
                continue
            hits = list(root.rglob("iLANDc.exe")) + list(root.rglob("iLANDc")) + list(root.rglob("ilandc"))
            found = first_valid(hits)
            if found is not None:
                return found

        return None

    def _on_add_local_runtime(self):
        if os.name == "nt":
            file_filter = "Executables (iLANDc.exe);;All files (*)"
        else:
            file_filter = "Executables (iLANDc ilandc);;All files (*)"

        start_dir = str(self._default_user_workspace_dir())
        current = self.config.get_string("workflow_executable_path", "").strip()
        if current:
            current_path = Path(current).expanduser()
            if current_path.exists():
                start_dir = str(current_path.parent if current_path.is_file() else current_path)

        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select native iLANDc executable",
            start_dir,
            file_filter,
        )
        if not selected:
            return

        executable = Path(selected).expanduser()
        if not executable.exists() or not executable.is_file():
            self.runtime_status_label.setText(f"Selected executable does not exist: {selected}")
            return

        name_lower = executable.name.lower()
        if "ilandc" not in name_lower:
            self.runtime_status_label.setText("Selected file is not iLANDc. Choose headless console executable.")
            return

        if os.name != "nt" and executable.suffix.lower() == ".exe":
            self.runtime_status_label.setText("Windows .exe cannot run on this OS. Choose native iLANDc binary.")
            return

        if os.name != "nt":
            try:
                mode = executable.stat().st_mode
                if not (mode & 0o111):
                    executable.chmod(mode | 0o111)
            except OSError:
                pass

        tag = f"local-{executable.parent.name}-{executable.name}"
        try:
            info = self.runtime_manager.register_local_runtime(executable=executable, tag=tag, activate=True)
            self.config.set_string("workflow_executable_path", str(executable.resolve()))
            self._refresh_runtime_local_list()
            self.runtime_status_label.setText(
                f"Registered local runtime {info.get('tag', '?')} ({Path(info.get('executable', '')).name})."
            )
        except Exception as exc:
            self.runtime_status_label.setText(f"Could not register local runtime: {exc}")

    def _on_log_filter_execute(self):
        search_for = self.log_filter_edit.text().strip()
        if not search_for:
            return

        if not hasattr(self, "_workflow_log_full_backup"):
            self._workflow_log_full_backup = ""

        if not self._workflow_log_full_backup:
            self._workflow_log_full_backup = self.workflow_log_output.toPlainText()

        debug_lines = self._workflow_log_full_backup.splitlines()
        lines: List[str] = []
        for idx, line in enumerate(debug_lines, start=1):
            if search_for.lower() in line.lower():
                lines.append(f"{idx}: {line}")

        if lines:
            self.workflow_log_output.setPlainText("\n".join(lines))
        else:
            self.workflow_log_output.setPlainText("Search term not found!")
        self.log_filter_clear_button.setEnabled(True)

    def _on_log_filter_clear(self):
        backup = getattr(self, "_workflow_log_full_backup", "")
        if not backup:
            return
        self.workflow_log_output.setPlainText(backup)
        self._workflow_log_full_backup = ""
        self.log_filter_clear_button.setEnabled(False)

    def _on_log_clear_text(self):
        self.workflow_log_output.clear()
        self._workflow_log_full_backup = ""
        self.log_filter_clear_button.setEnabled(False)

    def _on_log_copy(self):
        QGuiApplication.clipboard().setText(self.workflow_log_output.toPlainText())
        self.status_label.setText("Log output copied to clipboard.")

    def _append_workflow_log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.workflow_log_output.appendPlainText(f"[{timestamp}] {message}")

    def _on_check_latest_release(self):
        repo = self.runtime_repo_edit.text().strip() or "edfm-tum/iland-model"
        self.config.set_github_repo(repo)
        try:
            payload = self.runtime_manager.fetch_latest_release(repo=repo)
            self.latest_release_payload = payload
            tag = str(payload.get("tag_name", ""))
            assets = list(payload.get("assets", []))
            self.runtime_assets_list.clear()
            for asset in assets:
                item = QListWidgetItem(str(asset.get("name", "unnamed")))
                item.setData(USER_ROLE, asset)
                self.runtime_assets_list.addItem(item)
            self.runtime_status_label.setText(f"Latest release: {tag} ({len(assets)} assets).")
        except Exception as exc:
            self.runtime_status_label.setText(f"Could not fetch latest release: {exc}")

    def _on_install_latest_runtime(self):
        if os.name != "nt":
            self.runtime_status_label.setText(
                "Automatic runtime install is currently supported on Windows only. "
                "Select a native iLANDc executable manually."
            )
            return
        repo = self.runtime_repo_edit.text().strip() or "edfm-tum/iland-model"
        self.config.set_github_repo(repo)
        try:
            info = self.runtime_manager.install_latest_windows_runtime(repo=repo)
            self._refresh_runtime_local_list()
            exe = info.get("executable", "not found")
            self.runtime_status_label.setText(
                f"Installed runtime {info.get('tag', '?')} from {info.get('asset_name', '?')}. Executable: {exe}"
            )
        except Exception as exc:
            self.runtime_status_label.setText(f"Runtime install failed: {exc}")

    def _refresh_runtime_local_list(self):
        active_tag = self.runtime_manager.get_active_runtime_tag()
        self.runtime_local_list.clear()
        for runtime in self.runtime_manager.list_runtimes():
            tag = runtime.get("tag", "unknown")
            exe = runtime.get("executable", "")
            prefix = "* " if tag == active_tag else ""
            item = QListWidgetItem(f"{prefix}{tag} | {Path(exe).name if exe else 'no exe'}")
            item.setData(USER_ROLE, runtime)
            self.runtime_local_list.addItem(item)
        if not self.runtime_manager.list_runtimes():
            self.runtime_status_label.setText("No local runtimes installed yet.")
        self._refresh_runtime_compatibility_panel()

    def _on_activate_runtime(self):
        selected = self.runtime_local_list.selectedItems()
        if not selected:
            self.runtime_status_label.setText("Select an installed runtime to activate.")
            return
        runtime = selected[0].data(USER_ROLE) or {}
        tag = str(runtime.get("tag", ""))
        if not tag:
            self.runtime_status_label.setText("Selected runtime has no valid tag.")
            return
        if self.runtime_manager.set_active_runtime(tag):
            self._refresh_runtime_local_list()
            self.runtime_status_label.setText(f"Activated runtime: {tag}")
        else:
            self.runtime_status_label.setText(f"Could not activate runtime: {tag}")

    def _normalize_module_key(self, raw_name: str) -> str:
        return "".join(ch for ch in raw_name.lower() if ch.isalnum())

    def _module_display_name(self, module_key: str, source_display_names: Dict[str, str]) -> str:
        if module_key in source_display_names:
            return source_display_names[module_key]
        if module_key == "barkbeetle":
            return "BarkBeetle"
        return module_key[:1].upper() + module_key[1:] if module_key else "Unknown"

    def _is_truthy_text(self, raw_text: str) -> bool:
        return raw_text.strip().lower() in {"1", "true", "yes", "on"}

    def _enabled_modules_from_project_xml(self) -> Set[str]:
        project_path_raw = self.project_file_edit.text().strip()
        if not project_path_raw:
            return set()

        xml_path = Path(project_path_raw)
        if not xml_path.exists() or not xml_path.is_file():
            return set()

        try:
            root = ET.parse(xml_path).getroot()
        except Exception:
            return set()

        enabled_modules: Set[str] = set()
        parent_map = {child: parent for parent in root.iter() for child in parent}

        for node in root.iter():
            tag = str(node.tag)
            value = (node.text or "").strip()
            if not value or not self._is_truthy_text(value):
                continue

            lower_tag = tag.lower()
            if lower_tag.startswith("modules.") and lower_tag.endswith(".enabled"):
                module_name = tag[len("modules.") : -len(".enabled")]
                module_key = self._normalize_module_key(module_name)
                if module_key:
                    enabled_modules.add(module_key)
                continue

            if lower_tag == "enabled":
                parent = parent_map.get(node)
                if parent is None:
                    continue
                grand_parent = parent_map.get(parent)
                if grand_parent is None:
                    continue
                if str(grand_parent.tag).lower() != "modules":
                    continue

                module_key = self._normalize_module_key(str(parent.tag))
                if module_key:
                    enabled_modules.add(module_key)

        return enabled_modules

    def _detect_runtime_modules(self, executable: Path, expected_modules: Set[str]) -> Set[str]:
        cache_token = ""
        try:
            stat = executable.stat()
            cache_token = f"{executable.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
        except Exception:
            cache_token = str(executable)

        if cache_token and cache_token == self._runtime_module_cache_key:
            return set(self._runtime_module_cache)

        detected: Set[str] = set()
        candidate_modules = set(expected_modules)
        candidate_modules.update({"fire", "wind", "barkbeetle", "bite"})

        try:
            binary_data = executable.read_bytes()
            for match in re.findall(rb"modules\.([a-z0-9_]+)\.enabled", binary_data, flags=re.IGNORECASE):
                module_key = self._normalize_module_key(match.decode("ascii", "ignore"))
                if module_key:
                    detected.add(module_key)
        except Exception:
            pass

        try:
            for artifact in executable.parent.iterdir():
                if not artifact.is_file():
                    continue
                if artifact.suffix.lower() not in {".dll", ".so", ".dylib", ".exe", ".lib", ".a"}:
                    continue
                artifact_name = artifact.name.lower()
                for module_key in candidate_modules:
                    if module_key and module_key in artifact_name:
                        detected.add(module_key)
        except Exception:
            pass

        self._runtime_module_cache_key = cache_token
        self._runtime_module_cache = set(detected)
        return detected

    def _refresh_runtime_compatibility_panel(self):
        if not hasattr(self, "runtime_compat_tree"):
            return

        source_display_names: Dict[str, str] = {}
        source_modules: Set[str] = set()
        for raw_name in self.ui_catalog.discover_disturbance_modules():
            module_key = self._normalize_module_key(raw_name)
            if not module_key:
                continue
            source_modules.add(module_key)
            source_display_names.setdefault(module_key, raw_name)

        xml_enabled_modules = self._enabled_modules_from_project_xml()

        runtime_executable = self.runtime_manager.get_active_executable()
        runtime_modules: Set[str] = set()
        if runtime_executable is not None and runtime_executable.exists() and runtime_executable.is_file():
            runtime_modules = self._detect_runtime_modules(
                runtime_executable,
                source_modules.union(xml_enabled_modules),
            )

        all_modules = sorted(source_modules.union(xml_enabled_modules).union(runtime_modules))

        self.runtime_compat_tree.clear()
        if not all_modules:
            self.runtime_compat_tree.addTopLevelItem(
                QTreeWidgetItem([
                    "(no modules detected)",
                    "No",
                    "No",
                    "No active runtime" if runtime_executable is None else "No",
                    "Select a project XML and activate a runtime to compare modules",
                ])
            )

        for module_key in all_modules:
            in_source = module_key in source_modules
            in_xml = module_key in xml_enabled_modules
            in_runtime = module_key in runtime_modules

            if runtime_executable is None:
                runtime_state = "No active runtime"
            else:
                runtime_state = "Yes" if in_runtime else "No"

            if in_xml and runtime_executable is not None and not in_runtime:
                status = "Enabled in XML but not detected in runtime"
            elif in_xml and runtime_executable is None:
                status = "Enabled in XML (activate a runtime to verify)"
            elif in_runtime and not in_source:
                status = "Runtime-only module"
            elif in_source and not in_xml:
                status = "Available in source, not enabled in XML"
            else:
                status = "Aligned"

            item = QTreeWidgetItem(
                [
                    self._module_display_name(module_key, source_display_names),
                    "Yes" if in_source else "No",
                    "Yes" if in_xml else "No",
                    runtime_state,
                    status,
                ]
            )
            self.runtime_compat_tree.addTopLevelItem(item)

        runtime_name = runtime_executable.name if runtime_executable is not None else "none"
        summary = (
            f"Source plugins: {len(source_modules)} | "
            f"XML enabled: {len(xml_enabled_modules)} | "
            f"Runtime detected: {len(runtime_modules)} | "
            f"Active runtime: {runtime_name}"
        )
        if runtime_executable is not None and not runtime_modules:
            summary += " (module detection may be limited for this runtime build)."
        self.runtime_compat_summary.setText(summary)

    def _on_select_all_debug_data(self):
        all_selected = all(box.isChecked() for box in self.debug_action_boxes.values())
        target = not all_selected
        for box in self.debug_action_boxes.values():
            box.setChecked(target)
        self._append_debug_log("Selected all debug data types." if target else "Cleared all debug data types.")
        self._persist_debug_state()

    def _on_clear_debug_output(self):
        self.debug_output_log.clear()
        self._append_debug_log("Debug output cleared.")

    def _on_debug_item_toggled(self):
        self._persist_debug_state()

    def _copy_debug_command_args(self):
        mapping = {
            "Tree NPP": "debug.tree_npp=true",
            "Tree Partition": "debug.tree_partition=true",
            "Tree Growth": "debug.tree_growth=true",
            "Water Output": "debug.water_output=true",
            "Daily responses Output": "debug.daily_responses=true",
            "Establishment": "debug.establishment=true",
            "Sapling growth": "debug.sapling_growth=true",
            "Carbon Cycle": "debug.carbon_cycle=true",
            "Performance": "debug.performance=true",
            "Dynamic Output": "output.dynamic.enabled=true",
        }
        selected = [name for name, box in self.debug_action_boxes.items() if box.isChecked()]
        if not selected:
            self.status_label.setText("No debug data types selected.")
            self._append_debug_log("No debug args copied because no debug item is selected.")
            return

        args = [mapping[name] for name in selected if name in mapping]
        arg_line = " ".join(args)
        QGuiApplication.clipboard().setText(arg_line)
        self.status_label.setText("Debug args copied to clipboard.")
        self._append_debug_log(f"Copied debug args: {arg_line}")

    def _append_debug_log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.debug_output_log.appendPlainText(f"[{timestamp}] {message}")

    def _persist_debug_state(self):
        payload = {name: box.isChecked() for name, box in self.debug_action_boxes.items()}
        self.config.set_value("debug_data_selection", payload)

    def _on_view_repaint(self):
        if self.iface is None:
            self.view_status_label.setText("Repaint requested (iface not available in this context).")
            return
        try:
            self.iface.mapCanvas().refresh()
            self.view_status_label.setText("Map repaint requested.")
        except Exception as exc:
            self.view_status_label.setText(f"Could not repaint map: {exc}")

    def _on_view_full_extent(self):
        if self.iface is None:
            self.view_status_label.setText("Show full extent requested (iface not available in this context).")
            return
        try:
            self.iface.mapCanvas().zoomToFullExtent()
            self.iface.mapCanvas().refresh()
            self.view_status_label.setText("Map zoomed to full extent.")
        except Exception as exc:
            self.view_status_label.setText(f"Could not zoom to full extent: {exc}")

    def _on_misc_copy_image(self):
        try:
            if self.iface is not None:
                pixmap = self.iface.mapCanvas().grab()
            else:
                pixmap = self.grab()
            QGuiApplication.clipboard().setPixmap(pixmap)
            self._append_misc_log("Copied current view image to clipboard.")
        except Exception as exc:
            self._append_misc_log(f"Could not copy image: {exc}")

    def _on_misc_log_level_changed(self):
        selected = self._selected_misc_log_level()
        if not selected:
            return
        self.config.set_string("misc_log_level", selected)
        self._append_misc_log(f"Log level set to: {selected}")

    def _selected_misc_log_level(self) -> str:
        for name, button in self.misc_log_level_buttons.items():
            if button.isChecked():
                return name
        return ""

    def _on_misc_output_table_description(self):
        output_dir = self.repo_root / "src" / "output"
        if not output_dir.exists():
            self._append_misc_log("Output table description unavailable: src/output not found.")
            return

        entries: List[str] = []
        for cpp_file in sorted(output_dir.glob("*.cpp")):
            stem = cpp_file.stem
            h_file = output_dir / f"{stem}.h"
            entries.append(f"- {stem}: cpp={cpp_file.name}, header={'yes' if h_file.exists() else 'no'}")

        text = "Output table description\n\n" + "\n".join(entries)
        QGuiApplication.clipboard().setText(text)
        self._append_misc_log("Output table description copied to clipboard.")

    def _on_misc_log_timers(self):
        now = datetime.now()
        started = self.last_run_started_at
        if started is None:
            self._append_misc_log("No simulation run timestamp available yet.")
            return
        elapsed = now - started
        self._append_misc_log(f"Elapsed since last run start: {elapsed}.")

    def _on_misc_execute_test(self):
        checks = [
            ("Repo root exists", self.repo_root.exists()),
            ("src folder exists", (self.repo_root / "src").exists()),
            ("mainwindow.ui exists", (self.repo_root / "src" / "iland" / "mainwindow.ui").exists()),
            ("Metadata exists", self._settings_metadata_file().exists()),
        ]
        passed = [name for name, ok in checks if ok]
        failed = [name for name, ok in checks if not ok]
        self._append_misc_log(f"Execute test: {len(passed)} passed, {len(failed)} failed.")
        for name in passed:
            self._append_misc_log(f"PASS: {name}")
        for name in failed:
            self._append_misc_log(f"FAIL: {name}")

    def _on_misc_expression_plotter(self):
        expr = self.misc_expression_edit.text().strip()
        if not expr:
            self._append_misc_log("Expression is empty.")
            return
        expr_py = expr.replace("^", "**")
        points: List[str] = []
        try:
            for x in range(0, 11):
                y = eval(expr_py, {"__builtins__": {}}, {"x": x})
                points.append(f"{x},{y}")
        except Exception as exc:
            self._append_misc_log(f"Expression evaluation failed: {exc}")
            return

        result = "x,y\n" + "\n".join(points)
        QGuiApplication.clipboard().setText(result)
        self._append_misc_log(f"Expression plotter evaluated '{expr}'. Result CSV copied to clipboard.")

    def _on_misc_update_xml(self):
        if not self._ensure_settings_xml_loaded(force_reload=True, silent=True):
            self._append_misc_log("Update XML file skipped: no valid project XML path provided.")
            return
        if self._settings_xml_tree is None or self._settings_xml_path is None:
            self._append_misc_log("Update XML file skipped: XML tree is not available.")
            return

        if not self.settings_field_meta:
            self._load_settings_metadata()
        if not self.settings_field_meta:
            self._append_misc_log("Update XML file skipped: metadata file not found or empty.")
            return

        created = 0
        root = self._settings_xml_tree.getroot()
        for key in self.settings_field_meta.keys():
            exists = root.find("./" + "/".join(key.split("."))) is not None
            self._ensure_xml_node(root, key)
            if not exists:
                created += 1

        try:
            self._settings_xml_tree.write(self._settings_xml_path, encoding="utf-8", xml_declaration=True)
            self._append_misc_log(
                f"Update XML complete. Added {created} missing keys to {self._settings_xml_path.name}."
            )
        except Exception as exc:
            self._append_misc_log(f"Could not write updated XML: {exc}")

    def _append_misc_log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.misc_log_output.appendPlainText(f"[{timestamp}] {message}")

    def _run_model(self):
        if self._is_model_running():
            self.status_label.setText("A model run is already in progress.")
            self._update_run_controls_state()
            return
        if not self._model_created:
            self.status_label.setText("Create Model first, then run model.")
            self._update_run_controls_state()
            return

        project_file = self.project_file_edit.text().strip()
        if not project_file:
            self.status_label.setText("Project XML is required before running iLAND.")
            self._update_run_controls_state()
            return

        ask_default = max(1, int(self.config.get_string("workflow_last_years", str(self._last_run_year_request))))
        prompt = f"How many years to run?\nCurrent year: {max(1, self._current_year)}."
        years_to_run, ok = QInputDialog.getInt(
            self,
            "Run Model",
            prompt,
            ask_default,
            1,
            100000,
            1,
        )
        if not ok:
            return

        if not self._ensure_session(project_file):
            if self._legacy_cli_executable:
                target_year = max(1, self._current_year) + years_to_run
                self._append_workflow_log(
                    f"Run Model: compatibility mode active, executing one-shot run to year {target_year}."
                )
                self._last_run_year_request = years_to_run
                self._start_model_process(
                    project_file=project_file,
                    years_int=target_year,
                    run_mode="run",
                    requested_increment=years_to_run,
                    target_year=target_year,
                )
                return
            self._update_run_controls_state()
            return

        self._last_run_year_request = years_to_run
        self._active_run_mode = "run"
        self._active_requested_years = years_to_run
        self._active_target_year = max(1, self._current_year) + years_to_run
        self._session_stop_requested = False
        self._session_last_error = ""
        self._session_run_requested_years = years_to_run
        self._session_run_completed_years = 0
        self._session_run_finalize_pending = False
        self._model_paused = False
        self.last_run_started_at = datetime.now()
        self.model_status_label.setText(
            f"Model status: running | year {max(1, self._current_year)} -> {self._active_target_year}"
        )
        self._set_model_progress_state("running")
        self.status_label.setText(f"Running model for {years_to_run} year(s)...")
        self._append_workflow_log(
            f"RUN_YEARS requested: +{years_to_run} years from year {max(1, self._current_year)} to {self._active_target_year}."
        )

        self._session_run_thread = threading.Thread(
            target=self._run_session_year_loop,
            args=(years_to_run,),
            daemon=True,
        )
        self._session_run_thread.start()

        if self._model_poll_timer is None:
            self._model_poll_timer = QTimer(self)
            self._model_poll_timer.setInterval(250)
            self._model_poll_timer.timeout.connect(self._poll_model_process)
        self._model_poll_timer.start()
        self._update_run_controls_state()

    def _run_session_year_loop(self, years_to_run: int):
        for _ in range(max(0, int(years_to_run))):
            while self._model_paused and (not self._session_stop_requested):
                time.sleep(0.2)

            if self._session_stop_requested:
                break

            reply = self._session_command("RUN_ONE_YEAR", timeout_seconds=3600)
            if reply.get("status") != "OK":
                self._session_last_error = reply.get("msg", "unknown error")
                break

            try:
                year_value = int(reply.get("year", str(self._current_year + 1)))
            except Exception:
                year_value = self._current_year + 1

            self._runtime_reported_year = max(self._runtime_reported_year, year_value)
            self._current_year = year_value
            self._session_run_completed_years += 1

        self._session_run_finalize_pending = True

    def _poll_model_process(self):
        if self._session_run_thread is not None:
            if self._session_run_thread.is_alive():
                self.model_run_progress.setMinimum(0)
                self.model_run_progress.setMaximum(max(1, self._session_run_requested_years))
                self.model_run_progress.setValue(min(self._session_run_completed_years, self._session_run_requested_years))

                if self.last_run_started_at:
                    elapsed = datetime.now() - self.last_run_started_at
                    seconds = int(elapsed.total_seconds())
                else:
                    seconds = 0

                shown_year = max(self._current_year, self._runtime_reported_year)
                if self._model_paused:
                    self.model_status_label.setText(f"Model status: paused ({seconds}s) | year {shown_year}")
                    self._set_model_progress_state("paused")
                else:
                    self.model_status_label.setText(
                        f"Model status: running ({seconds}s) | year {shown_year} -> {self._active_target_year}"
                    )
                    self._set_model_progress_state("running")
                return

            if self._session_run_finalize_pending:
                self._session_run_finalize_pending = False
                self._session_run_thread = None
                self.model_run_progress.setMinimum(0)
                self.model_run_progress.setMaximum(1)
                self.model_run_progress.setValue(1)

                if self._session_last_error:
                    self.model_status_label.setText("Model status: run failed")
                    self._set_model_progress_state("failed")
                    self.status_label.setText(f"Run Model failed: {self._session_last_error}")
                    self._append_workflow_log(f"RUN_YEARS failed: {self._session_last_error}")
                elif self._session_stop_requested:
                    self.model_status_label.setText("Model status: stopped")
                    self._set_model_progress_state("idle")
                    self.status_label.setText("Model stopped.")
                    self._append_workflow_log(
                        f"Run stopped by user after {self._session_run_completed_years}/{self._session_run_requested_years} year steps."
                    )
                else:
                    self._model_created = True
                    self._set_current_year_display(max(self._current_year, self._runtime_reported_year))
                    self.model_status_label.setText("Model status: completed")
                    self._set_model_progress_state("success")
                    self.status_label.setText(f"Model completed through year {self._current_year}.")
                    self._append_workflow_log(f"RUN_YEARS completed. Current year: {self._current_year}")
                    self._autoload_project_data_on_success()

                self._model_paused = False
                self._session_stop_requested = False
                self._session_last_error = ""
                self._session_run_requested_years = 0
                self._session_run_completed_years = 0
                self._active_run_mode = ""
                self._active_requested_years = 0
                self._active_target_year = 0
                self._runtime_reported_year = self._current_year
                self._update_run_controls_state()
                return

        if self.last_run_process is None:
            if self._model_poll_timer is not None:
                self._model_poll_timer.stop()
            return

        code = self.last_run_process.poll()
        if code is None:
            if self.last_run_started_at:
                elapsed = datetime.now() - self.last_run_started_at
                seconds = int(elapsed.total_seconds())
                if self._model_paused:
                    self.model_status_label.setText(f"Model status: paused ({seconds}s)")
                    self._set_model_progress_state("paused")
                else:
                    shown_year = max(self._current_year, self._runtime_reported_year)
                    if self._active_target_year > 0:
                        self.model_status_label.setText(
                            f"Model status: running ({seconds}s) | year {shown_year} -> {self._active_target_year}"
                        )
                    else:
                        self.model_status_label.setText(f"Model status: running ({seconds}s) | year {shown_year}")
                    self._set_model_progress_state("running")
            return

        self.model_run_progress.setMinimum(0)
        self.model_run_progress.setMaximum(1)
        self.model_run_progress.setValue(1)
        if code == 0:
            if self._active_run_mode == "create":
                self._model_created = True
                self._set_current_year_display(1)
                self.model_status_label.setText("Model status: created")
                self._set_model_progress_state("success")
                self.status_label.setText("Model created. Ready to run.")
                self._append_workflow_log("Create Model completed successfully.")
            else:
                self._model_created = True
                if self._active_target_year > 0:
                    self._set_current_year_display(self._active_target_year)
                self.model_status_label.setText("Model status: completed")
                self._set_model_progress_state("success")
                self._append_workflow_log("Model process completed successfully.")
                self._autoload_project_data_on_success()
        else:
            self.model_status_label.setText(f"Model status: exited with code {code}")
            self._set_model_progress_state("failed")
            self._append_workflow_log(f"Model process exited with code {code}.")
            if self._active_run_mode == "create":
                self._model_created = False
        if self._model_poll_timer is not None:
            self._model_poll_timer.stop()
        self._model_paused = False
        self._active_run_mode = ""
        self._active_requested_years = 0
        self._active_target_year = 0
        self._runtime_reported_year = self._current_year
        self.last_run_process = None
        self._update_run_controls_state()

    def _open_output_folder(self):
        path = self._resolve_effective_output_dir(create=True)
        if path is None:
            self.status_label.setText("Output directory is not available.")
            return
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path)])
            self.status_label.setText(f"Opened output folder: {path}")
        except Exception as exc:
            self.status_label.setText(f"Could not open output folder: {exc}")

    def _load_latest_output_layer(self):
        if self.iface is None or QgsProject is None or QgsRasterLayer is None:
            self.status_label.setText("QGIS layer APIs are not available in this runtime.")
            self._append_workflow_log("Load layer skipped: QGIS APIs unavailable.")
            return

        resolved = self._resolve_effective_output_dir(create=False)
        if resolved is None:
            self.status_label.setText("Output directory is not available.")
            return
        output_dir = resolved
        if not output_dir.exists():
            self.status_label.setText("Output directory does not exist.")
            self._append_workflow_log(f"Load layer failed: output directory not found: {output_dir}")
            return

        candidate_files: List[Path] = []
        for pattern in ("*.tif", "*.tiff", "*.asc"):
            candidate_files.extend(output_dir.rglob(pattern))

        if not candidate_files:
            self.status_label.setText("No raster outputs found (.tif/.tiff/.asc).")
            self._append_workflow_log("Load layer failed: no raster outputs found.")
            return

        latest = max(candidate_files, key=lambda p: p.stat().st_mtime)
        layer_name = f"iLAND {latest.stem}"
        layer = QgsRasterLayer(str(latest), layer_name)
        if not layer.isValid():
            self.status_label.setText(f"Failed to load output layer: {latest.name}")
            self._append_workflow_log(f"Layer invalid: {latest}")
            return

        QgsProject.instance().addMapLayer(layer)
        self.status_label.setText(f"Loaded output layer: {latest.name}")
        self._append_workflow_log(f"Loaded raster layer into QGIS: {latest}")

    def _apply_visualization_settings(self):
        payload = {
            "mode": self._selected_visual_mode(),
            "toggles": {name: box.isChecked() for name, box in self.visual_toggle_boxes.items()},
            "other_grid": self.visual_other_grid_edit.text().strip(),
            "expression": self.visual_expression_edit.text().strip(),
            "value": self.visual_value_combo.currentText(),
            "species": self._selected_species_code(),
        }
        self.config.set_value("visualization_settings", payload)
        self.status_label.setText("Visualization settings applied and saved.")

    def _on_visual_mode_toggled(self, checked: bool):
        if not checked:
            return
        if self._is_loading_ui_state:
            return
        self._sync_visual_toggle_availability()
        # iLAND viewer behavior: selecting a radio mode immediately changes the map output.
        self._apply_visualization_settings()
        self._visualize_on_qgis_canvas()

    def _sync_visual_toggle_availability(self):
        mode = self._selected_visual_mode().lower().strip()
        allowed: Set[str]
        if mode == "other grid":
            allowed = {"Autoscale colors", "clip to stands", "Shading"}
        elif mode == "resource units":
            allowed = {"color by species", "species shares", "Autoscale colors", "clip to stands", "Shading"}
        elif mode in ("individual trees", "snags"):
            allowed = {"draw transparent", "color by species", "clip to stands", "Shading"}
        elif mode == "regeneration":
            allowed = {"established", "clip to stands", "Shading"}
        elif mode == "dominance grid":
            allowed = {"based on stems", "Autoscale colors", "clip to stands", "Shading"}
        elif mode == "seed availability":
            allowed = {"clip to stands", "Shading"}
        else:  # light influence field
            allowed = {"clip to stands", "Shading"}

        for name, box in self.visual_toggle_boxes.items():
            enabled = name in allowed
            box.setEnabled(enabled)
            if not enabled:
                box.setChecked(False)

    def _run_visual_expression(self):
        mode = self._selected_visual_mode().lower().strip()
        expr = self.visual_expression_edit.text().strip()
        allowed_modes = {"individual trees", "snags", "resource units", "regeneration", "other grid"}
        if mode not in allowed_modes:
            self.status_label.setText("Expression execution is available for Trees, Snags, Resource Units, Regeneration, and Other Grid.")
            return
        if not expr:
            self.status_label.setText("Expression is empty.")
            return
        if not self._is_valid_visual_expression(expr):
            self.status_label.setText("Expression looks invalid. Check characters and parenthesis balance.")
            return

        if mode in ("regeneration", "seed availability") and not self._selected_species_code():
            self.status_label.setText("Select a species for species-specific expression results.")
            return

        self._append_workflow_log(f"Expression accepted for mode '{mode}': {expr}")
        self._apply_visualization_settings()
        self._visualize_on_qgis_canvas()

    def _is_valid_visual_expression(self, expr: str) -> bool:
        if len(expr) > 120:
            return False
        if re.search(r"[^a-zA-Z0-9_\s\+\-\*/\(\)\.<>=!&,]", expr):
            return False

        depth = 0
        for ch in expr:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    return False
        return depth == 0

    def _visualize_on_qgis_canvas(self):
        if self.iface is None or QgsProject is None or QgsRasterLayer is None:
            self.status_label.setText("QGIS map APIs are not available in this runtime.")
            return

        mode = self._selected_visual_mode() or "other grid"
        toggles = {name: box.isChecked() for name, box in self.visual_toggle_boxes.items()}
        output_dir = Path(self.output_dir_edit.text().strip() or str(self.repo_root / "output"))
        project_file = Path(self.project_file_edit.text().strip()) if self.project_file_edit.text().strip() else None
        project_dir = project_file.parent if project_file and project_file.exists() else None
        selected_species = self._selected_species_code()

        if mode.lower().strip() == "seed availability" and not selected_species:
            self.status_label.setText("Select a species for Seed availability visualization.")
            self._append_workflow_log(
                "Visualization blocked for Seed availability: no species selected (matches iLAND viewer behavior)."
            )
            return
        if mode.lower().strip() == "regeneration" and not selected_species:
            self._append_workflow_log(
                "Regeneration visualization running with <all species>. Select a species for species-specific regeneration view."
            )

        self._apply_visual_value_preset_if_needed()

        source_kind = "none"

        layer = self._load_mode_output_layer(mode=mode, output_dir=output_dir)
        if layer is not None:
            source_kind = "output"
        if layer is None and project_dir is not None:
            layer = self._load_mode_project_gis_layer(
                mode=mode,
                project_dir=project_dir,
                other_grid_hint=self.visual_other_grid_edit.text().strip(),
            )
            if layer is not None:
                source_kind = "project-gis"

        if layer is None:
            self.status_label.setText(f"No spatial layer found for visualization mode '{mode}'.")
            self._append_workflow_log(
                f"Visualization mode '{mode}' found no map layer in output/gis folders."
            )
            self._load_mode_output_table(mode=mode, output_dir=output_dir)
            return

        opacity = 0.6 if toggles.get("draw transparent", False) else 1.0
        layer.setOpacity(opacity)

        # Keep project CRS in sync with iLAND GIS layers to avoid fallback transforms.
        self._align_project_crs_with_layer(layer)

        self._load_mode_output_table(mode=mode, output_dir=output_dir)

        # Optional hillshade-like context: load DEM underlay when shading is requested.
        if toggles.get("Shading", False) and project_dir is not None:
            dem = self._find_project_dem(project_dir)
            if dem is not None and dem != Path(layer.source()):
                if self._layer_source_exists(str(dem)):
                    dem_layer = self._find_loaded_layer_by_source(str(dem))
                else:
                    dem_layer = QgsRasterLayer(str(dem), "iLAND DEM")
                    if dem_layer.isValid():
                        dem_layer.setOpacity(0.45)
                        QgsProject.instance().addMapLayer(dem_layer)
                    else:
                        dem_layer = None

                if dem_layer is not None:
                    self._mark_mode_layer(dem_layer, mode=mode, role="dem")
                    self._set_layer_visible(dem_layer, True)

        try:
            self.iface.mapCanvas().setExtent(layer.extent())
            self.iface.mapCanvas().refresh()
        except Exception:
            pass

        self._validate_mode_output(mode=mode, layer=layer, source_kind=source_kind)
        self._set_layer_visible(layer, True)
        self.status_label.setText(f"Visualization applied: {mode} -> {layer.name()}")
        self._append_workflow_log(f"Visualization applied: {mode} using layer '{layer.name()}'.")

    def _visual_value_presets(self) -> Dict[str, str]:
        return {
            "(value)": "",
            "tree.dbh": "dbh",
            "tree.height": "height",
            "ru.id": "id",
            "species": "species",
        }

    def _apply_visual_value_preset_if_needed(self):
        preset = self._visual_value_presets().get(self.visual_value_combo.currentText(), "")
        current = self.visual_expression_edit.text().strip()
        if current and current != self._last_visual_value_preset:
            return

        if preset:
            self.visual_expression_edit.setText(preset)
        elif current == self._last_visual_value_preset:
            self.visual_expression_edit.clear()

        self._last_visual_value_preset = preset

    def _on_visual_value_changed(self, _index: int):
        self._apply_visual_value_preset_if_needed()
        selected = self.visual_value_combo.currentText()

        if selected in self._known_species_codes and hasattr(self, "visual_species_combo"):
            sidx = self.visual_species_combo.findData(selected)
            if sidx >= 0:
                self.visual_species_combo.setCurrentIndex(sidx)
            if "color by species" in self.visual_toggle_boxes:
                self.visual_toggle_boxes["color by species"].setChecked(True)
            self._append_workflow_log(
                f"Visualization value selected species '{selected}' from dropdown."
            )
            self._apply_visualization_settings()
            return

        if selected == "species" and "color by species" in self.visual_toggle_boxes:
            self.visual_toggle_boxes["color by species"].setChecked(True)

        mode = self._selected_visual_mode() or "other grid"
        expr = self.visual_expression_edit.text().strip()
        if expr:
            self._append_workflow_log(
                f"Visualization value preset for mode '{mode}': '{selected}' -> expression '{expr}'."
            )

    def _mode_patterns(self, mode: str) -> List[str]:
        mode_key = mode.lower().strip()
        mapping = {
            "light influence field": ["*lif*", "*light*", "*fon*", "*wind_scale*"],
            "dominance grid": ["*dominance*", "*dom*", "*height*", "*objectid*"],
            "seed availability": ["*seed*", "*seeds*"],
            "regeneration": ["*regen*", "*regeneration*", "*snapshot*"],
            "resource units": ["*resource*unit*", "*ru*", "*objectid*"],
            "individual trees": ["*tree*", "*trees*"],
            "snags": ["*snag*", "*dead*"],
            "other grid": ["*"],
        }
        return mapping.get(mode_key, ["*"])

    def _load_mode_output_layer(self, mode: str, output_dir: Path):
        if not output_dir.exists() or QgsRasterLayer is None:
            return None

        patterns = self._mode_patterns(mode)
        candidates: List[Path] = []
        for pattern in patterns:
            for ext in (".tif", ".tiff", ".asc"):
                candidates.extend(output_dir.rglob(f"{pattern}{ext}"))

        candidates = sorted({c for c in candidates if c.exists() and c.is_file()}, key=lambda p: p.stat().st_mtime)
        if not candidates:
            return None

        target = candidates[-1]
        if self._layer_source_exists(str(target)):
            self._append_workflow_log(f"Mode '{mode}': reusing existing output raster {target.name}")
            reused = self._find_loaded_layer_by_source(str(target))
            if reused is not None:
                self._mark_mode_layer(reused, mode=mode, role="raster")
                self._set_layer_visible(reused, True)
            return reused

        layer = QgsRasterLayer(str(target), f"iLAND {mode} ({target.stem})")
        if not layer.isValid():
            self._append_workflow_log(f"Output layer invalid for mode '{mode}': {target}")
            return None

        QgsProject.instance().addMapLayer(layer)
        self._mark_mode_layer(layer, mode=mode, role="raster")
        self._set_layer_visible(layer, True)
        return layer

    def _load_mode_project_gis_layer(self, mode: str, project_dir: Path, other_grid_hint: str = ""):
        gis_dir = project_dir / "gis"
        init_dir = project_dir / "init"
        if (not gis_dir.exists() and not init_dir.exists()) or QgsRasterLayer is None:
            return None

        mode_key = mode.lower().strip()
        preferred: List[str] = []
        if mode_key in ("dominance grid", "resource units"):
            preferred = ["*objectid*.asc", "*objectid*.tif"]
        elif mode_key == "light influence field":
            preferred = ["*wind_scale*.asc", "*dem*.asc"]
        elif mode_key == "regeneration":
            preferred = ["*snapshot*.asc", "*regen*.asc", "*soid*.asc"]
        elif mode_key == "seed availability":
            preferred = ["*soid*.asc", "*environment*.asc"]
        elif mode_key == "other grid" and other_grid_hint:
            safe = other_grid_hint.strip().replace(" ", "*")
            preferred = [f"*{safe}*.asc", f"*{safe}*.tif"]
        else:
            preferred = ["*.asc", "*.tif", "*.tiff"]

        candidates: List[Path] = []
        for pattern in preferred:
            if gis_dir.exists():
                candidates.extend(gis_dir.rglob(pattern))
            if init_dir.exists() and mode_key == "regeneration":
                candidates.extend(init_dir.rglob(pattern))

        candidates = sorted({c for c in candidates if c.exists() and c.is_file()}, key=lambda p: p.stat().st_mtime)
        if not candidates:
            return None

        target = candidates[-1]
        if self._layer_source_exists(str(target)):
            self._append_workflow_log(f"Mode '{mode}': reusing existing project GIS raster {target.name}")
            reused = self._find_loaded_layer_by_source(str(target))
            if reused is not None:
                self._mark_mode_layer(reused, mode=mode, role="raster")
                self._set_layer_visible(reused, True)
            return reused

        layer = QgsRasterLayer(str(target), f"iLAND {mode} ({target.stem})")
        if not layer.isValid():
            self._append_workflow_log(f"Project GIS layer invalid for mode '{mode}': {target}")
            return None

        QgsProject.instance().addMapLayer(layer)
        self._mark_mode_layer(layer, mode=mode, role="raster")
        self._set_layer_visible(layer, True)
        return layer

    def _find_project_dem(self, project_dir: Path) -> Optional[Path]:
        gis_dir = project_dir / "gis"
        if not gis_dir.exists():
            return None
        hits = list(gis_dir.rglob("*dem*.asc")) + list(gis_dir.rglob("*dem*.tif"))
        if not hits:
            return None
        return sorted(hits, key=lambda p: p.stat().st_mtime)[-1]

    def _load_mode_output_table(self, mode: str, output_dir: Path):
        if QgsVectorLayer is None:
            return

        db_path = output_dir / "output.sqlite"
        if not db_path.exists():
            return

        table_map = {
            "resource units": "dynamicstand",
            "individual trees": "landscape",
            "snags": "wind",
            "seed availability": "landscape",
            "regeneration": "dynamicstand",
            "dominance grid": "dynamicstand",
            "light influence field": "landscape",
            "other grid": "landscape",
        }
        table_name = table_map.get(mode.lower().strip(), "landscape")
        uri = f"{db_path}|layername={table_name}"
        if self._layer_source_exists(uri):
            existing = self._find_loaded_layer_by_source(uri)
            if existing is not None:
                self._mark_mode_layer(existing, mode=mode, role="table")
                self._set_layer_visible(existing, True)
            return
        layer = QgsVectorLayer(uri, f"iLAND {table_name} table", "ogr")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            self._mark_mode_layer(layer, mode=mode, role="table")
            self._set_layer_visible(layer, True)
            self._append_workflow_log(f"Loaded output table '{table_name}' from output.sqlite")

    def _autoload_project_data_on_success(self):
        if self.iface is None or QgsProject is None:
            return

        project_path_text = self.project_file_edit.text().strip()
        if not project_path_text:
            return

        project_file = Path(project_path_text)
        if not project_file.exists():
            return

        project_dir = project_file.parent
        output_dir = Path(self.output_dir_edit.text().strip() or str(project_dir / "output"))

        loaded_count = 0
        loaded_count += self._autoload_project_gis_layers(project_dir)
        loaded_count += self._autoload_output_tables(output_dir)
        linked_db_count = self._count_project_linked_databases(project_dir)

        self.status_label.setText(
            f"Run completed. Auto-loaded {loaded_count} layers/tables. Linked DB files detected: {linked_db_count}."
        )
        self._append_workflow_log(
            f"Auto-load after run: loaded {loaded_count} layers/tables; linked database files found: {linked_db_count}."
        )

    def _autoload_project_gis_layers(self, project_dir: Path) -> int:
        if QgsRasterLayer is None or QgsProject is None:
            return 0

        gis_dir = project_dir / "gis"
        if not gis_dir.exists():
            return 0

        loaded = 0
        for pattern in ("*.asc", "*.tif", "*.tiff"):
            for raster_path in sorted(gis_dir.rglob(pattern)):
                if not raster_path.is_file():
                    continue
                if self._layer_source_exists(str(raster_path)):
                    continue
                layer = QgsRasterLayer(str(raster_path), f"iLAND GIS {raster_path.stem}")
                if layer.isValid():
                    QgsProject.instance().addMapLayer(layer)
                    self._align_project_crs_with_layer(layer)
                    loaded += 1
        return loaded

    def _autoload_output_tables(self, output_dir: Path) -> int:
        if QgsVectorLayer is None or QgsProject is None:
            return 0

        output_db = output_dir / "output.sqlite"
        if not output_db.exists():
            return 0

        loaded = 0
        preferred_tables = ["landscape", "dynamicstand", "wind", "barkbeetle"]
        for table in preferred_tables:
            if not self._sqlite_table_exists(output_db, table):
                continue
            uri = f"{output_db}|layername={table}"
            if self._layer_source_exists(uri):
                continue
            layer = QgsVectorLayer(uri, f"iLAND Output {table}", "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                loaded += 1

        return loaded

    def _count_project_linked_databases(self, project_dir: Path) -> int:
        count = 0
        for rel in ("database", "init", "output"):
            folder = project_dir / rel
            if not folder.exists():
                continue
            count += len(list(folder.glob("*.sqlite")))
        return count

    def _sqlite_table_exists(self, db_path: Path, table_name: str) -> bool:
        try:
            con = sqlite3.connect(str(db_path))
            cur = con.cursor()
            cur.execute(
                "select 1 from sqlite_master where type in ('table','view') and lower(name)=lower(?) limit 1",
                (table_name,),
            )
            row = cur.fetchone()
            con.close()
            return row is not None
        except Exception:
            return False

    def _layer_source_exists(self, source: str) -> bool:
        if QgsProject is None:
            return False
        normalized = source.replace("\\", "/").lower()
        for layer in QgsProject.instance().mapLayers().values():
            existing = layer.source().replace("\\", "/").lower()
            if existing == normalized:
                return True
        return False

    def _find_loaded_layer_by_source(self, source: str):
        if QgsProject is None:
            return None
        normalized = source.replace("\\", "/").lower()
        for layer in QgsProject.instance().mapLayers().values():
            existing = layer.source().replace("\\", "/").lower()
            if existing == normalized:
                return layer
        return None

    def _mark_mode_layer(self, layer, mode: str, role: str):
        try:
            layer.setCustomProperty("iland.managed_mode_layer", True)
            layer.setCustomProperty("iland.mode", mode)
            layer.setCustomProperty("iland.mode_role", role)
        except Exception:
            pass

    def _clear_managed_mode_layers(self):
        if QgsProject is None:
            return
        project = QgsProject.instance()
        to_remove: List[str] = []
        for layer_id, layer in project.mapLayers().items():
            if bool(layer.customProperty("iland.managed_mode_layer", False)):
                to_remove.append(layer_id)
        for layer_id in to_remove:
            project.removeMapLayer(layer_id)

    def _set_layer_visible(self, layer, visible: bool):
        if QgsProject is None or layer is None:
            return
        try:
            root = QgsProject.instance().layerTreeRoot()
            node = root.findLayer(layer.id())
            if node is not None:
                node.setItemVisibilityChecked(visible)
        except Exception:
            pass

    def _validate_mode_output(self, mode: str, layer, source_kind: str):
        if layer is None:
            return
        mode_patterns = [p.replace("*", "") for p in self._mode_patterns(mode) if p != "*"]
        source_name = Path(layer.source().split("|")[0]).name.lower()
        matched = any(pattern and pattern.lower() in source_name for pattern in mode_patterns)

        if matched:
            self._append_workflow_log(
                f"Mode validation OK: '{mode}' matched source '{source_name}' ({source_kind})."
            )
        else:
            self._append_workflow_log(
                f"Mode validation WARN: '{mode}' used source '{source_name}' ({source_kind}) via fallback."
            )

    def _align_project_crs_with_layer(self, layer):
        if QgsProject is None or layer is None:
            return

        try:
            project = QgsProject.instance()
            layer_crs = layer.crs()
            if not layer_crs.isValid():
                return

            project_crs = project.crs()
            should_align = False
            if not project_crs.isValid():
                should_align = True
            elif project_crs.authid() == "EPSG:4326" and layer_crs.authid() != "EPSG:4326":
                # Typical iLAND GIS inputs are projected; prevent ballpark-only fallback warnings.
                should_align = True

            if should_align and project_crs.authid() != layer_crs.authid():
                project.setCrs(layer_crs)
                self._append_workflow_log(
                    f"Project CRS auto-aligned to layer CRS: {layer_crs.authid()} ({layer_crs.description()})"
                )
        except Exception as exc:
            self._append_workflow_log(f"Could not auto-align project CRS: {exc}")

    def _reset_visualization_settings(self):
        first_mode = next(iter(self.visual_mode_buttons.values()), None)
        if first_mode is not None:
            first_mode.setChecked(True)
        for box in self.visual_toggle_boxes.values():
            box.setChecked(False)
            box.setEnabled(True)
        self.visual_other_grid_edit.clear()
        self.visual_expression_edit.clear()
        self.visual_value_combo.setCurrentIndex(0)
        if hasattr(self, "visual_species_combo"):
            self.visual_species_combo.setCurrentIndex(0)
        self._sync_visual_toggle_availability()
        self._apply_visualization_settings()

    def _selected_visual_mode(self) -> str:
        for name, button in self.visual_mode_buttons.items():
            if button.isChecked():
                return name
        return ""

    def _browse_script_file(self):
        start_dir = str(self.repo_root)
        current = self.script_file_edit.text().strip()
        if current:
            start_dir = str(Path(current).parent)
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select JavaScript File",
            start_dir,
            "JavaScript Files (*.js);;All Files (*)",
        )
        if file_path:
            self.script_file_edit.setText(file_path)
            self.config.set_string("script_file_path", file_path)

    def _load_script_file(self):
        path = Path(self.script_file_edit.text().strip())
        if not path.exists() or not path.is_file():
            self.status_label.setText("Script file does not exist.")
            return
        try:
            text = path.read_text(encoding="utf-8")
            self.script_editor.setPlainText(text)
            self.config.set_string("script_file_path", str(path))
            self.status_label.setText(f"Loaded script: {path.name}")
        except Exception as exc:
            self.status_label.setText(f"Could not load script: {exc}")

    def _save_script_file(self):
        raw = self.script_file_edit.text().strip()
        if not raw:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save JavaScript File",
                str(self.repo_root / "script.js"),
                "JavaScript Files (*.js);;All Files (*)",
            )
            if not file_path:
                return
            self.script_file_edit.setText(file_path)
            raw = file_path

        path = Path(raw)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.script_editor.toPlainText(), encoding="utf-8")
            self.config.set_string("script_file_path", str(path))
            self.status_label.setText(f"Saved script: {path.name}")
        except Exception as exc:
            self.status_label.setText(f"Could not save script: {exc}")

    def _copy_script_command_args(self):
        script_path = self.script_file_edit.text().strip()
        if not script_path:
            self.status_label.setText("Select a script file to build command args.")
            return
        args = f'--script "{script_path}"'
        QGuiApplication.clipboard().setText(args)
        self.status_label.setText("Script run args copied to clipboard.")

    def _refresh_script_workspace(self):
        text = self.script_editor.toPlainText()
        lines = 0 if not text else text.count("\n") + 1
        chars = len(text)
        self.script_tree.clear()
        self.script_tree.addTopLevelItem(QTreeWidgetItem(["Global", "object"]))
        self.script_tree.addTopLevelItem(QTreeWidgetItem(["Model", "object"]))
        self.script_tree.addTopLevelItem(QTreeWidgetItem(["Script lines", str(lines)]))
        self.script_tree.addTopLevelItem(QTreeWidgetItem(["Script chars", str(chars)]))

    def _load_persisted_ui_state(self):
        self._is_loading_ui_state = True
        # Keep startup clean: no auto-filled paths and no implicit run/create behavior.
        self.project_file_edit.setText("")
        try:
            self._last_run_year_request = int(self.config.get_string("workflow_last_years", "10"))
        except ValueError:
            self._last_run_year_request = 10
        self._set_current_year_display(0)
        self.output_dir_edit.setText("")
        self.script_file_edit.setText(self.config.get_string("script_file_path", ""))
        self._refresh_species_controls()

        viz = self.config.get_value("visualization_settings", {})
        if not isinstance(viz, dict):
            viz = {}

        mode = str(viz.get("mode", ""))
        if mode in self.visual_mode_buttons:
            self.visual_mode_buttons[mode].setChecked(True)
        else:
            self._reset_visualization_settings()

        toggles = viz.get("toggles", {})
        if isinstance(toggles, dict):
            for name, box in self.visual_toggle_boxes.items():
                box.setChecked(bool(toggles.get(name, False)))

        self.visual_other_grid_edit.setText(str(viz.get("other_grid", "")))
        self.visual_expression_edit.setText(str(viz.get("expression", "")))
        value = str(viz.get("value", "(value)"))
        index = self.visual_value_combo.findText(value)
        self.visual_value_combo.setCurrentIndex(index if index >= 0 else 0)
        species = str(viz.get("species", ""))
        species_index = self.visual_species_combo.findData(species)
        self.visual_species_combo.setCurrentIndex(species_index if species_index >= 0 else 0)
        self._sync_visual_toggle_availability()

        debug_selection = self.config.get_value("debug_data_selection", {})
        if isinstance(debug_selection, dict):
            for name, box in self.debug_action_boxes.items():
                box.setChecked(bool(debug_selection.get(name, False)))
        self._append_debug_log("Debug Data tools ready.")

        level = self.config.get_string("misc_log_level", "Info")
        if level in self.misc_log_level_buttons:
            self.misc_log_level_buttons[level].setChecked(True)
        else:
            self.misc_log_level_buttons["Info"].setChecked(True)
        self._append_misc_log("Misc tools ready.")
        self._refresh_script_workspace()
        self._update_run_controls_state()
        self._is_loading_ui_state = False

    def _apply_theme(self):
        self.setStyleSheet(self._style_sheet(self._is_dark_palette()))

    def _is_dark_palette(self) -> bool:
        palette = self.palette()
        try:
            window_role = QPalette.ColorRole.Window
            text_role = QPalette.ColorRole.WindowText
        except AttributeError:  # pragma: no cover - Qt5 fallback
            window_role = QPalette.Window
            text_role = QPalette.WindowText
        window_color = palette.color(window_role)
        text_color = palette.color(text_role)
        return window_color.lightness() < text_color.lightness()

    def _style_sheet(self, dark_mode: bool) -> str:
        if dark_mode:
            background = "#232629"
            dock_border = "#3a3d40"
            panel = "#2d3033"
            field_bg = "#1f2124"
            field_border = "#4b4e52"
            text = "#f1f3f5"
            button_bg = "#3a3d40"
            button_hover = "#4a4e52"
            selected_bg = "#24537a"
            progress_track = "#14171a"
            progress_idle = "#6f7780"
        else:
            background = "#f5f5f5"
            dock_border = "#d0d0d0"
            panel = "#ececec"
            field_bg = "#ffffff"
            field_border = "#c9c9c9"
            text = "#000000"
            button_bg = "#e1e1e1"
            button_hover = "#d4d4d4"
            selected_bg = "#d7e9ff"
            progress_track = "#f1f3f5"
            progress_idle = "#9aa3ad"

        return f"""
            QDockWidget {{
                background: {background};
                border-left: 1px solid {dock_border};
            }}
            QWidget {{
                font-family: "Segoe UI", "Noto Sans";
                font-size: 10pt;
                color: {text};
            }}
            QLabel#ilandTitle {{
                font-size: 14pt;
                font-weight: 700;
                color: {text};
            }}
            QLabel#ilandSubtitle {{
                color: {text};
            }}
            QLabel#summaryLabel {{
                background: {panel};
                border: 1px solid {dock_border};
                border-radius: 6px;
                padding: 8px;
            }}
            QLineEdit,
            QPlainTextEdit,
            QTreeWidget,
            QListWidget,
            QTabWidget::pane {{
                background: {field_bg};
                border: 1px solid {field_border};
                color: {text};
            }}
            QLineEdit,
            QPlainTextEdit {{
                border-radius: 6px;
                padding: 5px;
            }}
            QPushButton {{
                background: {button_bg};
                border: 1px solid {field_border};
                border-radius: 6px;
                color: {text};
                padding: 6px 10px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {button_hover};
            }}
            QTreeWidget::item:selected,
            QListWidget::item:selected {{
                background: {selected_bg};
                color: {text};
            }}
            QProgressBar#modelRunProgress {{
                background: {progress_track};
                border: 1px solid {field_border};
                border-radius: 6px;
                min-height: 12px;
            }}
            QProgressBar#modelRunProgress::chunk {{
                background: {progress_idle};
                border-radius: 5px;
            }}
            QProgressBar#modelRunProgress[runState="running"]::chunk {{
                background: #2b7fff;
            }}
            QProgressBar#modelRunProgress[runState="success"]::chunk {{
                background: #22a05f;
            }}
            QProgressBar#modelRunProgress[runState="paused"]::chunk {{
                background: #d7911a;
            }}
            QProgressBar#modelRunProgress[runState="failed"]::chunk {{
                background: #d1493f;
            }}
        """
