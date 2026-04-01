# /********************************************************************************************
# iLAND Workbench — QGIS plugin for iLAND-based ecological modeling
# Copyright (C) 2026 Sushil Paudel
# GNU General Public License v3+
# ********************************************************************************************/

"""Processing algorithm for creating user-friendly iLAND project workspaces."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Dict, List

try:
    from qgis.core import (
        QgsProcessingAlgorithm,
        QgsProcessingContext,
        QgsProcessingException,
        QgsProcessingFeedback,
        QgsProcessingOutputString,
        QgsProcessingParameterBoolean,
        QgsProcessingParameterFile,
        QgsProcessingParameterString,
        QgsProject,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("QGIS core required") from exc


class ILandCreateProjectAlgorithm(QgsProcessingAlgorithm):
    """Create an iLAND project workspace with required folders and starter XML."""

    PROJECT_NAME = "PROJECT_NAME"
    PROJECT_LOCATION = "PROJECT_LOCATION"
    CREATE_MANDATORY_FOLDERS = "CREATE_MANDATORY_FOLDERS"
    SAVE_QGIS_PROJECT = "SAVE_QGIS_PROJECT"
    OVERWRITE_EXISTING = "OVERWRITE_EXISTING"

    OUTPUT_PROJECT_DIR = "OUTPUT_PROJECT_DIR"
    OUTPUT_PROJECT_XML = "OUTPUT_PROJECT_XML"
    OUTPUT_QGIS_PROJECT = "OUTPUT_QGIS_PROJECT"
    OUTPUT_REPORT = "OUTPUT_REPORT"

    MANDATORY_FOLDERS = [
        "abe",
        "analysis_example",
        "database",
        "gis",
        "init",
        "lip",
        "log",
        "output",
        "scripts",
        "temp",
    ]

    def name(self):
        return "create_iland_project"

    def displayName(self):
        return "Create iLAND project"

    def group(self):
        return "Data Preparation"

    def groupId(self):
        return "data_preparation"

    def shortHelpString(self):
        return (
            "Creates a new iLAND project workspace in a user-selected location. "
            "If no location is provided, the user's Documents folder is used (never plugin install folder). "
            "The algorithm creates required iLAND directories, writes a starter XML project file, "
            "and optionally saves a QGIS project with the same project name."
        )

    def initAlgorithm(self, config=None):
        del config
        self.addParameter(
            QgsProcessingParameterString(
                self.PROJECT_NAME,
                "Project name",
                defaultValue="iLAND_Project",
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.PROJECT_LOCATION,
                "Project location (optional; default = Documents)",
                behavior=QgsProcessingParameterFile.Folder,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.CREATE_MANDATORY_FOLDERS,
                "Create standard iLAND folders",
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.SAVE_QGIS_PROJECT,
                "Save QGIS project with same name",
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.OVERWRITE_EXISTING,
                "Overwrite existing XML/QGIS files if present",
                defaultValue=False,
            )
        )

        self.addOutput(QgsProcessingOutputString(self.OUTPUT_PROJECT_DIR, "Project directory"))
        self.addOutput(QgsProcessingOutputString(self.OUTPUT_PROJECT_XML, "Project XML"))
        self.addOutput(QgsProcessingOutputString(self.OUTPUT_QGIS_PROJECT, "QGIS project"))
        self.addOutput(QgsProcessingOutputString(self.OUTPUT_REPORT, "Creation report"))

    def processAlgorithm(
        self,
        parameters: Dict,
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict:
        if feedback.isCanceled():
            raise QgsProcessingException("Create iLAND project canceled by user.")

        project_name_raw = self.parameterAsString(parameters, self.PROJECT_NAME, context).strip()
        location_value = self.parameterAsFile(parameters, self.PROJECT_LOCATION, context)
        location_raw = str(location_value).strip() if location_value else ""
        create_folders = self.parameterAsBool(parameters, self.CREATE_MANDATORY_FOLDERS, context)
        save_qgis = self.parameterAsBool(parameters, self.SAVE_QGIS_PROJECT, context)
        overwrite = self.parameterAsBool(parameters, self.OVERWRITE_EXISTING, context)

        if not project_name_raw:
            raise QgsProcessingException("Project name is required.")

        project_name = self._sanitize_name(project_name_raw)
        base_dir = Path(location_raw) if location_raw else self._default_documents_dir()
        base_dir = base_dir.expanduser().resolve()
        base_dir.mkdir(parents=True, exist_ok=True)

        project_dir = base_dir / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        created_folders: List[str] = []
        if create_folders:
            for folder_name in self.MANDATORY_FOLDERS:
                if feedback.isCanceled():
                    raise QgsProcessingException("Create iLAND project canceled by user.")
                folder = project_dir / folder_name
                folder.mkdir(parents=True, exist_ok=True)
                created_folders.append(str(folder))

        xml_path = project_dir / f"{project_name}.xml"
        if xml_path.exists() and not overwrite:
            raise QgsProcessingException(
                f"Project XML already exists: {xml_path}. Enable overwrite or choose another project name."
            )
        self._write_starter_project_xml(xml_path, project_name)

        # Write a starter environment CSV so first-time users can fill it directly.
        env_file = project_dir / "init" / "environment.csv"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        if overwrite or not env_file.exists():
            env_file.write_text(
                "id;model.site.availableNitrogen;model.site.soilDepth;model.site.pctSand;"
                "model.site.pctSilt;model.site.pctClay;model.climate.tableName\n",
                encoding="utf-8",
            )

        qgis_project_path = project_dir / f"{project_name}.qgz"
        qgis_saved = False
        if save_qgis:
            try:
                project = QgsProject.instance()
                project.setTitle(project_name_raw)
                variables = dict(project.customVariables())
                variables.update(
                    {
                        "iland_project_xml": str(xml_path),
                        "iland_project_root": str(project_dir),
                    }
                )
                project.setCustomVariables(variables)
                qgis_saved = bool(project.write(str(qgis_project_path)))
            except (OSError, RuntimeError, ValueError) as exc:
                feedback.pushInfo(f"Warning: could not save QGIS project automatically: {exc}")

        report = {
            "created_at": datetime.utcnow().isoformat() + "Z",
            "project_name": project_name_raw,
            "project_directory": str(project_dir),
            "project_xml": str(xml_path),
            "qgis_project": str(qgis_project_path) if save_qgis else "",
            "qgis_project_saved": qgis_saved,
            "folders_created": created_folders,
        }

        report_path = project_dir / f"{project_name}_create_report.json"
        if feedback.isCanceled():
            raise QgsProcessingException("Create iLAND project canceled by user.")
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        feedback.pushInfo(f"Created iLAND project directory: {project_dir}")
        feedback.pushInfo(f"Project XML: {xml_path}")
        if save_qgis:
            if qgis_saved:
                feedback.pushInfo(f"QGIS project saved: {qgis_project_path}")
            else:
                feedback.pushInfo("QGIS project save requested but not confirmed by QgsProject.write().")

        return {
            self.OUTPUT_PROJECT_DIR: str(project_dir),
            self.OUTPUT_PROJECT_XML: str(xml_path),
            self.OUTPUT_QGIS_PROJECT: str(qgis_project_path) if save_qgis else "",
            self.OUTPUT_REPORT: str(report_path),
        }

    def createInstance(self):
        return ILandCreateProjectAlgorithm()

    def _sanitize_name(self, value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
        cleaned = cleaned.strip("._-")
        return cleaned or "iLAND_Project"

    def _default_documents_dir(self) -> Path:
        documents = Path.home() / "Documents"
        if documents.exists():
            return documents
        return Path.home()

    def _write_starter_project_xml(self, xml_path: Path, project_name: str):
        root = ET.Element("project")

        system = ET.SubElement(root, "system")
        path = ET.SubElement(system, "path")
        ET.SubElement(path, "home").text = str(xml_path.parent)
        ET.SubElement(path, "database").text = "database"
        ET.SubElement(path, "lip").text = "lip"
        ET.SubElement(path, "output").text = "output"
        ET.SubElement(path, "temp").text = "temp"
        ET.SubElement(path, "script").text = "scripts"
        ET.SubElement(path, "init").text = "init"
        ET.SubElement(path, "gis").text = "gis"
        ET.SubElement(path, "abe").text = "abe"
        ET.SubElement(path, "analysis_example").text = "analysis_example"
        ET.SubElement(path, "log").text = "log"

        database = ET.SubElement(system, "database")
        ET.SubElement(database, "in").text = "database/species.sqlite"
        ET.SubElement(database, "out").text = f"database/{project_name}.sqlite"
        ET.SubElement(database, "climate").text = "database/climate.sqlite"

        logging = ET.SubElement(system, "logging")
        ET.SubElement(logging, "logTarget").text = "file"
        ET.SubElement(logging, "logFile").text = "log/fatallog_$date$.txt"

        settings = ET.SubElement(system, "settings")
        ET.SubElement(settings, "logLevel").text = "Info"

        model = ET.SubElement(root, "model")
        world = ET.SubElement(model, "world")
        ET.SubElement(world, "environmentFile").text = "init/environment.csv"

        climate = ET.SubElement(model, "climate")
        ET.SubElement(climate, "tableName").text = "climate"

        output = ET.SubElement(root, "output")
        dynamic = ET.SubElement(output, "dynamic")
        ET.SubElement(dynamic, "enabled").text = "true"

        tree = ET.ElementTree(root)
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)