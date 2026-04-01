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

"""Module discovery for iLAND source structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List

CODE_SUFFIXES = {".h", ".hpp", ".cpp", ".c", ".cxx", ".js", ".py", ".R", ".qml"}
SKIP_DIR_NAMES = {"__pycache__", ".git", ".idea", ".vscode", "build"}
SRC_HINT_DIRS = {"core", "iland", "ilandc", "output", "tools", "tests"}


@dataclass
class SubmoduleInfo:
    """Container for one submodule folder and its source files."""

    name: str
    path: str
    files: List[str] = field(default_factory=list)
    children: List["SubmoduleInfo"] = field(default_factory=list)


@dataclass
class ModuleInfo:
    """Container for one top-level iLAND module folder."""

    name: str
    path: str
    files: List[str] = field(default_factory=list)
    submodules: List[SubmoduleInfo] = field(default_factory=list)


class ILandModuleRegistry:
    """Discovers modules and submodules from the iLAND source tree."""

    def __init__(self, repo_root: Path, max_files_per_bucket: int = 300) -> None:
        self.repo_root = Path(repo_root)
        self.src_root = self._resolve_src_root()
        self.max_files_per_bucket = max_files_per_bucket

    def _resolve_src_root(self) -> Path:
        direct = self.repo_root / "src"
        if direct.exists() and direct.is_dir():
            return direct

        # Common repository wrappers used by distributions and plugin workspaces.
        wrapped_candidates = [
            self.repo_root / "iland-model-main" / "src",
            self.repo_root / "iland-model" / "src",
            self.repo_root / "iLAND" / "src",
            self.repo_root / "iLand" / "src",
        ]
        for candidate in wrapped_candidates:
            if candidate.exists() and candidate.is_dir() and self._looks_like_iland_src(candidate):
                return candidate

        # Fallback: find a nested iLAND source root by locating src/iland/mainwindow.ui.
        for marker in self.repo_root.rglob("src/iland/mainwindow.ui"):
            src_root = marker.parent.parent
            if src_root.exists() and src_root.is_dir():
                return src_root

        # QGIS4/iLAND4 snapshots may not ship UI files, so discover by structure instead.
        structural_candidates: List[Path] = []
        for marker in self.repo_root.rglob("src/iland"):
            src_root = marker.parent
            if src_root.exists() and src_root.is_dir() and self._looks_like_iland_src(src_root):
                structural_candidates.append(src_root)

        if structural_candidates:
            return self._pick_best_src_candidate(structural_candidates)

        return direct

    def _looks_like_iland_src(self, src_root: Path) -> bool:
        if not src_root.exists() or not src_root.is_dir():
            return False
        score = sum(1 for hint in SRC_HINT_DIRS if (src_root / hint).exists())
        return score >= 2

    def _pick_best_src_candidate(self, candidates: List[Path]) -> Path:
        unique_candidates = list({candidate.resolve(): candidate for candidate in candidates}.values())
        return max(
            unique_candidates,
            key=lambda candidate: (
                sum(1 for hint in SRC_HINT_DIRS if (candidate / hint).exists()),
                -len(candidate.parts),
            ),
        )

    def discover(self) -> List[ModuleInfo]:
        if not self.src_root.exists():
            return []

        modules: List[ModuleInfo] = []
        for module_dir in sorted(self._iter_module_dirs(self.src_root), key=lambda p: p.name.lower()):
            module_files = self._collect_files(module_dir)
            submodules = self._collect_submodules(module_dir)
            modules.append(
                ModuleInfo(
                    name=module_dir.name,
                    path=self._rel(module_dir),
                    files=module_files,
                    submodules=submodules,
                )
            )
        return modules

    def _iter_module_dirs(self, root: Path) -> Iterable[Path]:
        for child in root.iterdir():
            if child.is_dir() and child.name not in SKIP_DIR_NAMES:
                yield child

    def _collect_submodules(self, module_dir: Path) -> List[SubmoduleInfo]:
        submodules: List[SubmoduleInfo] = []
        for sub_dir in sorted(self._iter_module_dirs(module_dir), key=lambda p: p.name.lower()):
            submodule = self._collect_submodule_tree(sub_dir)
            if submodule is None:
                continue
            submodules.append(submodule)
        return submodules

    def _collect_submodule_tree(self, directory: Path) -> SubmoduleInfo | None:
        files = self._collect_files(directory)
        children: List[SubmoduleInfo] = []
        for sub_dir in sorted(self._iter_module_dirs(directory), key=lambda p: p.name.lower()):
            child = self._collect_submodule_tree(sub_dir)
            if child is not None:
                children.append(child)

        if not files and not children:
            return None

        return SubmoduleInfo(
            name=directory.name,
            path=self._rel(directory),
            files=files,
            children=children,
        )

    def _collect_files(self, directory: Path) -> List[str]:
        files: List[str] = []
        for path in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            if not path.is_file():
                continue
            if path.suffix not in CODE_SUFFIXES:
                continue
            files.append(path.name)
            if len(files) >= self.max_files_per_bucket:
                files.append("...")
                break
        return files

    def _rel(self, path: Path) -> str:
        return str(path.relative_to(self.repo_root)).replace("\\", "/")
