"""
Preprocessor: parses Apple Health export.xml once and saves Parquet files.
Run this script whenever you export new data from Apple Health.

Usage:
    python preprocess.py
    python preprocess.py --export /path/to/exportación.xml
"""

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

from lxml import etree
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_EXPORT = Path(__file__).parent.parent / "apple_health_export" / "exportación.xml"
OUTPUT_DIR = Path(__file__).parent / "data"

# HK types we care about → short filename
TYPE_MAP = {
    "HKQuantityTypeIdentifierStepCount":                "steps",
    "HKQuantityTypeIdentifierHeartRate":                "heart_rate",
    "HKQuantityTypeIdentifierRestingHeartRate":         "resting_hr",
    "HKQuantityTypeIdentifierActiveEnergyBurned":       "active_energy",
    "HKQuantityTypeIdentifierBasalEnergyBurned":        "basal_energy",
    "HKQuantityTypeIdentifierDistanceWalkingRunning":   "distance_walk",
    "HKQuantityTypeIdentifierDistanceCycling":          "distance_cycling",
    "HKQuantityTypeIdentifierFlightsClimbed":           "flights_climbed",
    "HKCategoryTypeIdentifierSleepAnalysis":            "sleep",
    "HKQuantityTypeIdentifierBodyMass":                 "body_mass",
    "HKQuantityTypeIdentifierBodyMassIndex":            "bmi",
    "HKQuantityTypeIdentifierBodyFatPercentage":        "body_fat",
    "HKQuantityTypeIdentifierLeanBodyMass":             "lean_body_mass",
    "HKQuantityTypeIdentifierWalkingSpeed":             "walking_speed",
    "HKQuantityTypeIdentifierAppleWalkingSteadiness":   "walking_steadiness",
    "HKQuantityTypeIdentifierDietaryEnergyConsumed":    "dietary_energy",
    "HKQuantityTypeIdentifierDietaryProtein":           "dietary_protein",
    "HKQuantityTypeIdentifierDietaryCarbohydrates":     "dietary_carbs",
    "HKQuantityTypeIdentifierDietaryFatTotal":          "dietary_fat",
    "HKQuantityTypeIdentifierHeadphoneAudioExposure":   "headphone_audio",
    "HKQuantityTypeIdentifierWalkingStepLength":        "walking_step_length",
    "HKQuantityTypeIdentifierWalkingDoubleSupportPercentage": "walking_double_support",
    "HKQuantityTypeIdentifierWalkingAsymmetryPercentage": "walking_asymmetry",
}


def parse_and_save(export_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(exist_ok=True)
    t0 = time.time()

    print(f"Parsing {export_path} ...")
    records: dict[str, list] = defaultdict(list)
    workouts: list = []
    me_info: dict = {}

    context = etree.iterparse(str(export_path), events=("end",), tag=("Record", "Workout", "Me"))

    for _event, elem in context:
        tag = elem.tag

        if tag == "Me":
            me_info = dict(elem.attrib)

        elif tag == "Record":
            hk_type = elem.get("type", "")
            if hk_type in TYPE_MAP:
                records[hk_type].append({
                    "startDate":  elem.get("startDate"),
                    "endDate":    elem.get("endDate"),
                    "value":      elem.get("value"),
                    "unit":       elem.get("unit"),
                    "sourceName": elem.get("sourceName"),
                })

        elif tag == "Workout":
            stats = {}
            for child in elem:
                if child.tag == "WorkoutStatistics":
                    stats[child.get("type", "")] = {
                        "sum":     child.get("sum"),
                        "average": child.get("average"),
                        "min":     child.get("minimum"),
                        "max":     child.get("maximum"),
                        "unit":    child.get("unit"),
                    }
            workouts.append({
                "activityType":      elem.get("workoutActivityType", "").replace("HKWorkoutActivityType", ""),
                "startDate":         elem.get("startDate"),
                "endDate":           elem.get("endDate"),
                "duration_min":      elem.get("duration"),
                "totalDistance":     elem.get("totalDistance"),
                "totalDistanceUnit": elem.get("totalDistanceUnit"),
                "totalEnergy_kcal":  elem.get("totalEnergyBurned"),
                "sourceName":        elem.get("sourceName"),
            })

        elem.clear()

    # -----------------------------------------------------------------------
    # Save each type as Parquet
    # -----------------------------------------------------------------------
    saved = []
    for hk_type, rows in records.items():
        short = TYPE_MAP[hk_type]
        df = pd.DataFrame(rows)
        df["startDate"] = pd.to_datetime(df["startDate"], utc=True, errors="coerce")
        df["endDate"]   = pd.to_datetime(df["endDate"],   utc=True, errors="coerce")
        df["value"]     = pd.to_numeric(df["value"], errors="coerce")
        df["date"]      = df["startDate"].dt.date.astype(str)   # store as str for Parquet compat
        path = output_dir / f"{short}.parquet"
        df.to_parquet(path, index=False)
        saved.append((short, len(df)))
        print(f"  ✓ {short:<35} {len(df):>8,} rows → {path.name}")

    # -----------------------------------------------------------------------
    # Save workouts
    # -----------------------------------------------------------------------
    if workouts:
        wdf = pd.DataFrame(workouts)
        wdf["startDate"]        = pd.to_datetime(wdf["startDate"], utc=True, errors="coerce")
        wdf["endDate"]          = pd.to_datetime(wdf["endDate"],   utc=True, errors="coerce")
        wdf["duration_min"]     = pd.to_numeric(wdf["duration_min"], errors="coerce")
        wdf["totalDistance"]    = pd.to_numeric(wdf["totalDistance"], errors="coerce")
        wdf["totalEnergy_kcal"] = pd.to_numeric(wdf["totalEnergy_kcal"], errors="coerce")
        wdf["date"]             = wdf["startDate"].dt.date.astype(str)
        path = output_dir / "workouts.parquet"
        wdf.to_parquet(path, index=False)
        print(f"  ✓ {'workouts':<35} {len(wdf):>8,} rows → {path.name}")

    # -----------------------------------------------------------------------
    # Save Me metadata
    # -----------------------------------------------------------------------
    if me_info:
        pd.DataFrame([me_info]).to_parquet(output_dir / "me.parquet", index=False)
        print(f"  ✓ me.parquet")

    elapsed = time.time() - t0
    total_rows = sum(n for _, n in saved)
    print(f"\nDone in {elapsed:.1f}s — {total_rows:,} records across {len(saved)} metrics + {len(workouts)} workouts")
    print(f"Output: {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preprocess Apple Health XML → Parquet")
    parser.add_argument("--export", type=Path, default=DEFAULT_EXPORT,
                        help="Path to exportación.xml")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="Output directory for Parquet files")
    args = parser.parse_args()

    if not args.export.exists():
        print(f"ERROR: Export file not found: {args.export}", file=sys.stderr)
        sys.exit(1)

    parse_and_save(args.export, args.output)
