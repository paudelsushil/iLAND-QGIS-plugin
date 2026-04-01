# /********************************************************************************************
# iLAND Workbench — QGIS plugin for iLAND-based ecological modeling
# Copyright (C) 2026 Sushil Paudel
# GNU General Public License v3+
# ********************************************************************************************/

"""Processing algorithms for baseline landscape construction from field data."""

from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

try:
    from qgis.core import (
        QgsProcessing,
        QgsProcessingAlgorithm,
        QgsProcessingContext,
        QgsProcessingException,
        QgsProcessingFeedback,
        QgsProcessingOutputString,
        QgsProcessingParameterBoolean,
        QgsProcessingParameterCrs,
        QgsProcessingParameterEnum,
        QgsProcessingParameterExtent,
        QgsProcessingParameterFeatureSource,
        QgsProcessingParameterField,
        QgsProcessingParameterFile,
        QgsProcessingParameterFileDestination,
        QgsProcessingParameterFolderDestination,
        QgsProcessingParameterNumber,
        QgsProcessingParameterRasterLayer,
    )
except ImportError as exc:
    raise RuntimeError("QGIS core required") from exc

from .data_preparation import (
    ILAND_INIT_TREE_COLUMNS,
    PlotDataSchema,
    ValidationResult,
    build_environment_csv,
    build_init_file_from_trees,
    normalize_species_name,
    validate_species_code,
)


class ILandGenerateDataTemplatesAlgorithm(QgsProcessingAlgorithm):
    """Generate empty CSV templates for all required plot-level field data tables."""

    OUTPUT_FOLDER = "OUTPUT_FOLDER"

    def __init__(self):
        super().__init__()

    def name(self):
        return "generate_data_templates"

    def displayName(self):
        return "Generate field data CSV templates"

    def group(self):
        return "Data Preparation"

    def groupId(self):
        return "data_preparation"

    def shortHelpString(self):
        return (
            "Generates empty CSV template files with headers and one example row "
            "for each data table needed to initialize an iLand landscape from "
            "field data: TREE_TABLE, REGENERATION_TABLE, FUEL_TABLE, SITE_TABLE. "
            "Fill these templates with your plot-level data, then use "
            "'Build iLand landscape from plot data' to create iLand inputs."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER,
                "Output folder for CSV templates",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        output_dir = Path(self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))
        output_dir.mkdir(parents=True, exist_ok=True)

        schema = PlotDataSchema()
        tables = ["TREE_TABLE", "REGENERATION_TABLE", "FUEL_TABLE", "SITE_TABLE"]

        for table_name in tables:
            csv_name = f"template_{table_name.lower()}.csv"
            csv_path = output_dir / csv_name
            schema.generate_template_csv(table_name, csv_path)
            feedback.pushInfo(f"Generated: {csv_path}")

            desc = schema.describe_table(table_name)
            readme_path = output_dir / f"README_{table_name.lower()}.txt"
            readme_path.write_text(desc, encoding="utf-8")

        feedback.pushInfo(f"All templates written to {output_dir}")
        return {self.OUTPUT_FOLDER: str(output_dir)}

    def createInstance(self):
        return ILandGenerateDataTemplatesAlgorithm()


class ILandBuildLandscapeFromPlotsAlgorithm(QgsProcessingAlgorithm):
    """Build iLand initialization files from plot-level field data.

    Reads tree, regeneration, fuel, and site CSV tables and produces:
      - Tree initialization file
      - Environment file
      - Species list
      - Validation report
    """

    TREE_CSV = "TREE_CSV"
    REGEN_CSV = "REGEN_CSV"
    FUEL_CSV = "FUEL_CSV"
    SITE_CSV = "SITE_CSV"
    PLOT_LOCATIONS = "PLOT_LOCATIONS"
    STAND_GRID = "STAND_GRID"
    DBH_BIN_WIDTH = "DBH_BIN_WIDTH"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    OUTPUT_REPORT = "OUTPUT_REPORT"

    def __init__(self):
        super().__init__()

    def name(self):
        return "build_landscape_from_plots"

    def displayName(self):
        return "Build iLand landscape from plot data"

    def group(self):
        return "Data Preparation"

    def groupId(self):
        return "data_preparation"

    def shortHelpString(self):
        return (
            "Converts plot-level field data (trees, regeneration, fuels, site conditions) "
            "into iLand initialization files. Requires at minimum a tree data CSV. "
            "Plot locations are spatially joined to the stand grid to assign stand IDs. "
            "Produces: init_trees.csv, environment.csv, species_list.txt, and a report."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.TREE_CSV, "Tree data CSV (required)",
                behavior=QgsProcessingParameterFile.File,
                fileFilter="CSV files (*.csv)",
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.REGEN_CSV, "Regeneration data CSV (optional)",
                behavior=QgsProcessingParameterFile.File,
                fileFilter="CSV files (*.csv)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.FUEL_CSV, "Fuel load data CSV (optional)",
                behavior=QgsProcessingParameterFile.File,
                fileFilter="CSV files (*.csv)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.SITE_CSV, "Site/soil data CSV (optional)",
                behavior=QgsProcessingParameterFile.File,
                fileFilter="CSV files (*.csv)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.PLOT_LOCATIONS,
                "Plot location points (with plot_id field)",
                [QgsProcessing.TypeVectorPoint],
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.STAND_GRID,
                "Stand grid (10m, for plot → stand assignment)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.DBH_BIN_WIDTH,
                "DBH bin width (cm) for tree grouping",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=5.0, minValue=1.0, maxValue=20.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER, "Output folder for iLand init files",
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_REPORT, "Processing report (JSON)",
                fileFilter="JSON files (*.json)",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        if feedback.isCanceled():
            raise QgsProcessingException("Build landscape canceled by user.")

        tree_csv = Path(self.parameterAsFile(parameters, self.TREE_CSV, context))
        regen_csv_raw = self.parameterAsFile(parameters, self.REGEN_CSV, context)
        fuel_csv_raw = self.parameterAsFile(parameters, self.FUEL_CSV, context)
        site_csv_raw = self.parameterAsFile(parameters, self.SITE_CSV, context)
        dbh_bin = self.parameterAsDouble(parameters, self.DBH_BIN_WIDTH, context)
        output_dir = Path(self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))
        report_path = Path(self.parameterAsFileOutput(parameters, self.OUTPUT_REPORT, context))

        output_dir.mkdir(parents=True, exist_ok=True)
        result = ValidationResult()

        # --- Spatial plot → stand assignment ---
        plot_stand_map: Dict[str, int] = {}
        plot_source = self.parameterAsSource(parameters, self.PLOT_LOCATIONS, context)
        stand_grid = self.parameterAsRasterLayer(parameters, self.STAND_GRID, context)

        if plot_source is not None and stand_grid is not None:
            feedback.pushInfo("Assigning plots to stands via spatial join with stand grid...")
            provider = stand_grid.dataProvider()
            for feature in plot_source.getFeatures():
                if feedback.isCanceled():
                    raise QgsProcessingException("Build landscape canceled by user.")
                geom = feature.geometry()
                if geom.isNull():
                    continue
                pt = geom.asPoint()
                # Sample stand grid at plot location
                val, ok = provider.sample(pt, 1)
                if ok and val > 0:
                    plot_id = str(feature["plot_id"]) if "plot_id" in [f.name() for f in plot_source.fields()] else str(feature.id())
                    plot_stand_map[plot_id] = int(val)
            result.info.append(f"Spatially assigned {len(plot_stand_map)} plots to stands.")
            feedback.pushInfo(f"Assigned {len(plot_stand_map)} plots to stand IDs.")

        # --- Read tree data ---
        if not tree_csv.exists():
            raise QgsProcessingException(f"Tree CSV not found: {tree_csv}")

        tree_records: List[Dict[str, Any]] = []
        species_found: set = set()
        unknown_species: set = set()

        with open(tree_csv, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if feedback.isCanceled():
                    raise QgsProcessingException("Build landscape canceled by user.")
                plot_id = str(row.get("plot_id", "")).strip()
                raw_species = str(row.get("species", "")).strip()
                code = normalize_species_name(raw_species)

                if not code:
                    unknown_species.add(raw_species)
                    continue
                species_found.add(code)

                # Assign stand_id from spatial join or from CSV column
                stand_id = 0
                if plot_id in plot_stand_map:
                    stand_id = plot_stand_map[plot_id]
                elif "stand_id" in row and row["stand_id"]:
                    try:
                        stand_id = int(row["stand_id"])
                    except ValueError:
                        pass

                tree_records.append({
                    "plot_id": plot_id,
                    "stand_id": stand_id,
                    "species": code,
                    "dbh_cm": float(row.get("dbh_cm", 0) or 0),
                    "height_m": float(row.get("height_m", 0) or 0),
                    "trees_per_ha": float(row.get("trees_per_ha", 1) or 1),
                    "age": int(row.get("age", 0) or 0),
                    "status": str(row.get("status", "L")).strip().upper(),
                })

        if unknown_species:
            result.warnings.append(
                f"Could not resolve {len(unknown_species)} species names to iLand codes: "
                f"{sorted(unknown_species)}. Add them to KNOWN_SPECIES_CODES in data_preparation.py."
            )

        # Separate live trees from snags
        live_trees = [r for r in tree_records if r.get("status", "L") != "D"]
        snag_records = [r for r in tree_records if r.get("status", "L") == "D"]

        feedback.pushInfo(
            f"Read {len(tree_records)} tree records: "
            f"{len(live_trees)} live, {len(snag_records)} snags, "
            f"{len(species_found)} species."
        )

        # --- Build init file ---
        if feedback.isCanceled():
            raise QgsProcessingException("Build landscape canceled by user.")
        init_rows = build_init_file_from_trees(live_trees, dbh_bin_width=dbh_bin)
        init_path = output_dir / "init_trees.csv"
        with open(init_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=ILAND_INIT_TREE_COLUMNS)
            writer.writeheader()
            for row in init_rows:
                if feedback.isCanceled():
                    raise QgsProcessingException("Build landscape canceled by user.")
                writer.writerow(row)

        feedback.pushInfo(f"Wrote {len(init_rows)} init rows to {init_path}")

        # --- Species list ---
        species_path = output_dir / "species_list.txt"
        species_path.write_text("\n".join(sorted(species_found)), encoding="utf-8")
        feedback.pushInfo(f"Species list: {sorted(species_found)}")

        # --- Environment file from site data ---
        env_path = output_dir / "environment.csv"
        if site_csv_raw and Path(site_csv_raw).exists():
            site_records = []
            with open(site_csv_raw, "r", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    if feedback.isCanceled():
                        raise QgsProcessingException("Build landscape canceled by user.")
                    plot_id = str(row.get("plot_id", "")).strip()
                    stand_id = plot_stand_map.get(plot_id, 0)
                    if stand_id <= 0:
                        continue
                    site_records.append({
                        "id": stand_id,
                        "model.site.availableNitrogen": row.get("available_n_kg_ha", "50"),
                        "model.site.soilDepth": row.get("soil_depth_cm", "100"),
                        "model.site.pctSand": row.get("pct_sand", "40"),
                        "model.site.pctSilt": row.get("pct_silt", "35"),
                        "model.site.pctClay": row.get("pct_clay", "25"),
                        "model.climate.tableName": f"clim_{stand_id}",
                    })
            if site_records:
                build_environment_csv(site_records, env_path)
                feedback.pushInfo(f"Environment file: {env_path} ({len(site_records)} resource units)")
            else:
                result.warnings.append("Site CSV loaded but no records matched stand grid plots.")
        else:
            result.info.append("No site CSV provided. Environment file must be created manually.")

        # --- Fuel data summary (for validation, not direct iLand input) ---
        fuel_summary: Dict[str, Any] = {}
        if fuel_csv_raw and Path(fuel_csv_raw).exists():
            with open(fuel_csv_raw, "r", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                fuel_rows = list(reader)
                fuel_summary = {
                    "plot_count": len(fuel_rows),
                    "fields": list(fuel_rows[0].keys()) if fuel_rows else [],
                }
                # Fuel data is used for model evaluation, not direct initialization.
                # CWD loads can inform initial carbon pool estimates.
                cwd_values = []
                for row in fuel_rows:
                    if feedback.isCanceled():
                        raise QgsProcessingException("Build landscape canceled by user.")
                    try:
                        cwd_values.append(float(row.get("cwd_tons_ha", 0)))
                    except ValueError:
                        pass
                if cwd_values:
                    import numpy as np
                    fuel_summary["cwd_mean_tons_ha"] = round(float(np.mean(cwd_values)), 2)
                    fuel_summary["cwd_range"] = [round(min(cwd_values), 2), round(max(cwd_values), 2)]
                    result.info.append(
                        f"CWD mean: {fuel_summary['cwd_mean_tons_ha']} t/ha "
                        f"(range {fuel_summary['cwd_range']}). "
                        f"Use this to inform youngRefractoryC in environment file."
                    )

            fuel_summary_path = output_dir / "fuel_summary.json"
            fuel_summary_path.write_text(json.dumps(fuel_summary, indent=2), encoding="utf-8")

        # --- Report ---
        report = {
            "timestamp": str(Path(tree_csv).stat().st_mtime),
            "tree_records": len(tree_records),
            "live_trees": len(live_trees),
            "snags": len(snag_records),
            "init_rows": len(init_rows),
            "species": sorted(species_found),
            "unknown_species": sorted(unknown_species),
            "plots_assigned_to_stands": len(plot_stand_map),
            "fuel_summary": fuel_summary,
            "validation": {
                "is_valid": result.is_valid,
                "errors": result.errors,
                "warnings": result.warnings,
                "info": result.info,
            },
            "output_files": {
                "init_trees": str(init_path),
                "species_list": str(species_path),
                "environment": str(env_path) if env_path.exists() else None,
            },
        }

        report_path.parent.mkdir(parents=True, exist_ok=True)
        if feedback.isCanceled():
            raise QgsProcessingException("Build landscape canceled by user.")
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        return {
            self.OUTPUT_FOLDER: str(output_dir),
            self.OUTPUT_REPORT: str(report_path),
        }

    def createInstance(self):
        return ILandBuildLandscapeFromPlotsAlgorithm()


def _download_binary_with_progress(
    *,
    url: str,
    target_path: Path,
    feedback,
    label: str,
    timeout: int = 180,
    chunk_size: int = 262144,
):
    request = urllib.request.Request(url, headers={"User-Agent": "iLAND-QGIS-plugin/1.0"})
    temp_path = target_path.with_suffix(target_path.suffix + ".part")

    if temp_path.exists():
        try:
            temp_path.unlink()
        except OSError:
            pass

    feedback.pushInfo(f"Downloading {label}...")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length", "")
            total_bytes = int(content_length) if content_length.isdigit() else 0
            downloaded = 0
            started_at = time.monotonic()
            last_log_at = started_at

            with temp_path.open("wb") as handle:
                while True:
                    if feedback.isCanceled():
                        raise QgsProcessingException(f"Download canceled by user: {label}")

                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)

                    now = time.monotonic()
                    elapsed = max(0.001, now - started_at)
                    speed_mb_s = (downloaded / (1024.0 * 1024.0)) / elapsed

                    if total_bytes > 0:
                        fraction = min(1.0, downloaded / total_bytes)
                        feedback.setProgress(int(fraction * 100))
                        if now - last_log_at >= 1.0:
                            feedback.pushInfo(
                                f"{label}: {downloaded / (1024.0 * 1024.0):.2f}/"
                                f"{total_bytes / (1024.0 * 1024.0):.2f} MB "
                                f"({fraction * 100:.1f}%), {speed_mb_s:.2f} MB/s"
                            )
                            last_log_at = now
                    elif now - last_log_at >= 1.0:
                        feedback.pushInfo(
                            f"{label}: {downloaded / (1024.0 * 1024.0):.2f} MB downloaded, "
                            f"{speed_mb_s:.2f} MB/s"
                        )
                        last_log_at = now

        temp_path.replace(target_path)
        avg_speed = (downloaded / (1024.0 * 1024.0)) / max(0.001, time.monotonic() - started_at)
        feedback.setProgress(100)
        feedback.pushInfo(
            f"Download complete: {target_path.name} ({downloaded / (1024.0 * 1024.0):.2f} MB, avg {avg_speed:.2f} MB/s)"
        )
    except QgsProcessingException:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        raise
    except urllib.error.HTTPError as exc:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        raise QgsProcessingException(f"HTTP error while downloading {label}: {exc.code}") from exc
    except urllib.error.URLError as exc:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        raise QgsProcessingException(f"Network error while downloading {label}: {exc.reason}") from exc


class ILandDownloadStandGridSourceAlgorithm(QgsProcessingAlgorithm):
    """Download stand-grid source rasters (LANDFIRE default + global alternatives)."""

    DATA_SOURCE = "DATA_SOURCE"
    TIME_PERIOD = "TIME_PERIOD"
    DOWNLOAD_EXTENT = "DOWNLOAD_EXTENT"
    DOWNLOAD_EXTENT_CRS = "DOWNLOAD_EXTENT_CRS"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    DOWNLOAD_FILES = "DOWNLOAD_FILES"
    OUTPUT_MANIFEST = "OUTPUT_MANIFEST"
    DOWNLOADED_FILES = "DOWNLOADED_FILES"

    SOURCE_OPTIONS = [
        "LANDFIRE EVT (US, API)",
        "ESA WorldCover (Global)",
    ]

    TIME_OPTIONS = [
        "latest",
        "2022",
        "2021",
        "2020",
    ]

    LANDFIRE_API_BY_PERIOD = {
        "2022": "https://landfire.cr.usgs.gov/arcgis/rest/services/LF_2022/LF2022_EVT/ImageServer/exportImage",
        "2020": "https://landfire.cr.usgs.gov/arcgis/rest/services/LF_2020/LF2020_EVT/ImageServer/exportImage",
    }

    WORLDCOVER_URL_BY_PERIOD = {
        "2021": "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_Map.tif",
        "2020": "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v100/2020/map/ESA_WorldCover_10m_2020_v100_Map.tif",
    }

    def name(self):
        return "download_stand_grid_source"

    def displayName(self):
        return "Download stand-grid source data"

    def group(self):
        return "Data Preparation"

    def groupId(self):
        return "data_preparation"

    def shortHelpString(self):
        return (
            "Downloads stand-grid source rasters before running stand-grid conversion. "
            "Default source is LANDFIRE EVT (US, API). "
            "Global alternative: ESA WorldCover.\n\n"
            "For LANDFIRE API download, set an extent. The algorithm writes a manifest in all cases."
        )

    def initAlgorithm(self, config=None):
        del config
        self.addParameter(
            QgsProcessingParameterEnum(
                self.DATA_SOURCE,
                "Data source",
                options=self.SOURCE_OPTIONS,
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.TIME_PERIOD,
                "Time period",
                options=self.TIME_OPTIONS,
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterExtent(
                self.DOWNLOAD_EXTENT,
                "Download extent (required for LANDFIRE API)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterCrs(
                self.DOWNLOAD_EXTENT_CRS,
                "Extent CRS",
                defaultValue="EPSG:4326",
                optional=True,
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
            QgsProcessingParameterFileDestination(
                self.OUTPUT_MANIFEST,
                "Output manifest (JSON)",
                fileFilter="JSON (*.json)",
            )
        )
        self.addOutput(QgsProcessingOutputString(self.DOWNLOADED_FILES, "Downloaded files"))

    def processAlgorithm(self, parameters, context, feedback):
        source_index = self.parameterAsEnum(parameters, self.DATA_SOURCE, context)
        time_index = self.parameterAsEnum(parameters, self.TIME_PERIOD, context)
        period = self.TIME_OPTIONS[time_index]
        download_files = self.parameterAsBool(parameters, self.DOWNLOAD_FILES, context)
        output_folder = Path(self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))
        output_folder.mkdir(parents=True, exist_ok=True)

        extent = self.parameterAsExtent(parameters, self.DOWNLOAD_EXTENT, context)
        extent_crs = self.parameterAsCrs(parameters, self.DOWNLOAD_EXTENT_CRS, context)

        if feedback.isCanceled():
            raise QgsProcessingException("Download stand-grid source canceled by user.")

        source_name = self.SOURCE_OPTIONS[source_index]
        notes: List[str] = []
        manifest_items: List[Dict[str, Any]] = []
        downloaded_files: List[str] = []

        if source_name.startswith("LANDFIRE"):
            resolved_period = period if period in self.LANDFIRE_API_BY_PERIOD else "2022"
            if period == "latest":
                resolved_period = "2022"
            api_url = self.LANDFIRE_API_BY_PERIOD.get(resolved_period)
            if not api_url:
                raise QgsProcessingException(f"LANDFIRE period '{resolved_period}' is not configured.")

            item: Dict[str, Any] = {
                "source": source_name,
                "period": resolved_period,
                "api": api_url,
                "requires_extent": True,
            }

            has_extent = extent is not None and not extent.isEmpty()
            if has_extent:
                srid = extent_crs.postgisSrid() if extent_crs.isValid() else 4326
                params = {
                    "bbox": f"{extent.xMinimum()},{extent.yMinimum()},{extent.xMaximum()},{extent.yMaximum()}",
                    "bboxSR": srid,
                    "imageSR": srid,
                    "format": "tiff",
                    "interpolation": "RSP_NearestNeighbor",
                    "f": "image",
                }
                url = f"{api_url}?{urllib.parse.urlencode(params)}"
                item["request_url"] = url
            else:
                notes.append("LANDFIRE API download requires an extent; manifest created without download URL.")

            manifest_items.append(item)

            if download_files and has_extent:
                target = output_folder / f"landfire_evt_{resolved_period}.tif"
                _download_binary_with_progress(
                    url=item["request_url"],
                    target_path=target,
                    feedback=feedback,
                    label=target.name,
                )
                downloaded_files.append(str(target))
            elif download_files:
                notes.append("LANDFIRE file download skipped because extent was not provided.")

        else:
            resolved_period = period
            if period == "latest":
                resolved_period = "2021"
            if resolved_period == "2022":
                resolved_period = "2021"
                notes.append("ESA WorldCover has no 2022 release in this tool; using 2021.")

            url = self.WORLDCOVER_URL_BY_PERIOD.get(resolved_period)
            if not url:
                raise QgsProcessingException(f"No WorldCover URL configured for period '{resolved_period}'.")

            manifest_items.append(
                {
                    "source": source_name,
                    "period": resolved_period,
                    "url": url,
                    "scope": "global",
                }
            )

            if download_files:
                target = output_folder / f"esa_worldcover_{resolved_period}.tif"
                _download_binary_with_progress(
                    url=url,
                    target_path=target,
                    feedback=feedback,
                    label=target.name,
                )
                downloaded_files.append(str(target))

        manifest = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "source": source_name,
            "time_period_requested": period,
            "time_period_resolved": resolved_period,
            "download_files": download_files,
            "extent": (
                {
                    "xmin": extent.xMinimum(),
                    "ymin": extent.yMinimum(),
                    "xmax": extent.xMaximum(),
                    "ymax": extent.yMaximum(),
                    "crs": extent_crs.authid() if extent_crs.isValid() else "EPSG:4326",
                }
                if extent is not None and not extent.isEmpty()
                else None
            ),
            "items": manifest_items,
            "downloaded_files": downloaded_files,
            "notes": notes,
        }

        manifest_path = Path(self.parameterAsFileOutput(parameters, self.OUTPUT_MANIFEST, context))
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        manifest_copy = output_folder / "stand_grid_source_manifest.json"
        if manifest_copy.resolve() != manifest_path.resolve():
            manifest_copy.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            feedback.pushInfo(f"Manifest copy written: {manifest_copy}")

        feedback.pushInfo(f"Manifest written: {manifest_path}")
        if notes:
            for note in notes:
                feedback.pushInfo(f"Note: {note}")

        downloaded_text = "\n".join(downloaded_files)
        if not downloaded_text:
            downloaded_text = "No files downloaded. Enable download and/or provide extent (LANDFIRE API)."

        return {
            self.OUTPUT_MANIFEST: str(manifest_path),
            self.DOWNLOADED_FILES: downloaded_text,
        }

    def createInstance(self):
        return ILandDownloadStandGridSourceAlgorithm()