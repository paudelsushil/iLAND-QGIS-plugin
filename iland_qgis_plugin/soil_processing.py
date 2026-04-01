# /********************************************************************************************
# iLAND Workbench — QGIS plugin for iLAND-based ecological modeling
# Copyright (C) 2026 Sushil Paudel
# GNU General Public License v3+
# ********************************************************************************************/

"""Processing algorithm for downloading soil data (SSURGO and global options)."""

from __future__ import annotations

import csv
import json
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from qgis.core import (
        QgsProcessingAlgorithm,
        QgsProcessingContext,
        QgsProcessingException,
        QgsProcessingFeedback,
        QgsProcessingOutputString,
        QgsProcessingParameterBoolean,
        QgsProcessingParameterEnum,
        QgsProcessingParameterFile,
        QgsProcessingParameterFileDestination,
        QgsProcessingParameterFolderDestination,
        QgsProcessingParameterNumber,
        QgsProcessingParameterString,
    )
except ImportError as exc:
    raise RuntimeError("QGIS core required") from exc


class ILandSoilDataDownloadAlgorithm(QgsProcessingAlgorithm):
    """Download soil datasets with source-specific variable selection."""

    DATA_SOURCE = "DATA_SOURCE"
    SOIL_VARIABLES = "SOIL_VARIABLES"
    SOIL_DEPTHS = "SOIL_DEPTHS"
    US_STATE_FILTER = "US_STATE_FILTER"
    POINT_LON = "POINT_LON"
    POINT_LAT = "POINT_LAT"
    OUTPUT_FORMAT = "OUTPUT_FORMAT"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    DOWNLOAD_FILES = "DOWNLOAD_FILES"
    SOURCE_METADATA_XML = "SOURCE_METADATA_XML"
    OUTPUT_MANIFEST = "OUTPUT_MANIFEST"
    DOWNLOADED_FILES = "DOWNLOADED_FILES"

    SOURCE_DEFINITIONS = [
        {
            "id": "ssurgo",
            "title": "SSURGO (USDA, USA)",
            "kind": "ssurgo",
            "endpoint": "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest",
            "variables": [
                "sandtotal_r",
                "silttotal_r",
                "claytotal_r",
                "om_r",
                "ph1to1h2o_r",
                "dbthirdbar_r",
                "wfifteenbar_r",
                "awc_r",
                "ksat_r",
                "cec7_r",
            ],
        },
        {
            "id": "soilgrids",
            "title": "SoilGrids (ISRIC, Global)",
            "kind": "soilgrids",
            "endpoint": "https://rest.isric.org/soilgrids/v2.0/properties/query",
            "variables": [
                "clay",
                "sand",
                "silt",
                "phh2o",
                "soc",
                "bdod",
                "cec",
                "cfvo",
                "nitrogen",
                "ocd",
                "ocs",
            ],
        },
    ]

    SOILGRIDS_DEPTH_OPTIONS = [
        "0-5cm",
        "5-15cm",
        "15-30cm",
        "30-60cm",
        "60-100cm",
        "100-200cm",
    ]

    FORMAT_OPTIONS = ["Auto", "CSV", "JSON"]

    _VARIABLE_OPTION_MAP: Optional[List[Dict[str, str]]] = None
    _DEPTH_OPTION_MAP: Optional[List[Dict[str, str]]] = None

    def name(self):
        return "soil_data_download"

    def displayName(self):
        return "Soil Data Download"

    def group(self):
        return "Soil Data Preparation"

    def groupId(self):
        return "soil_data_preparation"

    def shortHelpString(self):
        return (
            "Downloads soil data by source with variable selection.\n\n"
            "Sources:\n"
            "- SSURGO (USDA, USA): tabular horizon/component exports via Soil Data Access API\n"
            "- SoilGrids (ISRIC, Global): point-based soil profile queries\n\n"
            "Tip: SSURGO is default. For SoilGrids, provide lon/lat.\n"
            "A manifest JSON is always written."
        )

    @classmethod
    def _build_option_maps(cls):
        var_map: List[Dict[str, str]] = []
        for source in cls.SOURCE_DEFINITIONS:
            sid = source["id"]
            title = source["title"]
            for var_name in source["variables"]:
                var_map.append(
                    {
                        "source_id": sid,
                        "name": var_name,
                        "label": f"{title}: {var_name}",
                    }
                )
        cls._VARIABLE_OPTION_MAP = var_map

        depth_map: List[Dict[str, str]] = []
        for depth in cls.SOILGRIDS_DEPTH_OPTIONS:
            depth_map.append(
                {
                    "source_id": "soilgrids",
                    "name": depth,
                    "label": f"SoilGrids: {depth}",
                }
            )
        cls._DEPTH_OPTION_MAP = depth_map

    def initAlgorithm(self, config=None):
        del config
        if self._VARIABLE_OPTION_MAP is None or self._DEPTH_OPTION_MAP is None:
            self._build_option_maps()

        source_titles = [s["title"] for s in self.SOURCE_DEFINITIONS]
        variable_options = [v["label"] for v in (self._VARIABLE_OPTION_MAP or [])]
        depth_options = ["Auto"] + [d["label"] for d in (self._DEPTH_OPTION_MAP or [])]

        self.addParameter(
            QgsProcessingParameterEnum(
                self.DATA_SOURCE,
                "Soil data source",
                options=source_titles,
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.SOIL_VARIABLES,
                "Soil variables (select source-specific entries)",
                options=variable_options,
                allowMultiple=True,
                defaultValue=[],
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.SOIL_DEPTHS,
                "Soil depth intervals (SoilGrids only)",
                options=depth_options,
                allowMultiple=True,
                defaultValue=[0],
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.US_STATE_FILTER,
                "US state filter for SSURGO (optional; e.g., TX, AR)",
                defaultValue="",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.POINT_LON,
                "Longitude for SoilGrids point query (WGS84)",
                type=QgsProcessingParameterNumber.Double,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.POINT_LAT,
                "Latitude for SoilGrids point query (WGS84)",
                type=QgsProcessingParameterNumber.Double,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.OUTPUT_FORMAT,
                "Output format",
                options=self.FORMAT_OPTIONS,
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER,
                "Output folder",
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.DOWNLOAD_FILES,
                "Download files (otherwise manifest only)",
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.SOURCE_METADATA_XML,
                "Source metadata XML (optional, e.g. SSURGO ISO 19115)",
                behavior=QgsProcessingParameterFile.File,
                fileFilter="XML files (*.xml)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_MANIFEST,
                "Output manifest (JSON)",
                fileFilter="JSON (*.json)",
            )
        )

        self.addOutput(QgsProcessingOutputString(self.DOWNLOADED_FILES, "Downloaded files"))

    def processAlgorithm(self, parameters, context: QgsProcessingContext, feedback: QgsProcessingFeedback):
        if feedback.isCanceled():
            raise QgsProcessingException("Soil Data Download canceled by user.")

        source_index = self.parameterAsEnum(parameters, self.DATA_SOURCE, context)
        source = self.SOURCE_DEFINITIONS[source_index]
        source_id = source["id"]

        output_folder = Path(self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))
        output_folder.mkdir(parents=True, exist_ok=True)

        download_files = self.parameterAsBool(parameters, self.DOWNLOAD_FILES, context)
        format_index = self.parameterAsEnum(parameters, self.OUTPUT_FORMAT, context)
        requested_format = self.FORMAT_OPTIONS[format_index].lower()

        metadata_xml_raw = self.parameterAsFile(parameters, self.SOURCE_METADATA_XML, context)
        metadata_xml = Path(metadata_xml_raw) if metadata_xml_raw else None

        selected_variable_indices = self.parameterAsEnums(parameters, self.SOIL_VARIABLES, context)
        selected_variables = self._selected_variables_for_source(source_id, selected_variable_indices)
        if not selected_variables:
            selected_variables = list(source["variables"])

        selected_depths = self._selected_depths(parameters, context)

        manifest_items: List[Dict[str, Any]] = []
        downloaded_files: List[str] = []
        notes: List[str] = []

        if metadata_xml is not None and metadata_xml.exists():
            metadata_info = self._parse_metadata_xml(metadata_xml, feedback)
            if metadata_info:
                notes.append(metadata_info)

        if not download_files:
            notes.append("Manifest-only mode: set 'Download files' to fetch outputs.")

        if source_id == "ssurgo":
            state_filter = self.parameterAsString(parameters, self.US_STATE_FILTER, context).strip().upper()
            total = max(1, len(selected_variables))
            for idx, variable in enumerate(selected_variables, start=1):
                if feedback.isCanceled():
                    raise QgsProcessingException("Soil Data Download canceled by user.")

                query = self._build_ssurgo_query(variable=variable, state_filter=state_filter)
                item = {
                    "source": source["title"],
                    "variable": variable,
                    "query_endpoint": source["endpoint"],
                    "query": query,
                    "state_filter": state_filter,
                }
                manifest_items.append(item)

                if not download_files:
                    continue

                feedback.pushInfo(f"[{idx}/{total}] Fetching SSURGO variable: {variable}")
                result_json = self._post_form_json(
                    url=source["endpoint"],
                    payload={"QUERY": query},
                    timeout=120,
                )
                rows = self._extract_sda_rows(result_json)
                feedback.pushInfo(f"[{idx}/{total}] Retrieved {len(rows)} row(s) for {variable}")

                out_path = output_folder / f"ssurgo_{variable}.csv"
                self._write_rows_csv(rows, out_path)
                downloaded_files.append(str(out_path))
                progress = int(100 * idx / total)
                feedback.setProgress(max(0, min(100, progress)))
                feedback.pushInfo(f"[{idx}/{total}] Wrote {out_path.name}")

        elif source_id == "soilgrids":
            lon = self.parameterAsDouble(parameters, self.POINT_LON, context)
            lat = self.parameterAsDouble(parameters, self.POINT_LAT, context)
            if lon is None or lat is None:
                raise QgsProcessingException("SoilGrids requires longitude and latitude inputs.")
            if lon < -180 or lon > 180 or lat < -90 or lat > 90:
                raise QgsProcessingException("Longitude/latitude values are outside valid WGS84 ranges.")

            total = max(1, len(selected_variables))
            for idx, variable in enumerate(selected_variables, start=1):
                if feedback.isCanceled():
                    raise QgsProcessingException("Soil Data Download canceled by user.")

                params = [("lon", f"{lon:.8f}"), ("lat", f"{lat:.8f}"), ("property", variable), ("value", "mean")]
                for depth in selected_depths:
                    params.append(("depth", depth))
                url = f"{source['endpoint']}?{urllib.parse.urlencode(params)}"

                item = {
                    "source": source["title"],
                    "variable": variable,
                    "query_url": url,
                    "point": {"lon": lon, "lat": lat},
                    "depths": selected_depths,
                }
                manifest_items.append(item)

                if not download_files:
                    continue

                feedback.pushInfo(f"[{idx}/{total}] Fetching SoilGrids variable: {variable}")
                payload = self._get_json(url=url, timeout=120)

                if requested_format in {"auto", "json"}:
                    out_path = output_folder / f"soilgrids_{variable}.json"
                    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                else:
                    rows = self._flatten_soilgrids_payload(payload)
                    out_path = output_folder / f"soilgrids_{variable}.csv"
                    self._write_rows_csv(rows, out_path)

                downloaded_files.append(str(out_path))
                progress = int(100 * idx / total)
                feedback.setProgress(max(0, min(100, progress)))
                feedback.pushInfo(f"[{idx}/{total}] Wrote {out_path.name}")

        manifest = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "source": source,
            "selection": {
                "variables": selected_variables,
                "depths": selected_depths,
                "download_files": download_files,
                "output_format": requested_format,
            },
            "items": manifest_items,
            "downloaded_files": downloaded_files,
            "notes": notes,
        }

        manifest_path = Path(self.parameterAsFileOutput(parameters, self.OUTPUT_MANIFEST, context))
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        manifest_copy = output_folder / "soil_data_manifest.json"
        if manifest_copy.resolve() != manifest_path.resolve():
            manifest_copy.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            feedback.pushInfo(f"Manifest copy written: {manifest_copy}")

        feedback.pushInfo(f"Manifest written: {manifest_path}")

        downloaded_text = "\n".join(downloaded_files)
        if not downloaded_text:
            downloaded_text = "No files downloaded. Enable 'Download files' to fetch soil outputs."

        return {
            self.OUTPUT_MANIFEST: str(manifest_path),
            self.DOWNLOADED_FILES: downloaded_text,
        }

    def createInstance(self):
        return ILandSoilDataDownloadAlgorithm()

    def _selected_variables_for_source(self, source_id: str, selected_indices: List[int]) -> List[str]:
        variable_map = self._VARIABLE_OPTION_MAP or []
        selected_payloads = [
            variable_map[idx]
            for idx in selected_indices
            if 0 <= idx < len(variable_map)
        ]
        return [item["name"] for item in selected_payloads if item.get("source_id") == source_id]

    def _selected_depths(self, parameters, context: QgsProcessingContext) -> List[str]:
        depth_map = self._DEPTH_OPTION_MAP or []
        selected_depth_indices = self.parameterAsEnums(parameters, self.SOIL_DEPTHS, context)
        if not selected_depth_indices:
            return ["0-5cm", "5-15cm", "15-30cm"]

        selected_depths: List[str] = []
        for idx in selected_depth_indices:
            if idx == 0:
                continue
            payload_idx = idx - 1
            if 0 <= payload_idx < len(depth_map):
                selected_depths.append(depth_map[payload_idx]["name"])

        return selected_depths or ["0-5cm", "5-15cm", "15-30cm"]

    def _build_ssurgo_query(self, variable: str, state_filter: str) -> str:
        where_clause = ""
        if state_filter:
            where_clause = f"WHERE l.areasymbol LIKE '{state_filter}%'"

        return (
            "SELECT TOP 5000 "
            "l.areasymbol, mu.mukey, co.cokey, ch.chkey, ch.hzdept_r, ch.hzdepb_r, "
            f"ch.{variable} "
            "FROM legend l "
            "INNER JOIN mapunit mu ON l.lkey = mu.lkey "
            "INNER JOIN component co ON mu.mukey = co.mukey "
            "INNER JOIN chorizon ch ON co.cokey = ch.cokey "
            f"{where_clause} "
            "ORDER BY l.areasymbol, mu.mukey, co.comppct_r DESC, ch.hzdept_r"
        )

    def _post_form_json(self, url: str, payload: Dict[str, str], timeout: int) -> Dict[str, Any]:
        body = urllib.parse.urlencode(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "User-Agent": "iLAND-QGIS-plugin/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as exc:
            raise QgsProcessingException(f"HTTP error from SSURGO API: {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise QgsProcessingException(f"Network error from SSURGO API: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise QgsProcessingException(f"Invalid JSON from SSURGO API: {exc}") from exc

    def _get_json(self, url: str, timeout: int) -> Dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": "iLAND-QGIS-plugin/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as exc:
            raise QgsProcessingException(f"HTTP error from SoilGrids API: {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise QgsProcessingException(f"Network error from SoilGrids API: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise QgsProcessingException(f"Invalid JSON from SoilGrids API: {exc}") from exc

    def _extract_sda_rows(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        table = payload.get("Table")
        if not isinstance(table, list) or not table:
            return []

        # The API often returns list[dict], but some configurations return list[list].
        if isinstance(table[0], dict):
            return [dict(item) for item in table if isinstance(item, dict)]

        return [{"value": row} for row in table]

    def _flatten_soilgrids_payload(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        properties = payload.get("properties", {})
        layers = properties.get("layers", []) if isinstance(properties, dict) else []
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            prop_name = str(layer.get("name", ""))
            unit_info = layer.get("unit_measure", {}) if isinstance(layer.get("unit_measure"), dict) else {}
            unit = str(unit_info.get("mapped_units", ""))
            depths = layer.get("depths", []) if isinstance(layer.get("depths"), list) else []
            for depth in depths:
                if not isinstance(depth, dict):
                    continue
                values = depth.get("values", {}) if isinstance(depth.get("values"), dict) else {}
                row = {
                    "property": prop_name,
                    "depth": str(depth.get("label", "")),
                    "unit": unit,
                }
                row.update({str(k): v for k, v in values.items()})
                rows.append(row)
        return rows

    def _write_rows_csv(self, rows: List[Dict[str, Any]], out_path: Path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            out_path.write_text("", encoding="utf-8")
            return

        fieldnames = sorted({key for row in rows for key in row.keys()})
        with out_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name, "") for name in fieldnames})

    def _parse_metadata_xml(self, xml_path: Path, feedback: QgsProcessingFeedback) -> str:
        try:
            root = ET.parse(xml_path).getroot()
        except (ET.ParseError, OSError):
            return ""

        local_names = set()
        for elem in root.iter():
            if not isinstance(elem.tag, str):
                continue
            if elem.tag.endswith("LocalName") and (elem.text or "").strip():
                local_names.add((elem.text or "").strip())

        if local_names:
            preview = sorted(local_names)[:8]
            feedback.pushInfo(
                f"Metadata XML parsed: {len(local_names)} potential variable names (sample: {preview})"
            )
            return f"Metadata XML parsed with {len(local_names)} potential variable names."

        return "Metadata XML parsed; no LocalName entries detected."
