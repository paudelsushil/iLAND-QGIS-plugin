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
    from PyQt6.QtCore import QTimer, Qt  # type: ignore[import-not-found]
    from PyQt6.QtGui import QGuiApplication, QIcon, QPalette, QPixmap
    from PyQt6.QtWidgets import (
        QButtonGroup,
        QCheckBox,
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
    )  # type: ignore[import-not-found]

except ImportError:  # pragma: no cover - runtime fallback for QGIS 3.x
    from qgis.PyQt.QtCore import QTimer, Qt  # type: ignore[import-not-found]
    from qgis.PyQt.QtGui import QGuiApplication, QIcon, QPalette, QPixmap
    from qgis.PyQt.QtWidgets import (
        QButtonGroup,
        QCheckBox,
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
    )  # type: ignore[import-not-found]


USER_ROLE = _first_qt_attr(Qt, ["ItemDataRole.UserRole", "UserRole"])
HORIZONTAL = _first_qt_attr(Qt, ["Orientation.Horizontal", "Horizontal"])
ASPECT_KEEP = _first_qt_attr(Qt, ["AspectRatioMode.KeepAspectRatio", "KeepAspectRatio"])
TRANSFORM_SMOOTH = _first_qt_attr(
    Qt,
    ["TransformationMode.SmoothTransformation", "SmoothTransformation"],
)

from .config_manager import ILandPluginConfig
from .iland_ui_catalog import ILandUICatalog
from .module_registry import ILandModuleRegistry, ModuleInfo, SubmoduleInfo
from .runtime_manager import ILandRuntimeManager

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
        self._is_loading_ui_state = False
        self._model_poll_timer = None
        self._workflow_log_full_backup = ""
        self._last_visual_value_preset = ""
        self._known_species_codes: List[str] = []

        self.setObjectName("iLANDWorkbenchDock")
        self.setMinimumWidth(520)

        container = QWidget(self)
        root_layout = QVBoxLayout(container)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        logo = QLabel()
        logo.setFixedSize(36, 36)
        logo_path = self.repo_root / "iLAND_QGIS_plugin" / "icon4.png"
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            logo.setPixmap(pixmap.scaled(36, 36, ASPECT_KEEP, TRANSFORM_SMOOTH))
        header_text = QVBoxLayout()
        title = QLabel("iLAND Workbench")
        title.setObjectName("ilandTitle")
        subtitle = QLabel("Project input, processing controls, visualization panels, and outputs in one dock.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("ilandSubtitle")
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header_row.addWidget(logo)
        header_row.addLayout(header_text)
        header_row.addStretch(1)

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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        form = QFormLayout()
        self.project_file_edit = QLineEdit()
        self.project_file_edit.setPlaceholderText("Path to xml project file...")
        self.project_file_browse_button = QPushButton("...")
        self.project_file_browse_button.setFixedWidth(28)
        self.project_file_browse_button.clicked.connect(self._browse_project_xml)
        project_row = QHBoxLayout()
        project_row_widget = QWidget()
        project_row_widget.setLayout(project_row)
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

        form.addRow("Project XML", project_row_widget)
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
        self.model_run_progress.setTextVisible(False)
        self.model_run_progress.setMinimum(0)
        self.model_run_progress.setMaximum(1)
        self.model_run_progress.setValue(0)
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

        splitter = QSplitter(HORIZONTAL)
        splitter.setChildrenCollapsible(False)

        left = QFrame()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.settings_tree = QTreeWidget()
        self.settings_tree.setHeaderLabels(["iLAND Settings", "Type"])
        self.settings_tree.itemSelectionChanged.connect(self._on_settings_selection)
        left_layout.addWidget(self.settings_tree)

        right = QFrame()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.settings_summary = QLabel("Select a settings group.")
        self.settings_summary.setWordWrap(True)
        self.settings_keys_list = QListWidget()
        right_layout.addWidget(self.settings_summary)
        right_layout.addWidget(self.settings_keys_list)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter)
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
        self.runtime_install_button = QPushButton("Install Latest (Windows)")
        self.runtime_install_button.clicked.connect(self._on_install_latest_runtime)
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

        layout.addLayout(repo_form)
        layout.addLayout(button_row)
        layout.addWidget(QLabel("Latest Release Assets"))
        layout.addWidget(self.runtime_assets_list)
        layout.addWidget(QLabel("Installed Runtimes"))
        layout.addWidget(self.runtime_local_list)
        layout.addWidget(self.runtime_activate_button)
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

        module_count = len(self.modules)
        submodule_count = sum(self._count_submodules(module.submodules) for module in self.modules)
        self.status_label.setText(
            f"Discovered {module_count} modules, {submodule_count} submodules, and loaded iLAND UI catalogs."
        )

    def set_repo_root(self, repo_root: Path):
        self.repo_root = Path(repo_root)
        self.output_dir_edit.setText(str(self.repo_root / "output"))
        self.registry = ILandModuleRegistry(repo_root=self.repo_root)
        self.ui_catalog = ILandUICatalog(repo_root=self.repo_root)
        self.refresh_modules()

    def _rebuild_settings_tree(self):
        catalog = self.ui_catalog.discover_settings_catalog()
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
        self.settings_keys_list.clear()

        if kind == "category":
            self.settings_summary.setText(f"{name}: select a tab to see mapped settings.")
            return

        if kind == "tab":
            keys = self.settings_tab_map.get(name, [])
            self.settings_summary.setText(f"{name}: {len(keys)} settings mapped from project_file_metadata.txt")
            for key in keys:
                self.settings_keys_list.addItem(QListWidgetItem(key))

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
            self._update_run_controls_state()

    def _browse_output_dir(self):
        start_dir = self.output_dir_edit.text().strip() or str(self.repo_root / "output")
        folder = QFileDialog.getExistingDirectory(self, "Select output directory", start_dir)
        if folder:
            self.output_dir_edit.setText(folder)

    def _set_button_icon(self, button: QPushButton, icon_name: str):
        candidates = [
            self.plugin_dir / "icons" / icon_name,
            self.repo_root / "src" / "iland" / "res" / icon_name,
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                button.setIcon(QIcon(str(candidate)))
                break

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

    def _classify_session_startup_failure(self, ready: Dict[str, str], executable: Path) -> str:
        msg = str(ready.get("msg", "")).lower()
        boot = str(ready.get("boot", "")).lower()

        if "invalid number of years to run" in boot:
            return (
                "Selected iLANDc runtime does not support --session mode (legacy console signature detected). "
                "Activate a newer runtime/executable built from this repository's session-capable sources. "
                f"Current executable: {executable}"
            )
        if "usage:" in boot and "ilandc.exe <xml-project-file> <years>" in boot:
            return (
                "Selected iLANDc runtime appears to be legacy CLI-only and does not support persistent session mode. "
                "Please activate updated iLANDc.exe."
            )
        if msg == "session_closed":
            return (
                "Session backend closed before handshake. This usually means an incompatible runtime binary or missing runtime dependencies. "
                f"Executable: {executable}"
            )
        return "iLAND runtime does not support persistent session mode. Install updated runtime."

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
                self._append_workflow_log(f"Session startup failed: {ready}")
                self._stop_session()
                self.status_label.setText(self._classify_session_startup_failure(ready, executable))
                self.model_status_label.setText("Model status: session start failed")
                return False

            self._append_workflow_log("Started persistent iLAND session backend.")
            self.config.set_string("workflow_last_project", project_file)
            if output_dir:
                self.config.set_string("workflow_output_dir", output_dir)
            self.config.set_string("workflow_executable_path", str(executable))
            return True
        except Exception as exc:
            self._stop_session()
            self.status_label.setText(f"Could not start session backend: {exc}")
            self.model_status_label.setText("Model status: session start failed")
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

    def _run_one_year(self):
        if self._is_model_running():
            self.status_label.setText("A model run is already in progress.")
            return
        if not self._model_created:
            self.status_label.setText("Create Model first, then run one year.")
            return
        if not self._ensure_session(self.project_file_edit.text().strip()):
            self._update_run_controls_state()
            return

        reply = self._session_command("RUN_ONE_YEAR", timeout_seconds=3600)
        if reply.get("status") != "OK":
            self.status_label.setText(f"Run one year failed: {reply.get('msg', 'unknown error')}")
            self.model_status_label.setText("Model status: run failed")
            self._append_workflow_log(f"RUN_ONE_YEAR failed: {reply}")
            self._update_run_controls_state()
            return

        year_value = int(reply.get("year", str(self._current_year + 1)))
        self._set_current_year_display(year_value)
        self._runtime_reported_year = year_value
        self.model_status_label.setText("Model status: completed one year")
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
                self._append_workflow_log("Pause requested. Execution will continue after current yearly step.")
            else:
                self.model_status_label.setText("Model status: running")
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
                self._append_workflow_log(f"Model process resumed (PID {pid}).")
        except Exception as exc:
            self.status_label.setText(f"Pause/Continue failed: {exc}")
            self._append_workflow_log(f"Pause/Continue operation failed for PID {pid}: {exc}")

        self._update_run_controls_state()

    def _stop_model(self):
        if self._session_run_thread is not None and self._session_run_thread.is_alive():
            self._session_stop_requested = True
            self.status_label.setText("Stop requested. Waiting for current year step to finish...")
            self.model_status_label.setText("Model status: stopping...")
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

        if executable is None:
            self.model_status_label.setText("Model status: missing executable")
            self.status_label.setText("iLANDc runtime not found. Check Runtime tab to install/activate one.")
            self._append_workflow_log("Run blocked: executable not found after runtime auto-install attempt.")
            return None

        executable_str = str(executable)
        if "ilandc" not in Path(executable_str).name.lower():
            self.model_status_label.setText("Model status: invalid executable")
            self.status_label.setText("Selected executable is not iLANDc.exe. Headless console engine is required.")
            self._append_workflow_log(
                f"Run blocked: '{executable_str}' appears to be GUI app. Please select iLANDc.exe."
            )
            return None
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

        if not self._ensure_session(project_file):
            self._update_run_controls_state()
            return

        self.model_status_label.setText("Model status: creating...")
        reply = self._session_command("CREATE", timeout_seconds=3600)
        if reply.get("status") != "OK":
            self.model_status_label.setText("Model status: create failed")
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
        self.status_label.setText("Model created. Ready to run.")
        self._append_workflow_log("Create Model completed successfully using persistent session backend.")
        self._update_run_controls_state()

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
            return path.name.lower() == "ilandc.exe"

        from_runtime = self.runtime_manager.get_active_executable()
        if from_runtime is not None and from_runtime.exists() and is_ilandc(from_runtime):
            return from_runtime

        saved = self.config.get_string("workflow_executable_path", "")
        if saved:
            saved_path = Path(saved)
            if saved_path.exists() and saved_path.is_file() and is_ilandc(saved_path):
                return saved_path

        common_candidates = [
            self.repo_root / "iLANDc.exe",
            self.repo_root / "build" / "iLANDc.exe",
            self.repo_root / "bin" / "iLANDc.exe",
        ]
        for candidate in common_candidates:
            if candidate.exists() and candidate.is_file() and is_ilandc(candidate):
                return candidate

        for root_name in ["build", "bin", "dist", "release", "x64"]:
            root = self.repo_root / root_name
            if not root.exists():
                continue
            hits = list(root.rglob("iLANDc.exe"))
            if hits:
                return hits[0]

        which_path = shutil.which("iLANDc.exe")
        if which_path:
            which_candidate = Path(which_path)
            if is_ilandc(which_candidate):
                return which_candidate

        return None

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
            ("Metadata exists", (self.repo_root / "src" / "iland" / "res" / "project_file_metadata.txt").exists()),
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
        xml_path_raw = self.project_file_edit.text().strip()
        if not xml_path_raw:
            self._append_misc_log("Update XML file skipped: no project XML path provided.")
            return
        xml_path = Path(xml_path_raw)
        if not xml_path.exists():
            self._append_misc_log(f"Update XML file skipped: {xml_path} not found.")
            return

        metadata_file = self.repo_root / "src" / "iland" / "res" / "project_file_metadata.txt"
        if not metadata_file.exists():
            self._append_misc_log("Update XML file skipped: metadata file not found.")
            return

        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            xml_text = ET.tostring(root, encoding="unicode")
        except Exception as exc:
            self._append_misc_log(f"Could not parse project XML: {exc}")
            return

        keys = []
        for line in metadata_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(";") or "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0].strip()
            if key and key != "gui.layout":
                keys.append(key)

        missing: List[str] = []
        for key in keys:
            pattern = re.escape(key)
            if re.search(pattern, xml_text) is None:
                missing.append(key)

        report_file = xml_path.with_suffix(xml_path.suffix + ".missing_keys.txt")
        report_file.write_text("\n".join(missing), encoding="utf-8")
        self._append_misc_log(
            f"Update XML analysis complete. Missing keys: {len(missing)}. Report: {report_file.name}"
        )

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
        if not self._ensure_session(project_file):
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
                else:
                    self.model_status_label.setText(
                        f"Model status: running ({seconds}s) | year {shown_year} -> {self._active_target_year}"
                    )
                return

            if self._session_run_finalize_pending:
                self._session_run_finalize_pending = False
                self._session_run_thread = None
                self.model_run_progress.setMinimum(0)
                self.model_run_progress.setMaximum(1)
                self.model_run_progress.setValue(1)

                if self._session_last_error:
                    self.model_status_label.setText("Model status: run failed")
                    self.status_label.setText(f"Run Model failed: {self._session_last_error}")
                    self._append_workflow_log(f"RUN_YEARS failed: {self._session_last_error}")
                elif self._session_stop_requested:
                    self.model_status_label.setText("Model status: stopped")
                    self.status_label.setText("Model stopped.")
                    self._append_workflow_log(
                        f"Run stopped by user after {self._session_run_completed_years}/{self._session_run_requested_years} year steps."
                    )
                else:
                    self._model_created = True
                    self._set_current_year_display(max(self._current_year, self._runtime_reported_year))
                    self.model_status_label.setText("Model status: completed")
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
                else:
                    shown_year = max(self._current_year, self._runtime_reported_year)
                    if self._active_target_year > 0:
                        self.model_status_label.setText(
                            f"Model status: running ({seconds}s) | year {shown_year} -> {self._active_target_year}"
                        )
                    else:
                        self.model_status_label.setText(f"Model status: running ({seconds}s) | year {shown_year}")
            return

        self.model_run_progress.setMinimum(0)
        self.model_run_progress.setMaximum(1)
        self.model_run_progress.setValue(1)
        if code == 0:
            if self._active_run_mode == "create":
                self._model_created = True
                self._set_current_year_display(1)
                self.model_status_label.setText("Model status: created")
                self.status_label.setText("Model created. Ready to run.")
                self._append_workflow_log("Create Model completed successfully.")
            else:
                self._model_created = True
                if self._active_target_year > 0:
                    self._set_current_year_display(self._active_target_year)
                self.model_status_label.setText("Model status: completed")
                self._append_workflow_log("Model process completed successfully.")
                self._autoload_project_data_on_success()
        else:
            self.model_status_label.setText(f"Model status: exited with code {code}")
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
        output_dir = self.output_dir_edit.text().strip() or str(self.repo_root / "output")
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
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

        output_dir = Path(self.output_dir_edit.text().strip() or str(self.repo_root / "output"))
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
        """
