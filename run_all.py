#!/usr/bin/env python3
"""Rebuild US ETF signals and backtest the standalone strategy."""

import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def execute_notebook(name):
    matches = list((ROOT / "pipeline").rglob(name + ".ipynb"))

    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected one notebook for {name}, found {len(matches)}"
        )

    path = matches[0]
    from IPython.display import display
    ns = {"__name__": "__main__", "display": display}

    notebook = json.loads(path.read_text(encoding="utf-8"))

    for i, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        exec(
            compile("".join(cell["source"]), f"{path}:cell{i}", "exec"),
            ns,
        )


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-data",
        action="store_true",
        help="Download fresh US ETF prices before rebuilding signals",
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    os.environ["ETF_PROJECT_ROOT"] = str(ROOT)
    os.environ["MPLBACKEND"] = "Agg"

    if args.update_data:
        print("Updating US ETF prices...", flush=True)
        import portfolio_accounting as pa
        updater = pa.load_definitions("01_data_update")
        updater["main"](download=True)

    logs = ROOT / "results" / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    stages = [
        "02_parameter_ensemble",
        "05_risk_allocation",
        "06_bsv_volatility_targeting",
    ]

    for stage in stages:
        print(f"Running {stage}...", flush=True)
        with (logs / f"{stage}.log").open("w", encoding="utf-8") as log:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                execute_notebook(stage)

    print("Running US-only backtest...", flush=True)
    subprocess.run(
        [sys.executable, str(ROOT / "us_backtest.py")],
        cwd=ROOT,
        check=True,
    )

    print("Generating US strategy report...", flush=True)
    subprocess.run(
        [sys.executable, str(ROOT / "us_report.py")],
        cwd=ROOT,
        check=True,
    )

    print("\nUS-only pipeline completed successfully.")


if __name__ == "__main__":
    main()
