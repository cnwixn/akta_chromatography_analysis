#!/usr/bin/env python3
"""Plot an IMAC run exported from the AKTA system.

Reads the tab-separated CSV that the instrument writes, pulls out UV280,
conductivity and the Buffer B programme, then draws the chromatogram with
fraction markers. Two figures are written next to the input file.

Usage:
    python imac_analysis.py run.csv
    python imac_analysis.py            # uses the only CSV in the folder
    python imac_analysis.py run.csv --outdir figures --xmax 60
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import chardet
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

# Column layout of the AKTA export. Each series takes two columns, the first
# one is the volume in mL and the second one the measured value.
SERIES = {
    "UV_280": (0, 1),
    "Cond": (2, 3),
    "Conc_B": (4, 5),
}
FRACTION_VOLUME_COL = 6
FRACTION_LABEL_COL = 7


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot an AKTA IMAC run.")
    parser.add_argument(
        "csv",
        nargs="?",
        help="AKTA CSV export; when omitted the only CSV in the folder is used",
    )
    parser.add_argument("-o", "--outdir", default=None, help="output directory")
    parser.add_argument("--xmax", type=float, default=30.0, help="x-axis upper limit in mL")
    parser.add_argument("--uv-max", type=float, default=200.0, help="UV280 axis upper limit")
    parser.add_argument("--b-max", type=float, default=100.0, help="Buffer B axis upper limit")
    parser.add_argument("--dpi", type=int, default=1200, help="figure resolution")
    return parser.parse_args(argv)


def find_csv(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            sys.exit(f"CSV not found: {path}")
        return path
    candidates = sorted(Path.cwd().glob("*.csv"))
    if len(candidates) != 1:
        sys.exit(
            f"Expected exactly one CSV in {Path.cwd()}, found {len(candidates)}. "
            "Pass the file as an argument."
        )
    return candidates[0]


def read_akta_csv(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    with path.open("rb") as handle:
        encoding = chardet.detect(handle.read(10000))["encoding"]
    try:
        text = path.read_text(encoding=encoding)
    except (LookupError, UnicodeDecodeError):
        text = path.read_text(encoding="utf-8", errors="ignore")
    text = text.replace("\x00", "")

    raw = pd.read_csv(io.StringIO(text), sep="\t")

    data = pd.DataFrame()
    for name, (vol_col, value_col) in SERIES.items():
        data[f"{name}_Volume"] = pd.to_numeric(raw.iloc[2:, vol_col], errors="coerce")
        data[name] = pd.to_numeric(raw.iloc[2:, value_col], errors="coerce")
    data = data.dropna(how="all").reset_index(drop=True)

    fractions = pd.DataFrame(
        {
            "Frac_Volume": pd.to_numeric(raw.iloc[2:, FRACTION_VOLUME_COL], errors="coerce"),
            "Frac": raw.iloc[2:, FRACTION_LABEL_COL],
        }
    )
    fractions = fractions.dropna(subset=["Frac"])
    fractions = fractions[fractions["Frac"] != ""].reset_index(drop=True)
    return data, fractions


def style() -> None:
    plt.rcParams.update(
        {
            "font.family": "Times New Roman",
            "font.weight": "bold",
            "axes.labelweight": "bold",
            "font.size": 20,
            "lines.linewidth": 3.0,
        }
    )


def draw_chromatogram(data, fractions, args, label_rule) -> plt.Figure:
    fig, ax1 = plt.subplots(figsize=(12, 8))
    ax1.set_xlabel("Volume (mL)")
    ax1.set_ylabel("UV 280 (mAU)", color="black")
    ax1.plot(data["UV_280_Volume"], data["UV_280"], color="blue", label="UV 280 (mAU)")
    ax1.tick_params(axis="y", labelcolor="black")

    ax2 = ax1.twinx()
    ax2.set_ylabel("Conc B (%)", color="black")
    ax2.plot(data["Conc_B_Volume"], data["Conc_B"], color="red", label="Conc B (%)")
    ax2.tick_params(axis="y", labelcolor="black")

    for volume in fractions["Frac_Volume"]:
        ax1.axvline(
            x=volume,
            color="darkgreen",
            linestyle="-",
            alpha=0.8,
            ymin=0.005,
            ymax=0.01,
            clip_on=False,
        )

    for _, row in fractions.iterrows():
        if label_rule(row["Frac"]):
            ax1.text(
                row["Frac_Volume"],
                0.05,
                row["Frac"],
                transform=ax1.get_xaxis_transform(),
                rotation=0,
                verticalalignment="top",
                horizontalalignment="center",
                fontsize=10,
                color="darkgreen",
                bbox=dict(facecolor="white", alpha=0, pad=1, edgecolor="none", boxstyle="round"),
            )

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper center",
        framealpha=0.5,
        frameon=True,
        edgecolor="black",
    )

    ax1.grid(axis="y", linestyle="--", alpha=0.7)
    ax1.grid(axis="x", visible=False)
    ax1.set_xlim(left=0, right=args.xmax)
    ax1.set_ylim(bottom=0, top=args.uv_max)
    ax2.set_ylim(bottom=0, top=args.b_max)
    return fig


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    csv_path = find_csv(args.csv)
    outdir = Path(args.outdir) if args.outdir else csv_path.parent
    outdir.mkdir(parents=True, exist_ok=True)

    data, fractions = read_akta_csv(csv_path)
    style()

    first = draw_chromatogram(
        data,
        fractions,
        args,
        lambda label: label.endswith("A.1") or label == "Waste(Frac)",
    )
    first_path = outdir / f"{csv_path.stem}.jpg"
    first.savefig(first_path, dpi=args.dpi, bbox_inches="tight")
    plt.close(first)

    second = draw_chromatogram(
        data,
        fractions,
        args,
        lambda label: label.endswith(".3") or label.endswith(".8"),
    )
    second_path = outdir / f"{csv_path.stem}_Fracs.jpg"
    second.savefig(second_path, dpi=max(args.dpi, 1600), bbox_inches="tight")
    plt.close(second)

    print(f"Input:      {csv_path}")
    print(f"Fractions:  {len(fractions)}")
    print(f"Chromatogram: {first_path}")
    print(f"With labels:  {second_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
