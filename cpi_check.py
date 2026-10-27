"""Check CPI release coverage before running the forward strategy."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd

CPI_FILE = Path(__file__).resolve().parent / "data/raw/cpi_yoy.csv"

# Official BLS release schedule, 08:30 America/New_York.
# Extend this schedule when BLS publishes further release dates.
RELEASES = {
    "2026-10-14": "2026-09",
    "2026-11-10": "2026-10",
    "2026-12-10": "2026-11",
}


def check_cpi():
    now = datetime.now(ZoneInfo("America/New_York"))
    df = pd.read_csv(CPI_FILE)

    required = {
        "Release_Date", "Reference_Month",
        "Predicted_YOY", "Actual_YOY",
    }
    if not required.issubset(df.columns):
        raise ValueError("CPI CSV is missing required columns.")

    dates = pd.to_datetime(df["Release_Date"], errors="raise")
    if dates.duplicated().any():
        raise ValueError("Duplicate CPI release dates detected.")

    for col in ("Predicted_YOY", "Actual_YOY"):
        if pd.to_numeric(df[col], errors="coerce").isna().any():
            raise ValueError(f"Missing or invalid {col} in CPI CSV.")

    latest = dates.max().date()
    print(f"CPI latest recorded release: {latest}")

    for release, month in RELEASES.items():
        release_time = datetime.strptime(
            release + " 08:30", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=ZoneInfo("America/New_York"))

        if now >= release_time:
            match = df.loc[
                dates.dt.date == release_time.date()
            ]
            if match.empty or str(match.iloc[0]["Reference_Month"]) != month:
                raise RuntimeError(
                    f"CPI update required: {release} "
                    f"(reference month {month}). "
                    "Add verified Actual_YOY and Predicted_YOY "
                    "before running the forward simulation."
                )

    if now.date() >= datetime(2027, 1, 1).date():
        raise RuntimeError(
            "CPI release calendar needs updating for 2027."
        )

    upcoming = [
        date for date in RELEASES
        if datetime.strptime(date, "%Y-%m-%d").date() > now.date()
    ]
    print("CPI coverage check: PASSED")
    if upcoming:
        print(f"Next scheduled CPI release: {min(upcoming)}")


if __name__ == "__main__":
    check_cpi()
