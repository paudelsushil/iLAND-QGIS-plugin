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

"""QGIS Processing provider for iLAND Workbench."""

# pyright: reportMissingImports=false

from __future__ import annotations

import json
import shlex
import urllib.request
from pathlib import Path
from typing import Dict, List

try:
    from qgis.PyQt.QtGui import QIcon  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    from PyQt6.QtGui import QIcon  # type: ignore[import-not-found]

try:
    from qgis.core import (
        QgsProcessing,
        QgsProcessingAlgorithm,
        QgsProcessingContext,
        QgsProcessingException,
        QgsProcessingFeedback,
        QgsProcessingOutputString,
        QgsProcessingParameterBoolean,
        QgsProcessingParameterFile,
        QgsProcessingParameterFileDestination,
        QgsProcessingParameterString,
        QgsProcessingProvider,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("QGIS core classes are required to load the iLAND processing provider") from exc

from .module_registry import ILandModuleRegistry, SubmoduleInfo
from .config_manager import ILandPluginConfig

from .climate_processing import (
    ILandValidateNativeClimateAlgorithm,
    ILandFutureClimateDownloadAlgorithm,
    ILandHistoricalClimateDataAlgorithm,
    ILandBuildClimateFromGeoTIFFAlgorithm,
    ILandValidateClimateNetCDFAlgorithm,
    ILandBuildClimateDatabaseAlgorithm,
)
from .disturbance_processing import ILandProcessDisturbanceHistoryAlgorithm
from .landscape_builder import (
    ILandGenerateDataTemplatesAlgorithm,
    ILandBuildLandscapeFromPlotsAlgorithm,
    ILandDownloadStandGridSourceAlgorithm,
)
from .project_setup_processing import ILandCreateProjectAlgorithm
from .soil_processing import ILandSoilDataDownloadAlgorithm


class ILandProcessingProvider(QgsProcessingProvider):
    """Processing provider exposing iLAND helper algorithms."""

    def __init__(self, repo_root: Path):
        super().__init__()
        self.repo_root = Path(repo_root)
        self._icon = self._resolve_provider_icon()

    def id(self) -> str:
        return "iland"

    def name(self) -> str:
        return "iLAND"

    def longName(self) -> str:
        return "iLAND Workbench"

    def icon(self):
        if self._icon is not None:
            return self._icon
        return super().icon()

    def _resolve_provider_icon(self):
        icon_candidates = [
            Path(__file__).resolve().parent / "res" / "icon4.png",
            Path(__file__).resolve().parent / "res" / "icon.svg",
        ]
        for icon_path in icon_candidates:
            if icon_path.exists() and icon_path.is_file():
                return QIcon(str(icon_path))
        return None

    def loadAlgorithms(self):
        self.addAlgorithm(ILandListModulesAlgorithm(self.repo_root))

        self.addAlgorithm(ILandValidateNativeClimateAlgorithm())
        self.addAlgorithm(ILandFutureClimateDownloadAlgorithm())
        self.addAlgorithm(ILandHistoricalClimateDataAlgorithm())
        self.addAlgorithm(ILandValidateClimateNetCDFAlgorithm())
        self.addAlgorithm(ILandBuildClimateDatabaseAlgorithm())
        self.addAlgorithm(ILandBuildClimateFromGeoTIFFAlgorithm())

        self.addAlgorithm(ILandProcessDisturbanceHistoryAlgorithm())

        self.addAlgorithm(ILandGenerateDataTemplatesAlgorithm())
        self.addAlgorithm(ILandDownloadStandGridSourceAlgorithm())
        self.addAlgorithm(ILandBuildLandscapeFromPlotsAlgorithm())
        self.addAlgorithm(ILandCreateProjectAlgorithm())
        self.addAlgorithm(ILandSoilDataDownloadAlgorithm())


class ILandListModulesAlgorithm(QgsProcessingAlgorithm):
    """Export discovered iLAND modules/submodules as JSON."""

    INCLUDE_FILES = "INCLUDE_FILES"
    OUTPUT_JSON = "OUTPUT_JSON"

    def __init__(self, repo_root: Path):
        super().__init__()
        self.repo_root = Path(repo_root)
        self.plugin_dir = Path(__file__).resolve().parent

    def name(self) -> str:
        return "list_modules"

    def displayName(self) -> str:
        return "List iLAND modules"

    def shortHelpString(self) -> str:
        return (
            "Scans the iLAND src tree and exports discovered modules/submodules to a JSON file. "
            "Useful for validating plugin setup in QGIS4 test environments."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.INCLUDE_FILES,
                "Include source file names",
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_JSON,
                "Output JSON",
                fileFilter="JSON files (*.json)",
            )
        )

    def processAlgorithm(
        self,
        parameters: Dict,
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict:
        include_files = self.parameterAsBool(parameters, self.INCLUDE_FILES, context)
        output_json = self.parameterAsFileOutput(parameters, self.OUTPUT_JSON, context)

        effective_repo_root = self._resolve_effective_repo_root()
        registry = ILandModuleRegistry(repo_root=effective_repo_root)
        modules = registry.discover()
        if not modules:
            raise QgsProcessingException(
                "No iLAND modules discovered. "
                f"repo_root={effective_repo_root}. "
                f"resolved_src_root={registry.src_root}. "
                "Set the iLAND repository root in plugin settings if this path is incorrect."
            )

        payload: Dict[str, object] = {
            "repo_root": str(effective_repo_root),
            "resolved_src_root": str(registry.src_root),
            "module_count": len(modules),
            "modules": [
                {
                    "name": module.name,
                    "path": module.path,
                    "files": module.files if include_files else [],
                    "submodules": self._serialize_submodules(module.submodules, include_files),
                }
                for module in modules
            ],
        }

        Path(output_json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        feedback.pushInfo(f"Discovered {len(modules)} modules. Wrote {output_json}")
        return {self.OUTPUT_JSON: output_json}

    def createInstance(self):
        return ILandListModulesAlgorithm(self.repo_root)

    def _resolve_effective_repo_root(self) -> Path:
        configured_root = ILandPluginConfig(plugin_dir=self.plugin_dir).get_repo_root()
        if configured_root.exists():
            return configured_root
        return self.repo_root

    def _serialize_submodules(self, submodules: List[SubmoduleInfo], include_files: bool) -> List[Dict[str, object]]:
        serialized: List[Dict[str, object]] = []
        for submodule in submodules:
            serialized.append(
                {
                    "name": submodule.name,
                    "path": submodule.path,
                    "files": submodule.files if include_files else [],
                    "submodules": self._serialize_submodules(submodule.children, include_files),
                }
            )
        return serialized


class ILandBuildCommandAlgorithm(QgsProcessingAlgorithm):
    """Build a command-line preview for iLAND/iLANDc execution."""

    EXECUTABLE = "EXECUTABLE"
    PROJECT_FILE = "PROJECT_FILE"
    EXTRA_ARGS = "EXTRA_ARGS"
    COMMAND = "COMMAND"

    def __init__(self, repo_root: Path):
        super().__init__()
        self.repo_root = Path(repo_root)

    def name(self) -> str:
        return "build_run_command"

    def displayName(self) -> str:
        return "Build iLAND run command"

    def shortHelpString(self) -> str:
        return (
            "Builds a shell command preview for launching iLAND or iLANDc. "
            "This algorithm does not run the model; it prepares a command string for testing."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.EXECUTABLE,
                "iLAND/iLANDc executable",
                behavior=QgsProcessingParameterFile.File,
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.PROJECT_FILE,
                "iLAND project file (optional)",
                behavior=QgsProcessingParameterFile.File,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.EXTRA_ARGS,
                "Extra command-line args",
                defaultValue="",
                optional=True,
            )
        )
        self.addOutput(QgsProcessingOutputString(self.COMMAND, "Command preview"))

    def processAlgorithm(
        self,
        parameters: Dict,
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict:
        executable = self.parameterAsFile(parameters, self.EXECUTABLE, context)
        project_file = self.parameterAsFile(parameters, self.PROJECT_FILE, context)
        extra_args = self.parameterAsString(parameters, self.EXTRA_ARGS, context).strip()

        if not executable:
            raise QgsProcessingException("Executable path is required.")

        command_parts = [executable]
        if project_file:
            command_parts.append(project_file)
        if extra_args:
            command_parts.extend(shlex.split(extra_args))

        command = " ".join(self._quote(part) for part in command_parts)
        feedback.pushInfo(f"Command preview: {command}")
        return {self.COMMAND: command}

    def createInstance(self):
        return ILandBuildCommandAlgorithm(self.repo_root)

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def _quote(self, token: str) -> str:
        if " " in token or "\t" in token:
            return f'"{token}"'
        return token


class ILandLatestReleaseAlgorithm(QgsProcessingAlgorithm):
    """Fetch latest iLAND release metadata from GitHub."""

    GITHUB_REPO = "GITHUB_REPO"
    RELEASE_INFO = "RELEASE_INFO"

    def __init__(self, repo_root: Path):
        super().__init__()
        self.repo_root = Path(repo_root)

    def name(self) -> str:
        return "latest_release_info"

    def displayName(self) -> str:
        return "Get latest iLAND release info"

    def shortHelpString(self) -> str:
        return (
            "Reads latest release metadata from GitHub API. "
            "Use this in update-only workflows where non-programmers should only update plugin/runtime artifacts."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterString(
                self.GITHUB_REPO,
                "GitHub repository (owner/repo)",
                defaultValue="edfm-tum/iland-model",
            )
        )
        self.addOutput(QgsProcessingOutputString(self.RELEASE_INFO, "Latest release JSON"))

    def processAlgorithm(
        self,
        parameters: Dict,
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict:
        repo = self.parameterAsString(parameters, self.GITHUB_REPO, context).strip()
        if not repo or "/" not in repo:
            raise QgsProcessingException("Repository must be in owner/repo format.")

        url = f"https://api.github.com/repos/{repo}/releases/latest"
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "iLAND-QGIS-Plugin"},
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # pragma: no cover
            raise QgsProcessingException(f"Could not fetch latest release metadata: {exc}") from exc

        result = {
            "repo": repo,
            "tag": payload.get("tag_name", ""),
            "name": payload.get("name", ""),
            "published_at": payload.get("published_at", ""),
            "html_url": payload.get("html_url", ""),
            "assets": [
                {
                    "name": asset.get("name", ""),
                    "size": asset.get("size", 0),
                    "download_url": asset.get("browser_download_url", ""),
                }
                for asset in payload.get("assets", [])
            ],
        }
        serialized = json.dumps(result, indent=2)
        feedback.pushInfo(f"Latest release: {result.get('tag', 'unknown')}")
        return {self.RELEASE_INFO: serialized}

    def createInstance(self):
        return ILandLatestReleaseAlgorithm(self.repo_root)
