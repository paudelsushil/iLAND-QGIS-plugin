# /********************************************************************************************
# iLAND Workbench — QGIS plugin for iLAND-based ecological modeling
# Copyright (C) 2026 Sushil Paudel
# GNU General Public License v3+
# ********************************************************************************************/

"""Shared data preparation utilities for iLand landscape construction."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np


# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------

ILAND_CLIMATE_COLUMNS = [
    "year", "month", "day",
    "min_temp",   # °C
    "max_temp",   # °C
    "prec",       # mm
    "rad",        # MJ/m²
    "vpd",        # kPa
]

ILAND_ENVIRONMENT_REQUIRED_KEYS = [
    "id",
    "model.site.availableNitrogen",
    "model.site.soilDepth",
    "model.site.pctSand",
    "model.site.pctSilt",
    "model.site.pctClay",
    "model.climate.tableName",
]

ILAND_INIT_TREE_COLUMNS = [
    "stand_id", "species", "count",
    "dbh_from", "dbh_to", "hd", "age", "density",
]

ILAND_SPECIES_CODE_PATTERN = re.compile(r"^[a-z]{4}$")

# 4-letter iLand species codes for common North American species.
# Extend as needed for your region.
KNOWN_SPECIES_CODES: Dict[str, str] = {
    "pseudotsuga menziesii": "psme",
    "douglas-fir": "psme",
    "douglas fir": "psme",
    "pinus contorta": "pico",
    "lodgepole pine": "pico",
    "picea engelmannii": "pien",
    "engelmann spruce": "pien",
    "abies lasiocarpa": "abla",
    "subalpine fir": "abla",
    "populus tremuloides": "potr",
    "quaking aspen": "potr",
    "pinus ponderosa": "pipo",
    "ponderosa pine": "pipo",
    "picea abies": "piab",
    "norway spruce": "piab",
    "fagus sylvatica": "fasy",
    "european beech": "fasy",
    "abies alba": "abal",
    "silver fir": "abal",
}


# ---------------------------------------------------------------------------
#  Validation results
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Accumulates warnings and errors from any validation pass."""

    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        parts = []
        if self.errors:
            parts.append(f"{len(self.errors)} error(s)")
        if self.warnings:
            parts.append(f"{len(self.warnings)} warning(s)")
        if self.info:
            parts.append(f"{len(self.info)} note(s)")
        return ", ".join(parts) if parts else "Validation passed."


# ---------------------------------------------------------------------------
#  Climate helpers
# ---------------------------------------------------------------------------

def detect_netcdf_variables(nc_path: Path) -> Dict[str, str]:
    """Return {standard_name_or_long_name: variable_key} from a NetCDF file.

    Requires the ``netCDF4`` library (ships with most QGIS installs).
    """
    try:
        import netCDF4 as nc  # type: ignore[import-untyped]
    except ImportError:
        raise RuntimeError(
            "netCDF4 library is required for climate data processing. "
            "Install via: pip install netCDF4"
        )

    ds = nc.Dataset(str(nc_path), "r")
    mapping: Dict[str, str] = {}
    for var_name, var_obj in ds.variables.items():
        long_name = getattr(var_obj, "long_name", "")
        standard_name = getattr(var_obj, "standard_name", "")
        label = standard_name or long_name or var_name
        mapping[label.lower()] = var_name
    ds.close()
    return mapping


# Mapping from common NetCDF variable names → iLand column names.
# Users can override via a JSON mapping file.
DEFAULT_VARIABLE_MAP: Dict[str, str] = {
    # temperature
    "tmmn": "min_temp",
    "tmin": "min_temp",
    "tasmin": "min_temp",
    "air_temperature_min": "min_temp",
    "minimum_temperature": "min_temp",
    "tmmx": "max_temp",
    "tmax": "max_temp",
    "tasmax": "max_temp",
    "air_temperature_max": "max_temp",
    "maximum_temperature": "max_temp",
    # precipitation
    "pr": "prec",
    "ppt": "prec",
    "precipitation_amount": "prec",
    "precipitation": "prec",
    # radiation
    "srad": "rad",
    "rsds": "rad",
    "surface_downwelling_shortwave_flux": "rad",
    "solar_radiation": "rad",
    # vpd
    "vpd": "vpd",
    "vapor_pressure_deficit": "vpd",
    "vpdmax": "vpd",
    "hurs": "_rh",       # relative humidity → needs conversion
    "relative_humidity": "_rh",
}


def estimate_vpd_from_temp(tmin: float, tmax: float, rh: Optional[float] = None) -> float:
    """Estimate VPD (kPa) from daily temperature.

    If relative humidity is available it is used; otherwise a dew-point
    approximation from Tmin is applied (Allen et al. 1998 FAO-56).
    """
    def saturation_vp(t: float) -> float:
        return 0.6108 * np.exp(17.27 * t / (t + 237.3))

    es = (saturation_vp(tmax) + saturation_vp(tmin)) / 2.0
    if rh is not None and 0 < rh <= 100:
        ea = es * (rh / 100.0)
    else:
        ea = saturation_vp(tmin)
    return max(0.0, es - ea)


def kelvin_to_celsius(k: float) -> float:
    return k - 273.15


def wm2_to_mjm2(w: float) -> float:
    """Convert W/m² (daily mean) to MJ/m²/day."""
    return w * 0.0864


def write_climate_sqlite(
    records: List[Dict[str, Any]],
    db_path: Path,
    table_name: str,
):
    """Write daily climate records to an iLand-compatible SQLite table."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    col_defs = ", ".join(f"{col} REAL" for col in ILAND_CLIMATE_COLUMNS)
    cur.execute(f"CREATE TABLE IF NOT EXISTS [{table_name}] ({col_defs})")
    cur.execute(f"DELETE FROM [{table_name}]")

    placeholders = ", ".join(["?"] * len(ILAND_CLIMATE_COLUMNS))
    insert_sql = f"INSERT INTO [{table_name}] VALUES ({placeholders})"
    rows = []
    for rec in records:
        rows.append(tuple(rec.get(col, 0.0) for col in ILAND_CLIMATE_COLUMNS))
    cur.executemany(insert_sql, rows)
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
#  Spatial clustering for climate
# ---------------------------------------------------------------------------

def assign_resource_units_to_climate_clusters(
    ru_centroids: List[Tuple[float, float]],
    nc_lon: np.ndarray,
    nc_lat: np.ndarray,
) -> Dict[int, Tuple[int, int]]:
    """Map each resource-unit index to the nearest NetCDF grid cell (row, col).

    Returns {ru_index: (lat_idx, lon_idx)}.
    """
    mapping: Dict[int, Tuple[int, int]] = {}
    for ru_idx, (cx, cy) in enumerate(ru_centroids):
        lat_idx = int(np.argmin(np.abs(nc_lat - cy)))
        lon_idx = int(np.argmin(np.abs(nc_lon - cx)))
        mapping[ru_idx] = (lat_idx, lon_idx)
    return mapping


# ---------------------------------------------------------------------------
#  Disturbance / vector helpers
# ---------------------------------------------------------------------------

DISTURBANCE_FIELD_ALIASES: Dict[str, List[str]] = {
    "year": ["year", "fire_year", "dist_year", "event_year", "yr"],
    "type": ["type", "dist_type", "disturbance_type", "event_type", "agent"],
    "severity": ["severity", "burn_severity", "intensity", "dnbr", "rdnbr"],
    "area_ha": ["area_ha", "area", "hectares", "size_ha", "fire_size"],
    "species_affected": ["species", "host_species", "tree_species", "spp"],
    "treatment_type": ["treatment", "treatment_type", "rx_type", "mgmt_type"],
    "stand_id": ["stand_id", "standid", "stand", "soid"],
}


def detect_field_mapping(
    field_names: List[str],
    alias_table: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, str]:
    """Guess which vector attribute fields correspond to iLand concepts.

    Returns {iland_concept: actual_field_name}.
    """
    if alias_table is None:
        alias_table = DISTURBANCE_FIELD_ALIASES

    mapping: Dict[str, str] = {}
    lower_fields = {f.lower().strip(): f for f in field_names}

    for concept, aliases in alias_table.items():
        for alias in aliases:
            if alias.lower() in lower_fields:
                mapping[concept] = lower_fields[alias.lower()]
                break
    return mapping


def validate_species_code(code: str) -> bool:
    return bool(ILAND_SPECIES_CODE_PATTERN.match(code.strip().lower()))


def normalize_species_name(raw: str) -> str:
    """Try to resolve a common/scientific name to a 4-letter iLand code."""
    key = raw.strip().lower()
    if validate_species_code(key):
        return key
    return KNOWN_SPECIES_CODES.get(key, "")


# ---------------------------------------------------------------------------
#  Plot data schema
# ---------------------------------------------------------------------------

@dataclass
class PlotDataSchema:
    """Describes expected columns for user-supplied plot-level field data."""

    # Each entry: (column_name, description, required, example)
    TREE_TABLE: List[Tuple[str, str, bool, str]] = field(default_factory=lambda: [
        ("plot_id", "Unique plot identifier matching spatial plot locations", True, "P001"),
        ("stand_id", "iLand stand grid ID this plot falls within (or mapped later)", False, "142"),
        ("species", "Species name or 4-letter iLand code", True, "psme"),
        ("dbh_cm", "Diameter at breast height in centimeters", True, "25.4"),
        ("height_m", "Total tree height in meters", False, "18.2"),
        ("trees_per_ha", "Expansion factor: stems per hectare this record represents", True, "150"),
        ("age", "Estimated tree age in years (0 if unknown)", False, "85"),
        ("status", "L=live, D=dead/snag, blank=live", False, "L"),
        ("crown_ratio", "Live crown ratio 0-1 (optional, for validation)", False, "0.45"),
        ("decay_class", "Snag decay class 1-5 (only for status=D)", False, "2"),
    ])

    REGENERATION_TABLE: List[Tuple[str, str, bool, str]] = field(default_factory=lambda: [
        ("plot_id", "Unique plot identifier", True, "P001"),
        ("species", "Species name or 4-letter iLand code", True, "abla"),
        ("height_class_m", "Midpoint of height class in meters (e.g. 0.5, 1.0, 2.0)", True, "0.5"),
        ("count_per_ha", "Seedlings/saplings per hectare in this height class", True, "2500"),
        ("age", "Estimated cohort age (0 if unknown)", False, "5"),
    ])

    FUEL_TABLE: List[Tuple[str, str, bool, str]] = field(default_factory=lambda: [
        ("plot_id", "Unique plot identifier", True, "P001"),
        ("litter_tons_ha", "Fine litter load (tonnes/ha)", False, "8.5"),
        ("duff_tons_ha", "Duff load (tonnes/ha)", False, "22.0"),
        ("cwd_tons_ha", "Coarse woody debris load (tonnes/ha)", True, "15.3"),
        ("fwd_tons_ha", "Fine woody debris 1-100hr fuels (tonnes/ha)", False, "4.2"),
        ("snag_density_ha", "Standing dead trees per hectare", False, "45"),
        ("canopy_cover_pct", "Percent canopy cover (0-100)", False, "72"),
        ("understory_cover_pct", "Lower vegetation cover percent (0-100)", False, "35"),
        ("understory_height_m", "Mean understory vegetation height (m)", False, "0.8"),
    ])

    SITE_TABLE: List[Tuple[str, str, bool, str]] = field(default_factory=lambda: [
        ("plot_id", "Unique plot identifier", True, "P001"),
        ("longitude", "Plot longitude (WGS84 decimal degrees)", True, "-110.523"),
        ("latitude", "Plot latitude (WGS84 decimal degrees)", True, "43.891"),
        ("elevation_m", "Elevation in meters above sea level", False, "2150"),
        ("slope_pct", "Slope in percent", False, "25"),
        ("aspect_deg", "Aspect in degrees from north", False, "180"),
        ("soil_depth_cm", "Effective soil depth in cm", False, "80"),
        ("pct_sand", "Soil sand percent", False, "45"),
        ("pct_silt", "Soil silt percent", False, "30"),
        ("pct_clay", "Soil clay percent", False, "25"),
        ("available_n_kg_ha", "Plant-available nitrogen (kg/ha/yr)", False, "50"),
    ])

    def generate_template_csv(self, table_name: str, output_path: Path):
        """Write an empty CSV template with headers and one example row."""
        table = getattr(self, table_name, None)
        if table is None:
            raise ValueError(f"Unknown table: {table_name}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            headers = [col[0] for col in table]
            writer.writerow(headers)
            example = [col[3] for col in table]
            writer.writerow(example)

    def describe_table(self, table_name: str) -> str:
        """Return a human-readable description of required/optional fields."""
        table = getattr(self, table_name, None)
        if table is None:
            return f"Unknown table: {table_name}"

        lines = [f"=== {table_name} ===", ""]
        for col_name, description, required, example in table:
            tag = "REQUIRED" if required else "optional"
            lines.append(f"  {col_name} ({tag}): {description}  [e.g. {example}]")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
#  Initialization file builder
# ---------------------------------------------------------------------------

def build_init_file_from_trees(
    tree_records: List[Dict[str, Any]],
    dbh_bin_width: float = 5.0,
) -> List[Dict[str, Any]]:
    """Group tree records into iLand initialization rows.

    Trees within the same stand and species are binned by DBH class.
    Returns rows matching ILAND_INIT_TREE_COLUMNS.
    """
    from collections import defaultdict

    # Group by (stand_id, species, dbh_bin)
    bins: Dict[Tuple, List[Dict]] = defaultdict(list)
    for rec in tree_records:
        species = normalize_species_name(str(rec.get("species", "")))
        if not species:
            continue
        dbh = float(rec.get("dbh_cm", 0))
        stand_id = int(rec.get("stand_id", 0))
        bin_lower = int(dbh / dbh_bin_width) * dbh_bin_width
        key = (stand_id, species, bin_lower)
        bins[key].append(rec)

    init_rows: List[Dict[str, Any]] = []
    for (stand_id, species, bin_lower), records in sorted(bins.items()):
        dbhs = [float(r.get("dbh_cm", 0)) for r in records]
        heights = [float(r.get("height_m", 0)) for r in records if float(r.get("height_m", 0)) > 0]
        counts = [float(r.get("trees_per_ha", 1)) for r in records]
        ages = [int(r.get("age", 0)) for r in records if int(r.get("age", 0)) > 0]

        mean_dbh = np.mean(dbhs) if dbhs else bin_lower + dbh_bin_width / 2
        mean_height = np.mean(heights) if heights else 0
        total_count = np.sum(counts)
        mean_age = int(np.mean(ages)) if ages else 0

        hd_ratio = (mean_height / (mean_dbh / 100.0)) if mean_dbh > 0 and mean_height > 0 else 80.0

        init_rows.append({
            "stand_id": stand_id,
            "species": species,
            "count": round(float(total_count), 1),
            "dbh_from": round(bin_lower, 1),
            "dbh_to": round(bin_lower + dbh_bin_width, 1),
            "hd": round(hd_ratio, 1),
            "age": mean_age,
            "density": 0,
        })

    return init_rows


# ---------------------------------------------------------------------------
#  Environment file builder
# ---------------------------------------------------------------------------

def build_environment_csv(
    ru_data: List[Dict[str, Any]],
    output_path: Path,
):
    """Write the iLand environment file from resource-unit records."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_keys: List[str] = []
    seen: Set[str] = set()
    for key in ILAND_ENVIRONMENT_REQUIRED_KEYS:
        if key not in seen:
            all_keys.append(key)
            seen.add(key)
    for rec in ru_data:
        for key in rec.keys():
            if key not in seen:
                all_keys.append(key)
                seen.add(key)

    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=all_keys, delimiter=";")
        writer.writeheader()
        for rec in ru_data:
            writer.writerow({k: rec.get(k, "") for k in all_keys})