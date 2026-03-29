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

"""Persistent plugin configuration for paths and repository settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional


class ILandPluginConfig:
    """Stores lightweight plugin settings outside the plugin source folder."""

    def __init__(self, plugin_dir: Path):
        self.plugin_dir = Path(plugin_dir)
        self.data_dir = self._default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.data_dir / "config.json"

    def get_repo_root(self) -> Path:
        default_repo = self.plugin_dir.parent
        data = self._load()
        configured = str(data.get("iland_repo_root", "")).strip()
        if configured:
            candidate = Path(configured)
            if candidate.exists():
                return candidate
        return default_repo

    def set_repo_root(self, repo_root: Path):
        data = self._load()
        data["iland_repo_root"] = str(Path(repo_root).resolve())
        self._save(data)

    def get_github_repo(self) -> str:
        data = self._load()
        value = str(data.get("github_repo", "")).strip()
        return value or "edfm-tum/iland-model"

    def set_github_repo(self, repo: str):
        data = self._load()
        data["github_repo"] = repo.strip() or "edfm-tum/iland-model"
        self._save(data)

    def get_value(self, key: str, default=None):
        data = self._load()
        return data.get(key, default)

    def set_value(self, key: str, value):
        data = self._load()
        data[key] = value
        self._save(data)

    def get_string(self, key: str, default: str = "") -> str:
        value = self.get_value(key, default)
        return str(value) if value is not None else default

    def set_string(self, key: str, value: Optional[str]):
        self.set_value(key, value or "")

    def _default_data_dir(self) -> Path:
        if os.name == "nt":
            base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
            if base:
                return Path(base) / "iLANDWorkbenchQGIS"
        return Path.home() / ".local" / "share" / "iLANDWorkbenchQGIS"

    def _load(self) -> Dict[str, object]:
        if not self.config_file.exists():
            return {}
        try:
            return json.loads(self.config_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, payload: Dict[str, object]):
        self.config_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
