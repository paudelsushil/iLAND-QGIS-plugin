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

"""Discovery helpers for mirroring iLAND desktop UI structure in QGIS plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Dict, List, Tuple
import xml.etree.ElementTree as ET


@dataclass
class DockPanelInfo:
    name: str
    title: str


@dataclass
class ToolbarActionInfo:
    name: str
    text: str


@dataclass
class SettingsCatalog:
    categories: Dict[str, List[str]] = field(default_factory=dict)
    tab_settings: Dict[str, List[str]] = field(default_factory=dict)


class ILandUICatalog:
    """Collects iLAND GUI concepts directly from source files."""

    SETTINGS_CATEGORIES = {
        "Project": [],
        "System": ["Path", "Database", "Logging", "System Settings", "Javascript"],
        "Model": [
            "World",
            "Climate",
            "Initialization",
            "Site",
            "Global Settings",
            "Seed Dispersal",
            "Soil",
            "Submodules",
            "Management",
        ],
        "Output": [
            "Vegetation state",
            "Dynamic",
            "Flows",
            "Processes",
            "Disturbance modules",
            "Forest management",
            "SVD",
        ],
        "Modules": ["Fire", "Wind", "Barkbeetle", "BITE"],
        "Other": [],
    }

    VISUALIZATION_CONTROLS = [
        "Light influence field",
        "dominance grid",
        "seed availability",
        "Regeneration",
        "individual Trees",
        "Snags",
        "resource units",
        "other grid",
        "species shares",
        "Autoscale colors",
        "Shading",
    ]

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)
        source_root = self._resolve_source_root()
        self.plugins_root = self._resolve_plugins_root()
        self.plugins_project_file = self.plugins_root / "plugins.pro"
        self.ui_file = source_root / "mainwindow.ui"

        metadata_candidates = [
            self.repo_root / "res" / "project_file_metadata.txt",
            source_root / "res" / "project_file_metadata.txt",
        ]
        metadata_file = metadata_candidates[0]
        for candidate in metadata_candidates:
            if candidate.exists() and candidate.is_file():
                metadata_file = candidate
                break
        self.metadata_file = metadata_file

    def _resolve_source_root(self) -> Path:
        direct = self.repo_root / "src" / "iland"
        if direct.exists() and direct.is_dir():
            return direct

        # Fallback: search nested source trees in workspace-like layouts.
        for marker in self.repo_root.rglob("src/iland/mainwindow.ui"):
            source_root = marker.parent
            if source_root.exists() and source_root.is_dir():
                return source_root

        return direct

    def _resolve_plugins_root(self) -> Path:
        direct = self.repo_root / "src" / "plugins"
        if direct.exists() and direct.is_dir():
            return direct

        for marker in self.repo_root.rglob("src/plugins/plugins.pro"):
            plugins_root = marker.parent
            if plugins_root.exists() and plugins_root.is_dir():
                return plugins_root

        for marker in self.repo_root.rglob("src/plugins"):
            if marker.exists() and marker.is_dir():
                return marker

        return direct

    def _format_module_display_name(self, module_name: str) -> str:
        token = module_name.strip()
        if not token:
            return ""
        parts = [part for part in re.split(r"[_\-\s]+", token) if part]
        if len(parts) <= 1:
            return token[:1].upper() + token[1:]
        return " ".join(part[:1].upper() + part[1:] for part in parts)

    def discover_disturbance_modules(self) -> List[str]:
        modules: List[str] = []

        if self.plugins_project_file.exists() and self.plugins_project_file.is_file():
            content = self.plugins_project_file.read_text(encoding="utf-8")
            for match in re.finditer(r"\bSUBDIRS\b\s*\+?=\s*([^\n]+)", content):
                rhs = match.group(1)
                for raw in rhs.replace("\\", " ").split():
                    candidate = raw.strip()
                    if not candidate or candidate.startswith("#"):
                        continue
                    module_dir = self.plugins_root / candidate
                    if module_dir.exists() and module_dir.is_dir():
                        display = self._format_module_display_name(candidate)
                        if display and display not in modules:
                            modules.append(display)

        if not modules and self.plugins_root.exists() and self.plugins_root.is_dir():
            for child in sorted(self.plugins_root.iterdir(), key=lambda p: p.name.lower()):
                if not child.is_dir():
                    continue
                display = self._format_module_display_name(child.name)
                if display and display not in modules:
                    modules.append(display)

        return modules

    def known_settings_tabs(self) -> List[str]:
        categories = {name: list(tabs) for name, tabs in self.SETTINGS_CATEGORIES.items()}
        module_tabs = categories.setdefault("Modules", [])
        for module in self.discover_disturbance_modules():
            if module not in module_tabs:
                module_tabs.append(module)

        known: List[str] = []
        for tabs in categories.values():
            known.extend(tabs)
        return known

    def discover_docks_and_toolbar(self) -> Tuple[List[DockPanelInfo], List[ToolbarActionInfo]]:
        if not self.ui_file.exists():
            return [], []

        tree = ET.parse(self.ui_file)
        root = tree.getroot()

        docks: List[DockPanelInfo] = []
        action_text: Dict[str, str] = {}
        toolbar_action_ids: List[str] = []

        for action_elem in root.findall(".//action"):
            action_name = action_elem.get("name", "")
            text = self._property_text(action_elem, "text")
            if action_name:
                action_text[action_name] = text or action_name

        for toolbar in root.findall(".//widget[@class='QToolBar']"):
            for addaction in toolbar.findall("addaction"):
                name = addaction.get("name", "")
                if name and name != "separator":
                    toolbar_action_ids.append(name)

        for dock in root.findall(".//widget[@class='QDockWidget']"):
            name = dock.get("name", "")
            title = self._property_text(dock, "windowTitle") or name
            if name:
                docks.append(DockPanelInfo(name=name, title=title))

        toolbar_actions = [
            ToolbarActionInfo(name=action_id, text=action_text.get(action_id, action_id))
            for action_id in toolbar_action_ids
        ]
        return docks, toolbar_actions

    def discover_settings_catalog(self) -> SettingsCatalog:
        categories = {name: list(tabs) for name, tabs in self.SETTINGS_CATEGORIES.items()}
        module_tabs = categories.setdefault("Modules", [])
        for module in self.discover_disturbance_modules():
            if module not in module_tabs:
                module_tabs.append(module)

        tab_settings: Dict[str, List[str]] = {}
        current_tab = "General"

        if self.metadata_file.exists():
            for raw_line in self.metadata_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith(";") or "=" not in line:
                    continue
                key, value = [part.strip() for part in line.split("=", 1)]

                if key == "gui.layout":
                    parts = [part.strip() for part in value.split("|")]
                    if len(parts) >= 3 and parts[0] == "tab":
                        current_tab = parts[2]
                        tab_settings.setdefault(current_tab, [])
                    continue

                tab_settings.setdefault(current_tab, []).append(key)

        known_tabs = {tab for tabs in categories.values() for tab in tabs}
        other_tabs = categories.setdefault("Other", [])
        for tab_name in sorted(tab_settings.keys()):
            if tab_name not in known_tabs and tab_name not in other_tabs:
                other_tabs.append(tab_name)

        return SettingsCatalog(categories=categories, tab_settings=tab_settings)

    def _property_text(self, element: ET.Element, property_name: str) -> str:
        prop = element.find(f"property[@name='{property_name}']")
        if prop is None:
            return ""
        string_node = prop.find("string")
        if string_node is None or string_node.text is None:
            return ""
        return string_node.text.strip()
