"""Module discovery for iLAND source structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List

CODE_SUFFIXES = {".h", ".hpp", ".cpp", ".c", ".cxx", ".js", ".py", ".R", ".qml"}
SKIP_DIR_NAMES = {"__pycache__", ".git", ".idea", ".vscode", "build"}


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
        self.src_root = self.repo_root / "src"
        self.max_files_per_bucket = max_files_per_bucket

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
