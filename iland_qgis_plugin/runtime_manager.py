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

"""Runtime manager for one-click iLAND runtime acquisition and activation."""

from __future__ import annotations

import json
import os
import re
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Optional


class ILandRuntimeManager:
    """Handles local runtime inventory and GitHub release downloads."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir) if data_dir else self._default_data_dir()
        self.runtimes_dir = self.data_dir / "runtimes"
        self.runtimes_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.runtimes_dir / "index.json"
        if not self.index_file.exists():
            self._save_index({"active_runtime": "", "runtimes": []})

    def list_runtimes(self) -> List[Dict[str, str]]:
        data = self._load_index()
        return list(data.get("runtimes", []))

    def get_active_runtime_tag(self) -> str:
        data = self._load_index()
        return str(data.get("active_runtime", ""))

    def get_active_executable(self) -> Optional[Path]:
        active_tag = self.get_active_runtime_tag()
        if not active_tag:
            return None
        for runtime in self.list_runtimes():
            if runtime.get("tag") == active_tag:
                exe = runtime.get("executable", "")
                if exe:
                    path = Path(exe)
                    if path.exists():
                        return path
        return None

    def set_active_runtime(self, tag: str) -> bool:
        data = self._load_index()
        runtimes = data.get("runtimes", [])
        if not any(rt.get("tag") == tag for rt in runtimes):
            return False
        data["active_runtime"] = tag
        self._save_index(data)
        return True

    def register_local_runtime(
        self,
        executable: Path,
        tag: Optional[str] = None,
        activate: bool = True,
    ) -> Dict[str, str]:
        exe = Path(executable).expanduser().resolve()
        if not exe.exists() or not exe.is_file():
            raise RuntimeError(f"Runtime executable not found: {exe}")

        runtime_tag = (tag or f"local-{exe.stem}").strip() or "local-runtime"
        runtime_info = {
            "tag": runtime_tag,
            "asset_name": "local-manual",
            "install_dir": str(exe.parent),
            "executable": str(exe),
        }
        self._upsert_runtime(runtime_info)
        if activate:
            self.set_active_runtime(runtime_tag)
        return runtime_info

    def fetch_latest_release(self, repo: str = "edfm-tum/iland-model") -> Dict[str, object]:
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "iLAND-QGIS-Plugin"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def fetch_releases(self, repo: str = "edfm-tum/iland-model", per_page: int = 10) -> List[Dict[str, object]]:
        url = f"https://api.github.com/repos/{repo}/releases?per_page={per_page}"
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "iLAND-QGIS-Plugin"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, list) else []

    def install_latest_windows_runtime(self, repo: str = "edfm-tum/iland-model") -> Dict[str, str]:
        release_candidates: List[Dict[str, object]] = []

        latest = self.fetch_latest_release(repo)
        if isinstance(latest, dict):
            release_candidates.append(latest)

        for rel in self.fetch_releases(repo=repo, per_page=10):
            if not isinstance(rel, dict):
                continue
            tag = str(rel.get("tag_name", ""))
            if any(str(existing.get("tag_name", "")) == tag for existing in release_candidates):
                continue
            release_candidates.append(rel)

        release: Optional[Dict[str, object]] = None
        asset: Optional[Dict[str, object]] = None
        for candidate in release_candidates:
            chosen = self._choose_windows_asset(candidate)
            if chosen is not None:
                release = candidate
                asset = chosen
                break

        if asset is None or release is None:
            checked_tags = [str(r.get("tag_name", "?")) for r in release_candidates]
            raise RuntimeError(
                "No Windows runtime asset found in recent releases. "
                f"Checked tags: {', '.join(checked_tags) if checked_tags else 'none'}."
            )

        tag = str(release.get("tag_name", "latest"))

        tag_safe = self._safe_name(tag)
        runtime_dir = self.runtimes_dir / tag_safe
        runtime_dir.mkdir(parents=True, exist_ok=True)

        asset_name = str(asset.get("name", "runtime.zip"))
        asset_url = str(asset.get("browser_download_url", ""))
        if not asset_url:
            raise RuntimeError("Selected release asset has no download URL.")

        downloaded_file = runtime_dir / asset_name
        self._download_file(asset_url, downloaded_file)

        if downloaded_file.suffix.lower() == ".zip":
            with zipfile.ZipFile(downloaded_file, "r") as archive:
                archive.extractall(runtime_dir)

        executable = self._find_executable(runtime_dir)
        if executable is None:
            found_exes = [str(path.name) for path in runtime_dir.rglob("*.exe")]
            raise RuntimeError(
                "Downloaded runtime does not contain iLANDc.exe. "
                f"Asset: {asset_name}. Found executables: {', '.join(found_exes) if found_exes else 'none'}."
            )

        runtime_info = {
            "tag": tag,
            "asset_name": asset_name,
            "install_dir": str(runtime_dir),
            "executable": str(executable),
        }

        self._upsert_runtime(runtime_info)
        if not self.get_active_runtime_tag():
            self.set_active_runtime(tag)

        return runtime_info

    def _choose_windows_asset(self, release_payload: Dict[str, object]) -> Optional[Dict[str, object]]:
        assets = list(release_payload.get("assets", []))
        if not assets:
            return None

        def score(asset: Dict[str, object]) -> int:
            name = str(asset.get("name", "")).lower()
            value = 0

            is_windows_named = "win" in name or "windows" in name
            if is_windows_named:
                value += 40

            if "ilandc" in name or "console" in name or "cli" in name:
                value += 8
            if "iland" in name:
                value += 2
            if name.endswith(".zip"):
                value += 10
            if name.endswith(".exe"):
                value += 12
            if "src" in name or "source" in name:
                value -= 5
            if "setup" in name or "installer" in name:
                value -= 2
            if name.endswith(".dmg") or name.endswith(".appimage"):
                value -= 10
            if ".tar" in name or name.endswith(".gz") or name.endswith(".bz2") or name.endswith(".xz"):
                value -= 8

            # Bare files (no extension) are often non-Windows artifacts in mixed release pages.
            if "." not in Path(name).name:
                value -= 12

            # On Windows, strongly deprioritize assets that are not clearly Windows-labeled.
            if os.name == "nt" and not is_windows_named:
                value -= 25
            return value

        ranked = sorted(assets, key=score, reverse=True)
        best = ranked[0]
        return best if score(best) > 0 else None

    def _find_executable(self, root: Path) -> Optional[Path]:
        candidates = list(root.rglob("*.exe"))
        if not candidates:
            return None

        def rank(path: Path) -> int:
            name = path.name.lower()
            score = 0
            if "ilandc" in name:
                score += 100
            if name == "iland.exe":
                score -= 50
            if "iland" in name:
                score += 3
            if "test" in name:
                score -= 3
            return score

        ranked = sorted(candidates, key=rank, reverse=True)
        best = ranked[0]
        return best if "ilandc" in best.name.lower() else None

    def _upsert_runtime(self, runtime_info: Dict[str, str]):
        data = self._load_index()
        runtimes = list(data.get("runtimes", []))
        runtimes = [rt for rt in runtimes if rt.get("tag") != runtime_info.get("tag")]
        runtimes.append(runtime_info)
        data["runtimes"] = runtimes
        self._save_index(data)

    def _download_file(self, url: str, destination: Path):
        destination.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "iLAND-QGIS-Plugin"})
        with urllib.request.urlopen(request, timeout=120) as response:
            destination.write_bytes(response.read())

    def _load_index(self) -> Dict[str, object]:
        try:
            return json.loads(self.index_file.read_text(encoding="utf-8"))
        except Exception:
            return {"active_runtime": "", "runtimes": []}

    def _save_index(self, payload: Dict[str, object]):
        self.index_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _safe_name(self, value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", value)
        return cleaned or "runtime"

    def _default_data_dir(self) -> Path:
        if os.name == "nt":
            base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
            if base:
                return Path(base) / "iLANDWorkbenchQGIS"
        return Path.home() / ".local" / "share" / "iLANDWorkbenchQGIS"
