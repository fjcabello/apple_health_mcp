"""
Apple Health MCP Server
Loads preprocessed Parquet files (run preprocess.py first) for fast startup.
Falls back to parsing the XML directly if Parquet files are not found.
"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from typing import Optional

import pandas as pd
from mcp.server.fastmcp import FastMCP

from config import HK_TYPE_MAP, SHORT_NAMES, SLEEP_VALUES

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

EXPORT_PATH = Path(os.environ.get(
    "APPLE_HEALTH_EXPORT",
    Path(__file__).parent.parent / "apple_health_export" / "exportación.xml"
))
DATA_DIR = Path(os.environ.get(
    "APPLE_HEALTH_DATA_DIR",
    Path(__file__).parent / "data"
))

# ---------------------------------------------------------------------------
# Data loading — Parquet first, XML fallback
# ---------------------------------------------------------------------------

_cache: dict = {}


def _load_data() -> dict:
    """
    Load data from Parquet files (fast). Falls back to parsing XML if
    Parquet files don't exist — run preprocess.py to generate them.
    """
    if _cache:
        return _cache

    parquet_available = DATA_DIR.exists() and any(DATA_DIR.glob("*.parquet"))

    if parquet_available:
        _load_from_parquet()
    else:
        print(
            "[apple-health-mcp] No Parquet files found. "
            "Run 'python preprocess.py' for faster startup. Falling back to XML...",
            file=sys.stderr,
        )
        _load_from_xml()

    return _cache


def _load_from_parquet() -> None:
    """Load all Parquet files from DATA_DIR into _cache."""
    import time
    t0 = time.time()
    print(f"[apple-health-mcp] Loading from Parquet: {DATA_DIR}", file=sys.stderr)

    frames: dict[str, pd.DataFrame] = {}
    for short in SHORT_NAMES:
        path = DATA_DIR / f"{short}.parquet"
        if path.exists():
            df = pd.read_parquet(path)
            # Restore datetime columns
            df["startDate"] = pd.to_datetime(df["startDate"], utc=True, errors="coerce")
            df["endDate"]   = pd.to_datetime(df["endDate"],   utc=True, errors="coerce")
            # date col is stored as str in Parquet — keep as str for filtering
            frames[short] = df

    workout_path = DATA_DIR / "workouts.parquet"
    workout_df = pd.DataFrame()
    if workout_path.exists():
        workout_df = pd.read_parquet(workout_path)
        workout_df["startDate"] = pd.to_datetime(workout_df["startDate"], utc=True, errors="coerce")
        workout_df["endDate"]   = pd.to_datetime(workout_df["endDate"],   utc=True, errors="coerce")

    me_info: dict = {}
    me_path = DATA_DIR / "me.parquet"
    if me_path.exists():
        me_info = pd.read_parquet(me_path).iloc[0].to_dict()

    _cache["frames"]   = frames
    _cache["workouts"] = workout_df
    _cache["me"]       = me_info

    total = sum(len(v) for v in frames.values())
    print(f"[apple-health-mcp] Loaded {total:,} records in {time.time()-t0:.2f}s", file=sys.stderr)


def _load_from_xml() -> None:
    """Stream-parse the XML as fallback when Parquet files don't exist."""
    from lxml import etree
    from collections import defaultdict
    import time



    t0 = time.time()
    print(f"[apple-health-mcp] Parsing XML: {EXPORT_PATH}", file=sys.stderr)

    records: dict[str, list] = defaultdict(list)
    workouts: list = []
    me_info: dict = {}

    context = etree.iterparse(str(EXPORT_PATH), events=("end",), tag=("Record", "Workout", "Me"))
    for _event, elem in context:
        tag = elem.tag
        if tag == "Me":
            me_info = dict(elem.attrib)
        elif tag == "Record":
            hk_type = elem.get("type", "")
            if hk_type in HK_TYPE_MAP:
                records[HK_TYPE_MAP[hk_type]].append({
                    "startDate":  elem.get("startDate"),
                    "endDate":    elem.get("endDate"),
                    "value":      elem.get("value"),
                    "unit":       elem.get("unit"),
                    "sourceName": elem.get("sourceName"),
                })
        elif tag == "Workout":
            avg_hr = None
            max_hr = None
            for child in elem:
                if child.tag == "WorkoutStatistics":
                    stat_type = child.get("type", "")
                    if "HeartRate" in stat_type:
                        avg_hr = child.get("average")
                        max_hr = child.get("maximum")
            workouts.append({
                "activityType":      elem.get("workoutActivityType", "").replace("HKWorkoutActivityType", ""),
                "startDate":         elem.get("startDate"),
                "endDate":           elem.get("endDate"),
                "duration_min":      elem.get("duration"),
                "totalDistance":     elem.get("totalDistance"),
                "totalDistanceUnit": elem.get("totalDistanceUnit"),
                "totalEnergy_kcal":  elem.get("totalEnergyBurned"),
                "sourceName":        elem.get("sourceName"),
                "avgHeartRate":      avg_hr,
                "maxHeartRate":      max_hr,
            })
        elem.clear()

    frames: dict[str, pd.DataFrame] = {}
    for short, rows in records.items():
        df = pd.DataFrame(rows)
        df["startDate"] = pd.to_datetime(df["startDate"], utc=True, errors="coerce")
        df["endDate"]   = pd.to_datetime(df["endDate"],   utc=True, errors="coerce")
        df["value"]     = pd.to_numeric(df["value"], errors="coerce")
        df["date"]      = df["startDate"].dt.date.astype(str)
        frames[short] = df

    workout_df = pd.DataFrame(workouts)
    if not workout_df.empty:
        workout_df["startDate"]        = pd.to_datetime(workout_df["startDate"], utc=True, errors="coerce")
        workout_df["endDate"]          = pd.to_datetime(workout_df["endDate"],   utc=True, errors="coerce")
        workout_df["duration_min"]     = pd.to_numeric(workout_df["duration_min"], errors="coerce")
        workout_df["totalDistance"]    = pd.to_numeric(workout_df["totalDistance"], errors="coerce")
        workout_df["totalEnergy_kcal"] = pd.to_numeric(workout_df["totalEnergy_kcal"], errors="coerce")
        workout_df["avgHeartRate"]     = pd.to_numeric(workout_df["avgHeartRate"], errors="coerce")
        workout_df["maxHeartRate"]     = pd.to_numeric(workout_df["maxHeartRate"], errors="coerce")
        workout_df["date"]             = workout_df["startDate"].dt.date.astype(str)

    _cache["frames"]   = frames
    _cache["workouts"] = workout_df
    _cache["me"]       = me_info

    total = sum(len(v) for v in frames.values())
    print(f"[apple-health-mcp] Loaded {total:,} records in {time.time()-t0:.1f}s", file=sys.stderr)


def _get_frame(short_name: str) -> Optional[pd.DataFrame]:
    data = _load_data()
    return data["frames"].get(short_name)


def _filter_dates(df: pd.DataFrame, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
    if start:
        df = df[df["date"] >= start]
    if end:
        df = df[df["date"] <= end]
    return df


def _date_summary(df: pd.DataFrame, agg: str = "sum") -> str:
    if df.empty:
        return "No data for the specified range."
    daily = df.groupby("date")["value"].agg(agg).reset_index()
    daily.columns = ["date", "value"]
    daily["value"] = daily["value"].round(2)
    return daily.to_string(index=False)


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP("apple-health", host="0.0.0.0", port=8001)


@mcp.tool()
def health_summary() -> str:
    """
    Returns a high-level summary of all available Apple Health data:
    types available, total record counts, and date range.
    """
    data = _load_data()
    frames = data["frames"]
    me = data["me"]
    workouts = data["workouts"]

    lines = ["=== Apple Health Export Summary ===\n"]

    if me:
        dob = me.get("HKCharacteristicTypeIdentifierDateOfBirth", "?")
        sex = me.get("HKCharacteristicTypeIdentifierBiologicalSex", "?").replace("HKBiologicalSex", "")
        lines.append(f"Date of birth : {dob}")
        lines.append(f"Biological sex: {sex}\n")

    lines.append(f"{'Data type':<45} {'Records':>10}  {'From':<12}  {'To':<12}")
    lines.append("-" * 85)

    for short in SHORT_NAMES:
        df = frames.get(short)
        if df is not None and not df.empty:
            n   = len(df)
            lo  = str(df["date"].min())
            hi  = str(df["date"].max())
            lines.append(f"{short:<45} {n:>10,}  {lo:<12}  {hi:<12}")

    if not workouts.empty:
        n   = len(workouts)
        lo  = str(workouts["date"].min())
        hi  = str(workouts["date"].max())
        lines.append(f"{'workouts':<45} {n:>10,}  {lo:<12}  {hi:<12}")

    return "\n".join(lines)


@mcp.tool()
def get_steps(start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
    """
    Returns daily step counts. Optionally filter by start_date and/or end_date (YYYY-MM-DD).
    """
    df = _get_frame("steps")
    if df is None or df.empty:
        return "No step data available."
    df = _filter_dates(df, start_date, end_date)
    result = _date_summary(df, "sum")
    total = df["value"].sum()
    avg   = df.groupby("date")["value"].sum().mean()
    return f"Total steps: {total:,.0f}  |  Daily average: {avg:,.0f}\n\n{result}"


@mcp.tool()
def get_heart_rate(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    stat: str = "mean"
) -> str:
    """
    Returns heart rate data aggregated by day.
    stat options: mean, min, max (default: mean).
    Optionally filter by start_date and/or end_date (YYYY-MM-DD).
    """
    df = _get_frame("heart_rate")
    if df is None or df.empty:
        return "No heart rate data available."
    df = _filter_dates(df, start_date, end_date)
    agg_map = {"mean": "mean", "min": "min", "max": "max"}
    agg = agg_map.get(stat, "mean")
    result = _date_summary(df, agg)
    overall = df["value"].agg(agg)
    return f"Heart rate ({stat}) overall: {overall:.1f} bpm\n\n{result}"


@mcp.tool()
def get_resting_heart_rate(start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
    """
    Returns resting heart rate values by day. Optionally filter by date range (YYYY-MM-DD).
    """
    df = _get_frame("resting_hr")
    if df is None or df.empty:
        return "No resting heart rate data available."
    df = _filter_dates(df, start_date, end_date)
    return _date_summary(df, "mean")


@mcp.tool()
def get_sleep(start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
    """
    Returns sleep analysis: hours per stage (Core, Deep, REM, Awake) aggregated by night.
    Optionally filter by start_date and/or end_date (YYYY-MM-DD).
    """
    data = _load_data()
    df = data["frames"].get("sleep")
    if df is None or df.empty:
        return "No sleep data available."

    df = _filter_dates(df, start_date, end_date).copy()
    df["stage"]      = df["value"].map(SLEEP_VALUES).fillna(df["value"])
    df["duration_h"] = (df["endDate"] - df["startDate"]).dt.total_seconds() / 3600
    # Attribute sleep to the night it belongs to (if start < 12:00 → previous night)
    df["night"] = df.apply(
        lambda r: (pd.Timestamp(r["date"]) - pd.Timedelta(days=1)).date().isoformat()
        if r["startDate"].hour < 12 else r["date"],
        axis=1,
    )

    pivot = (
        df.groupby(["night", "stage"])["duration_h"]
        .sum()
        .unstack(fill_value=0)
        .round(2)
    )
    total_sleep = pivot[[c for c in ["Core", "Deep", "REM", "Asleep"] if c in pivot.columns]].sum(axis=1)
    pivot["Total_sleep_h"] = total_sleep.round(2)

    means = pivot.mean().round(2)
    header = f"Nightly averages:\n{means.to_string()}\n\n"
    return header + pivot.to_string()


@mcp.tool()
def get_workouts(
    activity_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 50
) -> str:
    """
    Returns workout sessions. Optionally filter by activity_type (e.g. 'Running', 'Cycling'),
    date range (YYYY-MM-DD), and limit the number of results (default 50).
    """
    data = _load_data()
    df = data["workouts"].copy()
    if df.empty:
        return "No workout data available."

    if activity_type:
        df = df[df["activityType"].str.contains(activity_type, case=False, na=False)]
    df = _filter_dates(df, start_date, end_date)

    if df.empty:
        return "No workouts matching the given filters."

    # Summary stats
    n = len(df)
    types = df["activityType"].value_counts().to_dict()
    total_min = df["duration_min"].sum()
    total_kcal = df["totalEnergy_kcal"].sum()

    summary = (
        f"Total workouts: {n}\n"
        f"Total time: {total_min/60:.1f} h\n"
        f"Total energy: {total_kcal:,.0f} kcal\n"
        f"By type: {types}\n\n"
    )

    cols = ["date", "activityType", "duration_min", "totalDistance",
            "totalDistanceUnit", "totalEnergy_kcal", "avgHeartRate", "maxHeartRate", "sourceName"]
    display = df[[c for c in cols if c in df.columns]].head(limit)
    display = display.rename(columns={
        "activityType": "type",
        "duration_min": "mins",
        "totalDistance": "dist",
        "totalDistanceUnit": "dist_unit",
        "totalEnergy_kcal": "kcal",
        "avgHeartRate": "avg_hr",
        "maxHeartRate": "max_hr",
    })
    return summary + display.to_string(index=False)


@mcp.tool()
def get_body_metrics(start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
    """
    Returns body metrics: weight (kg), BMI, body fat %, and lean body mass over time.
    Optionally filter by date range (YYYY-MM-DD).
    """
    data = _load_data()
    results = []
    for short in ["body_mass", "bmi", "body_fat", "lean_body_mass"]:
        df = _get_frame(short)
        if df is not None and not df.empty:
            df = _filter_dates(df, start_date, end_date)
            if not df.empty:
                unit = df["unit"].iloc[0] if "unit" in df.columns else ""
                daily = df.groupby("date")["value"].mean().round(2).reset_index()
                results.append(f"--- {short} ({unit}) ---\n{daily.to_string(index=False)}")

    return "\n\n".join(results) if results else "No body metrics available."


@mcp.tool()
def get_activity_energy(start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
    """
    Returns daily active and basal energy burned (kcal), plus walking/running distance.
    Optionally filter by date range (YYYY-MM-DD).
    """
    data = _load_data()
    sections = []
    for short, label in [
        ("active_energy", "Active energy (kcal)"),
        ("basal_energy",  "Basal energy (kcal)"),
        ("distance_walk", "Walking/running distance"),
        ("flights_climbed", "Flights climbed"),
    ]:
        df = _get_frame(short)
        if df is not None and not df.empty:
            df = _filter_dates(df, start_date, end_date)
            if not df.empty:
                unit = df["unit"].iloc[0] if "unit" in df.columns else ""
                total = df["value"].sum()
                avg   = df.groupby("date")["value"].sum().mean()
                sections.append(
                    f"--- {label} ({unit}) ---\n"
                    f"Total: {total:,.1f}  |  Daily average: {avg:,.1f}\n"
                    f"{_date_summary(df, 'sum')}"
                )
    return "\n\n".join(sections) if sections else "No energy/activity data available."


@mcp.tool()
def get_nutrition(start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
    """
    Returns daily nutritional intake: energy (kcal), protein, carbs, fat.
    Optionally filter by date range (YYYY-MM-DD).
    """
    data = _load_data()
    sections = []
    for short, label in [
        ("dietary_energy",  "Energy (kcal)"),
        ("dietary_protein", "Protein (g)"),
        ("dietary_carbs",   "Carbohydrates (g)"),
        ("dietary_fat",     "Total fat (g)"),
    ]:
        df = _get_frame(short)
        if df is not None and not df.empty:
            df = _filter_dates(df, start_date, end_date)
            if not df.empty:
                sections.append(f"--- {label} ---\n{_date_summary(df, 'sum')}")
    return "\n\n".join(sections) if sections else "No nutrition data available."


@mcp.tool()
def query_health_data(
    metric: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    aggregation: str = "sum"
) -> str:
    """
    Generic query for any available metric.
    metric: one of steps, heart_rate, resting_hr, active_energy, basal_energy,
            distance_walk, distance_cycling, flights_climbed, sleep, body_mass,
            bmi, body_fat, lean_body_mass, walking_speed, walking_steadiness,
            dietary_energy, dietary_protein, dietary_carbs, dietary_fat,
            headphone_audio, walking_step_length, walking_double_support,
            walking_asymmetry
    aggregation: sum, mean, min, max (default: sum)
    start_date / end_date: YYYY-MM-DD (optional)
    """
    df = _get_frame(metric)
    if df is None:
        available = ", ".join(SHORT_NAMES)
        return f"Unknown metric '{metric}'. Available: {available}"
    if df.empty:
        return f"No data for '{metric}'."
    df = _filter_dates(df, start_date, end_date)
    return _date_summary(df, aggregation)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    app = mcp.streamable_http_app()
    uvicorn.run(app, host="0.0.0.0", port=8001)
