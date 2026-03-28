"""Dynamic iLAND-style settings dialog for editing project XML values."""

from __future__ import annotations

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
    from PyQt6.QtCore import Qt, QLocale  # type: ignore[import-not-found]
    from PyQt6.QtGui import QIcon, QDoubleValidator, QIntValidator  # type: ignore[import-not-found]
    from PyQt6.QtWidgets import (  # type: ignore[import-not-found]
        QCheckBox,
        QDialog,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSplitter,
        QTreeWidget,
        QTreeWidgetItem,
        QTableWidget,
        QTableWidgetItem,
        QToolButton,
        QVBoxLayout,
        QWidget,
        QComboBox,
    )
except ImportError:  # pragma: no cover - runtime fallback for QGIS 3.x
    from qgis.PyQt.QtCore import Qt, QLocale  # type: ignore[import-not-found]
    from qgis.PyQt.QtGui import QIcon, QDoubleValidator, QIntValidator  # type: ignore[import-not-found]
    from qgis.PyQt.QtWidgets import (  # type: ignore[import-not-found]
        QCheckBox,
        QDialog,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSplitter,
        QTreeWidget,
        QTreeWidgetItem,
        QTableWidget,
        QTableWidgetItem,
        QToolButton,
        QVBoxLayout,
        QWidget,
        QComboBox,
    )


USER_ROLE = _first_qt_attr(Qt, ["ItemDataRole.UserRole", "UserRole"])
HORIZONTAL = _first_qt_attr(Qt, ["Orientation.Horizontal", "Horizontal"])
MSGBOX_YES = _resolve_qt_attr(QMessageBox, "StandardButton.Yes") or getattr(QMessageBox, "Yes")
MSGBOX_NO = _resolve_qt_attr(QMessageBox, "StandardButton.No") or getattr(QMessageBox, "No")


class ILandSettingsDialog(QDialog):
    """Standalone settings dialog modeled after iLAND desktop behavior."""

    def __init__(
        self,
        repo_root: Path,
        plugin_dir: Path,
        project_file: str,
        categories: Dict[str, List[str]],
        tab_map: Dict[str, List[str]],
        tab_layout: Dict[str, List[Dict[str, str]]],
        tab_titles: Dict[str, str],
        tab_descriptions: Dict[str, str],
        field_meta: Dict[str, Dict[str, str]],
        initial_tab: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.repo_root = Path(repo_root)
        self.plugin_dir = Path(plugin_dir)
        self.current_project_file = project_file.strip()

        self.categories = {k: list(v) for k, v in categories.items()}
        self.tab_map = dict(tab_map)
        self.tab_layout = dict(tab_layout)
        self.tab_titles = dict(tab_titles)
        self.tab_descriptions = dict(tab_descriptions)
        self.field_meta = dict(field_meta)

        self.current_tab_name = ""
        self.current_tab_keys: List[str] = []
        self.widget_instances: Dict[str, List[Dict[str, object]]] = {}
        self.active_instance_by_key: Dict[str, Dict[str, object]] = {}
        self.key_primary_tab: Dict[str, str] = self._build_primary_tab_map()

        self._xml_tree: Optional[ET.ElementTree] = None
        self._xml_path: Optional[Path] = None
        self.loaded_values: Dict[str, str] = {}
        self.pending_values: Dict[str, str] = {}
        self.dirty_keys: Set[str] = set()
        self._changes_dialog: Optional[QDialog] = None
        self._changes_table: Optional[QTableWidget] = None
        self._change_keys: List[str] = []
        self.comments: Dict[str, str] = {}

        self.filter_mode = "simple"
        self.initial_tab = initial_tab.strip()
        self._home_path_last_applied = ""

        self.setWindowTitle(self.current_project_file or "Edit Settings")
        self.resize(1180, 760)

        self._build_ui()
        self._rebuild_tree()
        self._ensure_xml_loaded(force_reload=True)
        self._update_dirty_state()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        toolbar_row = QHBoxLayout()
        self.filter_simple_button = QPushButton("Simple view")
        self.filter_advanced_button = QPushButton("Advanced view")
        self.filter_all_button = QPushButton("Show all")
        self.show_changes_button = QPushButton("Show changes")
        for button in [self.filter_simple_button, self.filter_advanced_button, self.filter_all_button]:
            button.setCheckable(True)
        self.filter_simple_button.setChecked(True)
        self.show_changes_button.setEnabled(False)

        self.filter_simple_button.clicked.connect(lambda: self._set_filter_mode("simple"))
        self.filter_advanced_button.clicked.connect(lambda: self._set_filter_mode("advanced"))
        self.filter_all_button.clicked.connect(lambda: self._set_filter_mode("all"))
        self.show_changes_button.clicked.connect(self._show_changes_dialog)

        icon_map = {
            self.filter_simple_button: ("iconFilterSimple.png", "Only basic options are shown."),
            self.filter_advanced_button: (
                "iconFilterAdvanced.png",
                "Shows also more advanced options, besides the elements of 'Simple view'.",
            ),
            self.filter_all_button: (
                "iconFilterAll.png",
                "Advanced settings and also deprecated variables.",
            ),
            self.show_changes_button: ("iconMagnifyingGlass.png", "Show table with modified values."),
        }
        for button, (icon_name, tooltip) in icon_map.items():
            icon_path = self.plugin_dir / "res" / icon_name
            if icon_path.exists() and icon_path.is_file():
                button.setIcon(QIcon(str(icon_path)))
            button.setToolTip(tooltip)

        toolbar_row.addWidget(self.filter_simple_button)
        toolbar_row.addWidget(self.filter_advanced_button)
        toolbar_row.addWidget(self.filter_all_button)
        toolbar_row.addWidget(self.show_changes_button)
        toolbar_row.addStretch(1)

        split = QSplitter(HORIZONTAL)
        split.setChildrenCollapsible(False)

        left = QFrame()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.settings_tree = QTreeWidget()
        self.settings_tree.setHeaderHidden(True)
        self.settings_tree.itemSelectionChanged.connect(self._on_tree_selection)
        left_layout.addWidget(self.settings_tree)

        right = QFrame()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.summary_label = QLabel("Select a settings tab.")
        self.summary_label.setTextFormat(_first_qt_attr(Qt, ["TextFormat.RichText", "RichText"]))
        self.summary_label.setWordWrap(True)
        self.description_label = QLabel("")
        self.description_label.setTextFormat(_first_qt_attr(Qt, ["TextFormat.RichText", "RichText"]))
        self.description_label.setOpenExternalLinks(True)
        self.description_label.setWordWrap(True)

        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        self.editor_container = QWidget()
        self.editor_layout = QVBoxLayout(self.editor_container)
        self.editor_layout.setContentsMargins(0, 0, 0, 0)
        self.editor_layout.setSpacing(6)
        self.editor_scroll.setWidget(self.editor_container)

        right_layout.addWidget(self.summary_label)
        right_layout.addWidget(self.description_label)
        right_layout.addWidget(self.editor_scroll)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)

        self.dirty_label = QLabel("No pending changes.")
        self.dirty_label.setVisible(False)

        button_row = QHBoxLayout()
        button_row.addWidget(self.dirty_label)
        self.save_button = QPushButton("Save Changes")
        self.save_as_button = QPushButton("Save as...")
        self.cancel_button = QPushButton("Cancel")
        self.save_button.clicked.connect(self._save_changes)
        self.save_as_button.clicked.connect(self._save_as)
        self.cancel_button.clicked.connect(self.reject)
        button_row.addStretch(1)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.save_as_button)
        button_row.addWidget(self.cancel_button)

        root.addLayout(toolbar_row)
        root.addWidget(split, 1)
        root.addLayout(button_row)

    def _rebuild_tree(self):
        self.settings_tree.clear()
        root_item = QTreeWidgetItem(["Project"])
        root_item.setData(0, USER_ROLE, {"kind": "root", "name": "Project"})

        tabs_seen: Set[str] = set()
        for category, tabs in self.categories.items():
            category_item = QTreeWidgetItem([category])
            category_item.setData(0, USER_ROLE, {"kind": "category", "name": category})
            for tab in tabs:
                tabs_seen.add(tab)
                tab_item = QTreeWidgetItem([tab])
                tab_item.setData(0, USER_ROLE, {"kind": "tab", "name": tab})
                category_item.addChild(tab_item)
            if category_item.childCount() > 0:
                root_item.addChild(category_item)

        extra_tabs = sorted([t for t in self.tab_map.keys() if t not in tabs_seen])
        if extra_tabs:
            extra_item = QTreeWidgetItem(["Other"])
            extra_item.setData(0, USER_ROLE, {"kind": "category", "name": "Other"})
            for tab in extra_tabs:
                tab_item = QTreeWidgetItem([tab])
                tab_item.setData(0, USER_ROLE, {"kind": "tab", "name": tab})
                extra_item.addChild(tab_item)
            root_item.addChild(extra_item)

        self.settings_tree.addTopLevelItem(root_item)

        self.settings_tree.expandToDepth(2)
        if self.initial_tab:
            item = self._find_tab_item(self.initial_tab)
            if item is not None:
                self.settings_tree.setCurrentItem(item)
                return
        first_tab = self._first_tab_item()
        if first_tab is not None:
            self.settings_tree.setCurrentItem(first_tab)

    def _first_tab_item(self) -> Optional[QTreeWidgetItem]:
        if self.settings_tree.topLevelItemCount() == 0:
            return None
        root = self.settings_tree.topLevelItem(0)
        if root is None:
            return None
        for i in range(root.childCount()):
            category = root.child(i)
            if category is None:
                continue
            for j in range(category.childCount()):
                child = category.child(j)
                if child is None:
                    continue
                payload = child.data(0, USER_ROLE)
                if isinstance(payload, dict) and payload.get("kind") == "tab":
                    return child
        return None

    def _find_tab_item(self, tab_name: str) -> Optional[QTreeWidgetItem]:
        if self.settings_tree.topLevelItemCount() == 0:
            return None
        root = self.settings_tree.topLevelItem(0)
        if root is None:
            return None
        for i in range(root.childCount()):
            category = root.child(i)
            if category is None:
                continue
            for j in range(category.childCount()):
                child = category.child(j)
                if child is None:
                    continue
                payload = child.data(0, USER_ROLE)
                if isinstance(payload, dict) and payload.get("kind") == "tab" and payload.get("name") == tab_name:
                    return child
        return None

    def _set_filter_mode(self, mode: str):
        self.filter_mode = mode
        self.filter_simple_button.setChecked(mode == "simple")
        self.filter_advanced_button.setChecked(mode == "advanced")
        self.filter_all_button.setChecked(mode == "all")

        for key, instances in self.widget_instances.items():
            visibility = str(self.field_meta.get(key, {}).get("visibility", "simple")).strip().lower()
            if mode == "all":
                visible = True
            elif mode == "advanced":
                visible = visibility != "all"
            else:
                visible = visibility == "simple"
            for inst in instances:
                container = inst.get("container")
                if isinstance(container, QWidget):
                    container.setVisible(visible)

    def _build_primary_tab_map(self) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for tab_name, specs in self.tab_layout.items():
            for spec in specs:
                if spec.get("kind") not in {"field", "connected"}:
                    continue
                key = str(spec.get("key", "")).strip()
                if not key:
                    continue
                if key not in mapping:
                    mapping[key] = tab_name
        return mapping

    def _linkify(self, text: str, collapse: bool = False) -> str:
        import re

        def repl(match: re.Match[str]) -> str:
            url = match.group(0)
            if collapse:
                return f'<a href="{url}">(more)</a>'
            return f'<a href="{url}">{url}</a>'

        return re.sub(r"((?:https?|ftp)://\S+)", repl, text)

    def _on_tree_selection(self):
        selected = self.settings_tree.selectedItems()
        if not selected:
            return
        selected_item = selected[0]
        payload = selected_item.data(0, USER_ROLE)
        if not payload:
            return
        kind = payload.get("kind")

        if kind == "tab":
            tab_name = str(payload.get("name", "")).strip()
            if not tab_name:
                return
            self._render_tab(tab_name)
            return

        if kind in {"category", "root"}:
            category_name = str(payload.get("name", "")).strip()
            overview_tab = self._overview_tab_for_category(category_name, selected_item)
            if overview_tab:
                self._render_tab(overview_tab)
            return

    def _overview_tab_for_category(self, category_name: str, item: QTreeWidgetItem) -> str:
        overview_map = {
            "Project": "Project Description",
            "System": "System Settings",
            "Model": "Model Settings",
            "Output": "Output",
            "Modules": "Modules",
        }

        mapped = overview_map.get(category_name, "")
        if mapped and mapped in self.tab_map:
            return mapped

        if category_name == "Other":
            for i in range(item.childCount()):
                child = item.child(i)
                if child is None:
                    continue
                child_payload = child.data(0, USER_ROLE)
                if isinstance(child_payload, dict) and child_payload.get("kind") == "tab":
                    child_name = str(child_payload.get("name", "")).strip()
                    if child_name in self.tab_map:
                        return child_name

        for i in range(item.childCount()):
            child = item.child(i)
            if child is None:
                continue
            child_payload = child.data(0, USER_ROLE)
            if isinstance(child_payload, dict) and child_payload.get("kind") == "tab":
                child_name = str(child_payload.get("name", "")).strip()
                if child_name in self.tab_map:
                    return child_name

        if category_name == "Project" and "Project Description" in self.tab_map:
            return "Project Description"

        return ""

    def _clear_editor(self):
        while self.editor_layout.count():
            item = self.editor_layout.takeAt(0)
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

    def _render_tab(self, tab_name: str):
        self.current_tab_name = tab_name
        self.current_tab_keys = []
        self.widget_instances = {}
        self.active_instance_by_key = {}
        self._clear_editor()

        tab_title = self.tab_titles.get(tab_name, tab_name)
        self.summary_label.setText(f"<h2>{tab_title}</h2>")
        self.description_label.setText(self._linkify(self.tab_descriptions.get(tab_name, "")))

        layout_spec = self.tab_layout.get(tab_name, [])
        if not layout_spec:
            self.editor_layout.addWidget(QLabel("No settings mapped for this tab."))
            self.editor_layout.addStretch(1)
            return

        if not self._ensure_xml_loaded(silent=True):
            self.editor_layout.addWidget(QLabel("Select/load a valid Project XML first."))
            self.editor_layout.addStretch(1)
            return

        label_widgets: List[QLabel] = []

        for item in layout_spec:
            kind = str(item.get("kind", ""))

            if kind == "layout" and str(item.get("label", "")).strip() == "hl":
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setFrameShadow(QFrame.Shadow.Sunken)
                self.editor_layout.addWidget(line)
                continue

            if kind == "group":
                group_label = str(item.get("label", "")).strip()
                if group_label:
                    heading = QLabel(group_label)
                    heading.setStyleSheet("font-weight: 700;")
                    self.editor_layout.addWidget(heading)
                group_desc = str(item.get("description", "")).strip()
                if group_desc:
                    text = QLabel(self._linkify(group_desc, collapse=True))
                    text.setTextFormat(_first_qt_attr(Qt, ["TextFormat.RichText", "RichText"]))
                    text.setWordWrap(True)
                    text.setOpenExternalLinks(True)
                    self.editor_layout.addWidget(text)
                continue

            if kind not in {"field", "connected"}:
                continue

            key = str(item.get("key", "")).strip()
            if not key:
                continue
            meta = self.field_meta.get(key)
            if not meta:
                continue

            self.current_tab_keys.append(key)
            instance = self._create_widget_instance(key, meta, item)
            if key not in self.widget_instances:
                self.widget_instances[key] = []
            self.widget_instances[key].append(instance)
            if key not in self.active_instance_by_key:
                self.active_instance_by_key[key] = instance
            self._refresh_comment_button(key)

            row_widget = instance.get("row")
            if isinstance(row_widget, QWidget):
                self.editor_layout.addWidget(row_widget)

            label_widget = instance.get("label_widget")
            if isinstance(label_widget, QLabel):
                label_widgets.append(label_widget)

            value = self.pending_values.get(key, self.loaded_values.get(key, ""))
            self._set_instance_value(instance, value)

        if label_widgets:
            max_label_width = 0
            for label in label_widgets:
                cur_width = label.fontMetrics().boundingRect(label.text()).width()
                if cur_width > max_label_width:
                    max_label_width = cur_width
            for label in label_widgets:
                label.setMinimumWidth(max_label_width + 2)

        self.editor_layout.addStretch(1)
        self._set_filter_mode(self.filter_mode)
        self._update_dirty_state()

    def _create_widget_instance(self, key: str, meta: Dict[str, str], layout_item: Dict[str, str]) -> Dict[str, object]:
        input_type = str(meta.get("type", "string")).strip().lower()
        label = str(layout_item.get("label", "")).strip() or str(meta.get("label", key))
        tooltip = str(meta.get("tooltip", "")).strip()
        default_value = str(meta.get("default", ""))
        rich_tooltip = f"<FONT COLOR=black>{key}<br/>{tooltip}</FONT>"

        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setAlignment(_first_qt_attr(Qt, ["AlignmentFlag.AlignLeft", "AlignLeft"]))
        row_layout.setContentsMargins(11, 3, 11, 3)
        row_layout.setSpacing(6)

        comment_button = QToolButton()
        comment_button.setAutoRaise(True)
        comment_button.setIcon(self._comment_icon(False))
        comment_button.setToolTip("Click to edit comment")
        comment_button.clicked.connect(lambda _checked=False, k=key: self._edit_comment(k))
        row_layout.addWidget(comment_button)

        label_widget = QLabel(label)
        label_widget.setToolTip(rich_tooltip)
        row_layout.addWidget(label_widget)

        instance: Dict[str, object] = {
            "key": key,
            "type": input_type,
            "label": label,
            "parent_tab": self.key_primary_tab.get(key, self.current_tab_name),
            "row": row_widget,
            "container": row_widget,
            "label_widget": label_widget,
            "comment_button": comment_button,
        }

        if input_type == "boolean":
            control = QCheckBox()
            control.setToolTip(rich_tooltip)
            control.stateChanged.connect(lambda _state, k=key, inst=instance: self._on_instance_changed(k, inst))
            row_layout.addWidget(control)
            instance["control"] = control
            self._refresh_comment_button(key)
            return instance

        if input_type == "combo":
            control = QComboBox()
            defaults = [x.strip() for x in default_value.split(";") if x.strip()]
            for option in defaults:
                control.addItem(option)
            control.currentTextChanged.connect(lambda _text, k=key, inst=instance: self._on_instance_changed(k, inst))
            control.setToolTip(rich_tooltip)
            row_layout.addWidget(control)
            instance["control"] = control
            self._refresh_comment_button(key)
            return instance

        if input_type in {"path", "file", "directory"}:
            line = QLineEdit()
            line.setPlaceholderText(default_value)
            line.setToolTip(rich_tooltip)
            line.textChanged.connect(lambda _txt, k=key, inst=instance: self._on_instance_changed(k, inst))
            if key == "system.path.home":
                line.editingFinished.connect(self._on_home_path_edit_finished)
            browse = QToolButton()
            browse.setText("...")
            browse.clicked.connect(lambda _checked=False, t=input_type, inst=instance: self._browse_path(t, inst))
            row_layout.addWidget(browse)
            row_layout.addWidget(line)
            instance["control"] = line
            self._refresh_comment_button(key)
            return instance

        if input_type == "numeric":
            line = QLineEdit()
            line.setPlaceholderText(default_value)
            line.setToolTip(rich_tooltip)
            numeric_validator = QDoubleValidator(line)
            numeric_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
            numeric_validator.setLocale(QLocale(QLocale.Language.English))
            line.setValidator(numeric_validator)
            line.textChanged.connect(lambda _txt, k=key, inst=instance: self._on_instance_changed(k, inst))
            row_layout.addWidget(line)
            instance["control"] = line
            self._refresh_comment_button(key)
            return instance

        if input_type == "integer":
            line = QLineEdit()
            line.setPlaceholderText(default_value)
            line.setToolTip(rich_tooltip)
            int_validator = QIntValidator(line)
            int_validator.setLocale(QLocale(QLocale.Language.English))
            line.setValidator(int_validator)
            line.textChanged.connect(lambda _txt, k=key, inst=instance: self._on_instance_changed(k, inst))
            row_layout.addWidget(line)
            instance["control"] = line
            self._refresh_comment_button(key)
            return instance

        if input_type == "function":
            line = QLineEdit()
            line.setPlaceholderText(default_value)
            line.setToolTip(rich_tooltip)
            line.textChanged.connect(lambda _txt, k=key, inst=instance: self._on_instance_changed(k, inst))
            fx_button = QToolButton()
            fx_button.setText("f(x)")
            fx_button.setStyleSheet("font: italic;")
            fx_button.clicked.connect(
                lambda _checked=False, c=line: QMessageBox.information(
                    self,
                    "Function editor",
                    "Function plotter is not yet implemented in plugin; edit expression directly in the field.",
                )
            )
            row_layout.addWidget(fx_button)
            row_layout.addWidget(line)
            instance["control"] = line
            self._refresh_comment_button(key)
            return instance

        line = QLineEdit()
        line.setPlaceholderText(default_value)
        line.setToolTip(rich_tooltip)
        line.textChanged.connect(lambda _txt, k=key, inst=instance: self._on_instance_changed(k, inst))
        row_layout.addWidget(line)
        instance["control"] = line
        self._refresh_comment_button(key)
        return instance

    def _comment_icon(self, has_comment: bool) -> QIcon:
        icon_name = "note_full.png" if has_comment else "note_empty.png"
        icon_path = self.plugin_dir / "res" / icon_name
        if icon_path.exists() and icon_path.is_file():
            return QIcon(str(icon_path))
        return QIcon()

    def _refresh_comment_button(self, key: str):
        comment = self.comments.get(key, "").strip()
        has_comment = bool(comment)
        for instance in self.widget_instances.get(key, []):
            button = instance.get("comment_button")
            if isinstance(button, QToolButton):
                button.setIcon(self._comment_icon(has_comment))
                button.setToolTip(comment if has_comment else "Click to edit comment")

    def _edit_comment(self, key: str):
        current = self.comments.get(key, "")
        text, ok = QInputDialog.getMultiLineText(self, "Edit Comment", key, current)
        if not ok:
            return
        self.comments[key] = text.strip()
        self._refresh_comment_button(key)

    def _get_instance_value(self, instance: Dict[str, object]) -> str:
        control = instance.get("control")
        if isinstance(control, QCheckBox):
            return "true" if control.isChecked() else "false"
        if isinstance(control, QComboBox):
            return control.currentText().strip()
        if isinstance(control, QLineEdit):
            return control.text().strip()
        return ""

    def _set_instance_value(self, instance: Dict[str, object], value: str):
        control = instance.get("control")
        v = value.strip()
        if isinstance(control, QCheckBox):
            state = v.lower() in {"1", "true", "yes"}
            control.blockSignals(True)
            control.setChecked(state)
            control.blockSignals(False)
            return
        if isinstance(control, QComboBox):
            control.blockSignals(True)
            index = control.findText(v)
            if index < 0 and v:
                control.addItem(v)
                index = control.findText(v)
            if index >= 0:
                control.setCurrentIndex(index)
            control.blockSignals(False)
            return
        if isinstance(control, QLineEdit):
            control.blockSignals(True)
            control.setText(v)
            control.blockSignals(False)

    def _on_instance_changed(self, key: str, source_instance: Dict[str, object]):
        new_value = self._get_instance_value(source_instance)

        for instance in self.widget_instances.get(key, []):
            if instance is source_instance:
                continue
            self._set_instance_value(instance, new_value)

        base_value = self.loaded_values.get(key, "")
        if new_value == base_value:
            self.pending_values.pop(key, None)
            self.dirty_keys.discard(key)
        else:
            self.pending_values[key] = new_value
            self.dirty_keys.add(key)

        self._sync_changed_value_row(key, source_instance)
        self._update_dirty_state()

    def _ensure_changes_dialog(self):
        if self._changes_dialog is not None and self._changes_table is not None:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Changed values")
        dialog.resize(920, 420)

        layout = QVBoxLayout(dialog)
        table = QTableWidget(dialog)
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Label", "New Value", "Old Value", "Parent Tab"])

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.hide)
        close_row.addWidget(close_button)

        layout.addWidget(table)
        layout.addLayout(close_row)

        self._changes_dialog = dialog
        self._changes_table = table

    def _sync_changed_value_row(self, key: str, source_instance: Dict[str, object]):
        self._ensure_changes_dialog()
        if self._changes_table is None:
            return

        key_norm = key.replace(".connected", "")
        row_index = -1
        if key_norm in self._change_keys:
            row_index = self._change_keys.index(key_norm)

        is_changed = key in self.pending_values
        if not is_changed:
            if row_index >= 0:
                self._changes_table.removeRow(row_index)
                del self._change_keys[row_index]
            return

        old_value = self.loaded_values.get(key, "")
        new_value = self.pending_values.get(key, "")
        label = str(self.field_meta.get(key, {}).get("label", source_instance.get("label", key)))
        parent_tab = str(source_instance.get("parent_tab", self.key_primary_tab.get(key, self.current_tab_name)))
        values = [label, new_value, old_value, parent_tab]

        if row_index < 0:
            row_index = self._changes_table.rowCount()
            self._changes_table.insertRow(row_index)
            self._change_keys.append(key_norm)

        for column, value in enumerate(values):
            self._changes_table.setItem(row_index, column, QTableWidgetItem(value))

    def _on_home_path_edit_finished(self):
        home_instance = self.active_instance_by_key.get("system.path.home")
        if not home_instance:
            return
        new_home = self._get_instance_value(home_instance)
        old_home = self._home_path_last_applied
        if not new_home or new_home == old_home:
            return
        self._apply_home_path_change(old_home, new_home)
        self._home_path_last_applied = new_home

    def _apply_home_path_change(self, old_home: str, new_home: str):
        if not old_home or not new_home:
            return
        old_home_path = Path(old_home)
        new_home_path = Path(new_home)
        for key, meta in self.field_meta.items():
            if key == "system.path.home":
                continue
            input_type = str(meta.get("type", "")).lower()
            if input_type not in {"path", "file", "directory"}:
                continue
            instance = self.active_instance_by_key.get(key)
            if not instance:
                continue

            current = self._get_instance_value(instance)
            if not current:
                continue

            current_path = Path(current)
            if current_path.is_absolute():
                resolved_old = current_path
            else:
                resolved_old = (old_home_path / current_path)

            try:
                relative_to_new = resolved_old.relative_to(new_home_path)
                new_value = str(relative_to_new)
            except ValueError:
                new_value = str(resolved_old)

            self._set_instance_value(instance, new_value)
            self._on_instance_changed(key, instance)

    def _browse_path(self, input_type: str, instance: Dict[str, object]):
        control = instance.get("control")
        if not isinstance(control, QLineEdit):
            return
        start = control.text().strip() or self.current_project_file or str(self.repo_root)
        if input_type == "directory":
            selected = QFileDialog.getExistingDirectory(self, "Select directory", start)
            if selected:
                control.setText(selected)
            return
        selected, _ = QFileDialog.getOpenFileName(self, "Select file", start, "All files (*)")
        if selected:
            control.setText(selected)

    def _show_changes_dialog(self):
        if not self.pending_values:
            return
        self._ensure_changes_dialog()
        if self._changes_dialog is None or self._changes_table is None:
            return
        self._changes_table.resizeColumnsToContents()
        self._changes_dialog.show()
        if hasattr(self._changes_dialog, "raise_"):
            self._changes_dialog.raise_()
        self._changes_dialog.activateWindow()

    def _update_dirty_state(self):
        dirty = len(self.dirty_keys)
        if dirty:
            self.dirty_label.setText(f"Pending changes: {dirty}")
            self.dirty_label.setVisible(True)
        else:
            self.dirty_label.clear()
            self.dirty_label.setVisible(False)
        self.save_button.setEnabled(dirty > 0)
        self.save_as_button.setEnabled(dirty > 0 or bool(self.current_project_file))
        self.show_changes_button.setEnabled(dirty > 0)

    def _metadata_keys(self) -> List[str]:
        return list(self.field_meta.keys())

    def _clear_changes_table(self):
        self._change_keys = []
        if self._changes_table is not None:
            self._changes_table.setRowCount(0)

    def _ensure_node(self, root: ET.Element, key: str) -> ET.Element:
        node = root
        for part in [p for p in key.split(".") if p]:
            child = node.find(part)
            if child is None:
                child = ET.SubElement(node, part)
                child.text = ""
            node = child
        return node

    def _ensure_xml_loaded(self, force_reload: bool = False, silent: bool = False) -> bool:
        if not self.current_project_file:
            if not silent:
                QMessageBox.warning(self, "Settings", "Select a project XML file first.")
            self._xml_tree = None
            self._xml_path = None
            return False

        xml_path = Path(self.current_project_file)
        if not xml_path.exists() or not xml_path.is_file():
            if not silent:
                QMessageBox.warning(self, "Settings", f"Project XML not found:\n{xml_path}")
            self._xml_tree = None
            self._xml_path = None
            return False

        if (
            not force_reload
            and self._xml_tree is not None
            and self._xml_path is not None
            and self._xml_path.resolve() == xml_path.resolve()
        ):
            return True

        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            loaded: Dict[str, str] = {}
            for key in self._metadata_keys():
                node = self._ensure_node(root, key)
                loaded[key] = (node.text or "").strip()
            self._xml_tree = tree
            self._xml_path = xml_path
            self.loaded_values = loaded
            self.pending_values = {}
            self.dirty_keys.clear()
            self._clear_changes_table()
            self._home_path_last_applied = loaded.get("system.path.home", "").strip()
            self.setWindowTitle(str(xml_path))
            return True
        except (OSError, ET.ParseError, ValueError) as exc:
            self._xml_tree = None
            self._xml_path = None
            if not silent:
                QMessageBox.critical(self, "Settings", f"Could not load XML:\n{exc}")
            return False

    def _save_changes(self):
        if not self.pending_values:
            self.accept()
            return
        if not self._ensure_xml_loaded(silent=False):
            return
        if self._xml_tree is None or self._xml_path is None:
            return
        try:
            root = self._xml_tree.getroot()
            for key, value in self.pending_values.items():
                node = self._ensure_node(root, key)
                node.text = value
                self.loaded_values[key] = value
            self._xml_tree.write(self._xml_path, encoding="utf-8", xml_declaration=True)
            self.pending_values = {}
            self.dirty_keys.clear()
            self._clear_changes_table()
            self._update_dirty_state()
            self.accept()
        except (OSError, ET.ParseError, ValueError) as exc:
            QMessageBox.critical(self, "Settings", f"Could not save XML:\n{exc}")

    def _save_as(self):
        if not self._ensure_xml_loaded(silent=False):
            return
        if self._xml_tree is None:
            return

        start_path = self.current_project_file or str(self.repo_root)
        out_file, _ = QFileDialog.getSaveFileName(self, "Save new project file as", start_path, "XML files (*.xml)")
        if not out_file:
            return

        try:
            root = self._xml_tree.getroot()
            for key, value in self.pending_values.items():
                node = self._ensure_node(root, key)
                node.text = value
                self.loaded_values[key] = value
            self._xml_tree.write(out_file, encoding="utf-8", xml_declaration=True)
            self.current_project_file = out_file
            self._xml_path = Path(out_file)
            self.pending_values = {}
            self.dirty_keys.clear()
            self._clear_changes_table()
            self._update_dirty_state()
            self.accept()
        except (OSError, ET.ParseError, ValueError) as exc:
            QMessageBox.critical(self, "Settings", f"Could not save file:\n{exc}")
