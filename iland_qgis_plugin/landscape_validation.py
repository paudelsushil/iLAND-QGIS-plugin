# /********************************************************************************************
#
# iLAND Workbench - QGIS plugin for iLAND-based ecological modeling
# Copyright (C) 2026 Sushil Paudel
#
# This plugin is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# A full copy of the license can be found in the LICENSE file.
#
# This plugin integrates iLand, an individual-based forest landscape and disturbance model.
# Copyright (C) 2009-2026 Werner Rammer, Rupert Seidl
# For more information on the original iLand model, see https://iland-model.org
# ********************************************************************************************/

"""Pre-flight landscape validation for iLand model creation.

This validator is intentionally lightweight and focused on mandatory
landscape components that must exist before Create Model is allowed.
"""

from __future__ import annotations

import csv
import re
import shlex
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


BLOCK = "BLOCK"
WARN = "WARN"
INFO = "INFO"


@dataclass
class ValidationIssue:
    """Single validation finding."""

    severity: str
    category: str
    message: str
    detail: str = ""


@dataclass
class LandscapeValidationReport:
    """Validation report with blockers and non-blocking notes."""

    issues: List[ValidationIssue] = field(default_factory=list)
    checks_run: int = 0
    checks_passed: int = 0

    @property
    def has_blockers(self) -> bool:
        return any(issue.severity == BLOCK for issue in self.issues)

    @property
    def blocker_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == BLOCK)

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == WARN)

    @property
    def info_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == INFO)

    def summary(self) -> str:
        if not self.issues:
            return f"All {self.checks_run} checks passed. Ready to create model."

        parts: List[str] = []
        if self.blocker_count:
            parts.append(f"{self.blocker_count} blocker(s)")
        if self.warning_count:
            parts.append(f"{self.warning_count} warning(s)")
        if self.info_count:
            parts.append(f"{self.info_count} info note(s)")

        status = "BLOCKED" if self.has_blockers else "PASSED with notes"
        return f"{status}: {', '.join(parts)} from {self.checks_run} checks."

    def issues_text(self, severities: Optional[Set[str]] = None) -> str:
        lines: List[str] = []
        for issue in self.issues:
            if severities is not None and issue.severity not in severities:
                continue
            lines.append(f"[{issue.category}] {issue.message}")
            if issue.detail:
                lines.append(f"  Fix: {issue.detail}")
        return "\n".join(lines)


class ILandLandscapeValidator:
    """Validate required landscape inputs before Create Model."""

    CLIMATE_REQUIRED_COLUMNS = {
        "year",
        "month",
        "day",
        "min_temp",
        "max_temp",
        "prec",
        "rad",
        "vpd",
    }

    def __init__(self, project_xml_path: str):
        self.project_xml_path = Path(project_xml_path) if project_xml_path else None
        self.report = LandscapeValidationReport()
        self._xml_root: Optional[ET.Element] = None
        self._project_dir: Optional[Path] = None
        self._home_path: Optional[Path] = None

    def validate(self) -> LandscapeValidationReport:
        self.report = LandscapeValidationReport()

        self._check_project_xml_exists()
        if self.report.has_blockers:
            return self.report

        self._parse_project_xml()
        if self.report.has_blockers:
            return self.report

        self._check_home_path()

        self._check_required_file(
            category="Spatial",
            xpath="model.world.environmentGrid",
            label="Environment grid",
            detail="Provide the 100m resource unit grid file (model.world.environmentGrid).",
        )

        stand_enabled = self._get_xml_bool("model.world.standGrid.enabled")
        if not stand_enabled:
            self._fail(
                BLOCK,
                "Spatial",
                "Stand grid is disabled (model.world.standGrid.enabled=false).",
                "Enable stand grid and provide model.world.standGrid.fileName.",
            )
        self._check_required_file(
            category="Spatial",
            xpath="model.world.standGrid.fileName",
            label="Stand grid",
            detail="Provide the 10m stand grid file (model.world.standGrid.fileName).",
        )

        env_path = self._check_required_file(
            category="Environment",
            xpath="model.world.environmentFile",
            label="Environment file",
            detail="Provide environment CSV/TXT mapping RU IDs to climate and soil properties.",
        )
        if env_path is not None:
            self._validate_environment_file(env_path)

        climate_path = self._check_required_file(
            category="Climate",
            xpath="system.database.climate",
            label="Climate database",
            detail="Provide climate SQLite database with daily weather tables.",
            base_xpath="system.path.database",
        )
        if climate_path is not None:
            self._validate_climate_database(climate_path)

        species_path = self._check_required_file(
            category="Species",
            xpath="system.database.in",
            label="Species database",
            detail="Provide species SQLite parameter database (system.database.in).",
            base_xpath="system.path.database",
        )
        if species_path is not None:
            self._validate_species_database(species_path)

        self._check_required_file(
            category="Initialization",
            xpath="model.initialization.file",
            label="Initialization file",
            detail="Provide initialization input (snapshot SQLite or init CSV).",
        )

        self._check_lip_directory()

        if env_path is not None and climate_path is not None:
            self._cross_validate_environment_vs_climate(env_path, climate_path)

        if not self._get_xml_text("model.world.DEM"):
            self._fail(
                INFO,
                "Spatial",
                "No DEM configured (model.world.DEM).",
                "Flat topography will be assumed. This is optional but recommended for terrain realism.",
            )

        return self.report

    def _add(self, severity: str, category: str, message: str, detail: str = ""):
        self.report.issues.append(ValidationIssue(severity, category, message, detail))

    def _pass(self):
        self.report.checks_run += 1
        self.report.checks_passed += 1

    def _fail(self, severity: str, category: str, message: str, detail: str = ""):
        self.report.checks_run += 1
        self._add(severity, category, message, detail)

    def _check_project_xml_exists(self):
        self.report.checks_run += 1
        if self.project_xml_path is None or not self.project_xml_path.exists():
            self._add(BLOCK, "Project", "Project XML file not found.", "Select a valid XML file in Workflow tab.")
            return
        if not self.project_xml_path.is_file():
            self._add(BLOCK, "Project", "Project XML path is not a file.", str(self.project_xml_path))
            return
        self._pass()

    def _parse_project_xml(self):
        self.report.checks_run += 1
        try:
            tree = ET.parse(self.project_xml_path)
            self._xml_root = tree.getroot()
            self._project_dir = self.project_xml_path.parent
            self._pass()
        except ET.ParseError as exc:
            self._add(BLOCK, "Project", f"Project XML is not valid XML: {exc}", "Fix XML syntax errors.")
        except OSError as exc:
            self._add(BLOCK, "Project", f"Cannot read project XML: {exc}")

    def _get_xml_text(self, xpath: str) -> str:
        if self._xml_root is None:
            return ""
        node = self._xml_root
        for part in xpath.split("."):
            child = node.find(part)
            if child is None:
                return ""
            node = child
        return (node.text or "").strip()

    def _get_xml_bool(self, xpath: str) -> bool:
        value = self._get_xml_text(xpath).lower()
        return value in {"1", "true", "yes"}

    def _check_home_path(self):
        self.report.checks_run += 1
        home_raw = self._get_xml_text("system.path.home")
        if not home_raw:
            self._home_path = self._project_dir
            self._add(
                INFO,
                "Project",
                "system.path.home is not set.",
                "Relative paths will be resolved from project file directory.",
            )
            return

        home_path = Path(home_raw)
        if not home_path.is_absolute() and self._project_dir is not None:
            home_path = (self._project_dir / home_path).resolve()

        if not home_path.exists():
            self._add(
                BLOCK,
                "Project",
                f"system.path.home directory does not exist: {home_path}",
                "Create the directory or fix system.path.home.",
            )
            return

        self._home_path = home_path
        self._pass()

    def _resolve_path(self, raw_path: str, base_xpath: str = "") -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            return path

        candidates: List[Path] = []

        if base_xpath:
            base_raw = self._get_xml_text(base_xpath)
            if base_raw:
                base_path = Path(base_raw)
                if not base_path.is_absolute():
                    if self._home_path is not None:
                        base_path = self._home_path / base_path
                    elif self._project_dir is not None:
                        base_path = self._project_dir / base_path
                candidates.append(base_path / path)

        if self._home_path is not None:
            candidates.append(self._home_path / path)
        if self._project_dir is not None:
            candidates.append(self._project_dir / path)
        candidates.append(path)

        for candidate in candidates:
            if candidate.exists():
                return candidate

        return candidates[0]

    def _check_required_file(self, category: str, xpath: str, label: str, detail: str, base_xpath: str = "") -> Optional[Path]:
        self.report.checks_run += 1
        raw_value = self._get_xml_text(xpath)
        if not raw_value:
            self._add(BLOCK, category, f"{label} path is not set ({xpath}).", detail)
            return None

        resolved = self._resolve_path(raw_value, base_xpath=base_xpath)
        if not resolved.exists() or not resolved.is_file():
            self._add(BLOCK, category, f"{label} not found: {resolved}", detail)
            return None

        self._pass()
        return resolved

    def _detect_env_delimiter(self, file_path: Path) -> Optional[str]:
        try:
            with file_path.open("r", encoding="utf-8") as handle:
                first_line = handle.readline()
        except OSError:
            return ";"
        if "\t" in first_line:
            return "\t"
        if ";" in first_line:
            return ";"
        if "," in first_line:
            return ","
        return None

    def _clean_env_token(self, token: str) -> str:
        text = (token or "").strip().lstrip("\ufeff")
        if len(text) >= 2 and ((text[0] == '"' and text[-1] == '"') or (text[0] == "'" and text[-1] == "'")):
            text = text[1:-1].strip()
        return text

    def _load_environment_rows(self, env_path: Path) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
        """Load environment file rows from delimited or whitespace-separated text."""
        with env_path.open("r", encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip() and not line.lstrip().startswith("#")]

        if not lines:
            return {}, []

        delimiter = self._detect_env_delimiter(env_path)
        if delimiter is not None:
            reader = csv.reader(lines, delimiter=delimiter, skipinitialspace=True)
            try:
                header_raw = next(reader)
            except StopIteration:
                return {}, []

            header_tokens = [self._clean_env_token(h) for h in header_raw]
            headers = {h.lower().strip(): h for h in header_tokens if h}
            rows: List[Dict[str, str]] = []

            for raw_values in reader:
                values = [self._clean_env_token(v) for v in raw_values]
                if not any(values):
                    continue
                if len(values) < len(header_tokens):
                    values.extend([""] * (len(header_tokens) - len(values)))
                elif len(values) > len(header_tokens):
                    values = values[: len(header_tokens) - 1] + [" ".join(values[len(header_tokens) - 1 :])]
                rows.append(dict(zip(header_tokens, values)))
            return headers, rows

        try:
            header_tokens = [self._clean_env_token(t) for t in shlex.split(lines[0])]
        except ValueError:
            header_tokens = [self._clean_env_token(t) for t in re.split(r"\s+", lines[0])]

        headers = {h.lower().strip(): h for h in header_tokens if h}
        rows: List[Dict[str, str]] = []

        for line in lines[1:]:
            try:
                values = [self._clean_env_token(v) for v in shlex.split(line)]
            except ValueError:
                values = [self._clean_env_token(v) for v in re.split(r"\s+", line)]
            if len(values) < len(header_tokens):
                values.extend([""] * (len(header_tokens) - len(values)))
            elif len(values) > len(header_tokens):
                values = values[: len(header_tokens) - 1] + [" ".join(values[len(header_tokens) - 1 :])]
            rows.append(dict(zip(header_tokens, values)))

        return headers, rows

    def _validate_environment_file(self, env_path: Path):
        self.report.checks_run += 1
        try:
            headers, rows = self._load_environment_rows(env_path)
            if "id" not in headers:
                self._add(
                    BLOCK,
                    "Environment",
                    "Environment file is missing 'id' column.",
                    "Add id column matching resource unit IDs in environment grid.",
                )
                return

            if not rows:
                self._add(
                    BLOCK,
                    "Environment",
                    "Environment file has no data rows.",
                    "Add one row per resource unit.",
                )
                return

            self._pass()
        except OSError as exc:
            self._add(BLOCK, "Environment", f"Cannot read environment file: {exc}")

    def _validate_climate_database(self, climate_path: Path):
        self.report.checks_run += 1
        try:
            con = sqlite3.connect(str(climate_path))
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cur.fetchall()]
            if not tables:
                self._add(
                    BLOCK,
                    "Climate",
                    "Climate database contains no tables.",
                    "Create climate tables before running Create Model.",
                )
                con.close()
                return

            cur.execute(f"PRAGMA table_info([{tables[0]}])")
            columns = {row[1].lower() for row in cur.fetchall()}
            missing = self.CLIMATE_REQUIRED_COLUMNS - columns
            if missing:
                self._add(
                    BLOCK,
                    "Climate",
                    f"Climate table '{tables[0]}' missing required columns: {sorted(missing)}",
                    "Use iLAND climate preparation tools to rebuild the database.",
                )
                con.close()
                return

            con.close()
            self._pass()
        except sqlite3.Error as exc:
            self._add(BLOCK, "Climate", f"Cannot open climate database: {exc}")

    def _validate_species_database(self, species_path: Path):
        self.report.checks_run += 1
        try:
            con = sqlite3.connect(str(species_path))
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cur.fetchall()]
            con.close()

            if not tables:
                self._add(
                    BLOCK,
                    "Species",
                    "Species database contains no tables.",
                    "Provide a valid iLAND species parameter database.",
                )
                return

            self._pass()
        except sqlite3.Error as exc:
            self._add(BLOCK, "Species", f"Cannot open species database: {exc}")

    def _check_lip_directory(self):
        self.report.checks_run += 1
        lip_raw = self._get_xml_text("system.path.lip") or "lip"
        lip_dir = self._resolve_path(lip_raw)

        if not lip_dir.exists() or not lip_dir.is_dir():
            self._add(
                BLOCK,
                "Species",
                f"LIP directory not found: {lip_dir}",
                "Set system.path.lip and provide .bin LIP files for species.",
            )
            return

        lip_files = list(lip_dir.glob("*.bin"))
        if not lip_files:
            self._add(
                BLOCK,
                "Species",
                f"No .bin LIP files found in {lip_dir}",
                "Generate or copy required LIP files before creating model.",
            )
            return

        self._pass()

    def _cross_validate_environment_vs_climate(self, env_path: Path, climate_path: Path):
        self.report.checks_run += 1
        try:
            con = sqlite3.connect(str(climate_path))
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            db_tables = {row[0] for row in cur.fetchall()}
            con.close()

            headers, rows = self._load_environment_rows(env_path)
            table_col = headers.get("model.climate.tablename") or headers.get("tablename")
            if not table_col:
                self._add(
                    WARN,
                    "Environment",
                    "No climate table column found in environment file.",
                    "Add model.climate.tableName column or configure XML defaults.",
                )
                return

            referenced = set()
            for row in rows:
                value = (row.get(table_col, "") or "").strip()
                if value:
                    referenced.add(value)

            missing = referenced - db_tables
            if missing:
                matched = referenced & db_tables
                sample = sorted(missing)[:5]
                suffix = f" (and {len(missing) - 5} more)" if len(missing) > 5 else ""
                if not matched:
                    self._add(
                        BLOCK,
                        "Climate",
                        f"Environment references missing climate table(s): {sample}{suffix}",
                        "Ensure each model.climate.tableName value exists in climate database.",
                    )
                else:
                    self._add(
                        WARN,
                        "Climate",
                        (
                            f"Environment references {len(missing)} climate table(s) missing in database; "
                            f"sample: {sample}{suffix}"
                        ),
                        (
                            "Climate table coverage is partial. Original iLAND projects may still run depending "
                            "on actual runtime table usage, but review mappings if simulation fails."
                        ),
                    )
                return

            self._pass()
        except (sqlite3.Error, OSError):
            self._add(
                WARN,
                "Climate",
                "Could not fully cross-validate environment climate table names.",
                "Check model.climate.tableName mappings manually.",
            )
