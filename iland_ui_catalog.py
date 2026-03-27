"""Discovery helpers for mirroring iLAND desktop UI structure in QGIS plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
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
        self.ui_file = self.repo_root / "src" / "iland" / "mainwindow.ui"
        self.metadata_file = self.repo_root / "src" / "iland" / "res" / "project_file_metadata.txt"

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

        return SettingsCatalog(categories=dict(self.SETTINGS_CATEGORIES), tab_settings=tab_settings)

    def _property_text(self, element: ET.Element, property_name: str) -> str:
        prop = element.find(f"property[@name='{property_name}']")
        if prop is None:
            return ""
        string_node = prop.find("string")
        if string_node is None or string_node.text is None:
            return ""
        return string_node.text.strip()
