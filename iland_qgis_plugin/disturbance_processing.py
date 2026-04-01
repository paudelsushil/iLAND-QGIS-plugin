"""Processing algorithms for disturbance history and fuel management data."""

from __future__ import annotations

import csv
import json
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
        QgsProcessingParameterEnum,
        QgsProcessingParameterFeatureSource,
        QgsProcessingParameterField,
        QgsProcessingParameterFileDestination,
        QgsProcessingParameterRasterLayer,
        QgsProcessingParameterString,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("QGIS core required") from exc

from .data_preparation import ValidationResult, detect_field_mapping


class ILandProcessDisturbanceHistoryAlgorithm(QgsProcessingAlgorithm):
    """Convert disturbance vector data to iLand-ready event inputs."""

    INPUT_LAYER = "INPUT_LAYER"
    DISTURBANCE_TYPE = "DISTURBANCE_TYPE"
    YEAR_FIELD = "YEAR_FIELD"
    SEVERITY_FIELD = "SEVERITY_FIELD"
    STAND_GRID = "STAND_GRID"
    OUTPUT_TIME_EVENTS = "OUTPUT_TIME_EVENTS"
    OUTPUT_REPORT = "OUTPUT_REPORT"

    DIST_TYPES = ["wildfire", "bark_beetle", "fuel_treatment", "wind", "auto_detect"]

    def name(self):
        return "process_disturbance_history"

    def displayName(self):
        return "Process disturbance history for iLand"

    def group(self):
        return "Data Preparation"

    def groupId(self):
        return "data_preparation"

    def shortHelpString(self):
        return (
            "Converts disturbance vector layers into iLand-compatible event inputs. "
            "Field mapping is auto-detected with optional manual overrides."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_LAYER,
                "Disturbance history vector layer",
                [QgsProcessing.TypeVectorAnyGeometry],
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.DISTURBANCE_TYPE,
                "Disturbance type",
                options=self.DIST_TYPES,
                defaultValue=4,
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.YEAR_FIELD,
                "Year field (optional override)",
                parentLayerParameterName=self.INPUT_LAYER,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.SEVERITY_FIELD,
                "Severity field (optional override)",
                parentLayerParameterName=self.INPUT_LAYER,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.STAND_GRID,
                "Stand grid for spatial assignment (optional)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_TIME_EVENTS,
                "Output time events file",
                fileFilter="CSV files (*.csv)",
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_REPORT,
                "Processing report (JSON)",
                fileFilter="JSON files (*.json)",
            )
        )

    def processAlgorithm(
        self,
        parameters: Dict,
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict:
        source = self.parameterAsSource(parameters, self.INPUT_LAYER, context)
        dist_type = self.DIST_TYPES[self.parameterAsEnum(parameters, self.DISTURBANCE_TYPE, context)]
        year_override = self.parameterAsString(parameters, self.YEAR_FIELD, context).strip()
        severity_override = self.parameterAsString(parameters, self.SEVERITY_FIELD, context).strip()
        output_events = Path(self.parameterAsFileOutput(parameters, self.OUTPUT_TIME_EVENTS, context))
        output_report = Path(self.parameterAsFileOutput(parameters, self.OUTPUT_REPORT, context))

        if source is None:
            raise QgsProcessingException("Input layer is required.")

        result = ValidationResult()
        field_names = [f.name() for f in source.fields()]
        mapping = detect_field_mapping(field_names)
        year_field = year_override or mapping.get("year", "")
        severity_field = severity_override or mapping.get("severity", "")
        area_field = mapping.get("area_ha", "")
        stand_field = mapping.get("stand_id", "")
        type_field = mapping.get("type", "")

        if dist_type == "auto_detect":
            dist_type = "mixed" if type_field else "wildfire"

        if not year_field:
            result.errors.append("No year field detected. Set the year-field override.")
        elif year_field not in field_names:
            result.errors.append(f"Year field '{year_field}' does not exist in input layer.")

        if result.errors:
            raise QgsProcessingException("; ".join(result.errors))

        events: List[Dict[str, Any]] = []
        for feature in source.getFeatures():
            if feedback.isCanceled():
                raise QgsProcessingException("Disturbance processing canceled by user.")

            try:
                year_value = int(feature[year_field])
            except (TypeError, ValueError):
                result.warnings.append(f"Feature {feature.id()}: invalid year value skipped")
                continue

            event: Dict[str, Any] = {
                "year": year_value,
                "type": dist_type,
            }

            if type_field and feature[type_field] not in (None, ""):
                event["type"] = str(feature[type_field]).strip().lower()

            if severity_field and severity_field in field_names:
                try:
                    event["severity"] = float(feature[severity_field])
                except (TypeError, ValueError):
                    pass

            if area_field and area_field in field_names:
                try:
                    event["area_ha"] = float(feature[area_field])
                except (TypeError, ValueError):
                    pass

            if stand_field and stand_field in field_names:
                try:
                    event["stand_id"] = int(feature[stand_field])
                except (TypeError, ValueError):
                    pass

            geom = feature.geometry()
            if geom and not geom.isNull():
                centroid = geom.centroid().asPoint()
                event["x"] = round(centroid.x(), 2)
                event["y"] = round(centroid.y(), 2)
                if "area_ha" not in event:
                    try:
                        event["area_ha"] = round(geom.area() / 10000.0, 4)
                    except Exception:
                        pass

            events.append(event)

        output_events.parent.mkdir(parents=True, exist_ok=True)
        event_columns = ["year", "type", "severity", "area_ha", "stand_id", "x", "y"]
        with output_events.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=event_columns)
            writer.writeheader()
            for event in events:
                writer.writerow({k: event.get(k, "") for k in event_columns})

        report_payload = {
            "created_utc": datetime.utcnow().isoformat() + "Z",
            "input_feature_count": source.featureCount(),
            "valid_event_count": len(events),
            "field_mapping": {
                "year": year_field,
                "severity": severity_field,
                "area_ha": area_field,
                "stand_id": stand_field,
                "type": type_field,
            },
            "warnings": result.warnings,
            "notes": result.info,
        }
        output_report.parent.mkdir(parents=True, exist_ok=True)
        output_report.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

        feedback.pushInfo(f"Wrote {len(events)} events to {output_events}")
        feedback.pushInfo(f"Wrote report to {output_report}")
        return {
            self.OUTPUT_TIME_EVENTS: str(output_events),
            self.OUTPUT_REPORT: str(output_report),
        }

    def createInstance(self):
        return ILandProcessDisturbanceHistoryAlgorithm()


