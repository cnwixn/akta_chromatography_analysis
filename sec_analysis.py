"""
Recommended runtime environment
- Dedicated Conda environment: sec-analysis
- Python: 3.13 or compatible
- Required packages: pandas, matplotlib

Setup uses environment.yml from the installed skill folder, not the experiment:
- conda env create -f "/absolute/path/to/sec-analysis/environment.yml"
- conda activate sec-analysis
- After copying this template beside its CSV, run python "{csv_stem}_SEC.py".
- Compatible existing imac-sec-analysis or akta-analysis environments can also be used.
"""

from __future__ import annotations

import argparse
import io
from html import escape
from pathlib import Path
from typing import Optional

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


# None gives a diagnostic overview; select final limits after image/data review.
# Project convention: final SEC figures start at 2.5 mL; set the upper bound after reviewing the run.
X_LIMITS: Optional[tuple[float, float]] = None  # mL
UV_Y_LIMITS: Optional[tuple[float, float]] = None  # mAU
FRACTION_LABEL_Y = -0.065  # axes fraction, below the x-axis tick labels
FIGURE_DPI = 300  # export resolution, overridden by the web UI
FIGURE_SIZE = (12.0, 10.0)  # inches, overridden by the web UI
INCLUDE_CUT_TRACE = False  # set by --include-cut or the web UI


def checked_limits(limits: tuple[float, float], name: str) -> tuple[float, float]:
    from math import isfinite
    low, high = map(float, limits)
    if not (isfinite(low) and isfinite(high) and low < high):
        raise ValueError(f"{name} must contain two finite increasing bounds.")
    return low, high


def resolve_limits(limits, automatic, name):
    """Fill a missing bound from the automatic one, then validate the pair."""
    if limits is None:
        return automatic
    low, high = limits
    if low is None:
        low = automatic[0]
    if high is None:
        high = automatic[1]
    return checked_limits((low, high), name)


def local_uv_limits(values: pd.Series) -> tuple[float, float]:
    from math import isfinite
    values = values.dropna()
    values = values[values.map(isfinite)]
    if values.empty:
        raise ValueError("No finite UV samples inside the selected display/scaling window.")
    low = min(float(values.min()), 0.0)
    high = max(float(values.max()), 0.0)
    span = high - low
    padding = 0.08 * (span if span > 0 else max(abs(high), 1.0))
    return low - padding, high + padding


DATA_SERIES = {
    "UV_280": {"vol_col": 0, "data_col": 1},
    "Cond": {"vol_col": 2, "data_col": 3},
    "Conc_B": {"vol_col": 4, "data_col": 5},
    "UV_280_CUT": {"vol_col": 12, "data_col": 13},
}

SERIES_VALIDATION_RULES = {
    "UV_280": {"header_tokens": ["uv", "280"], "unit_tokens": ["mau"]},
    "Cond": {"header_tokens": ["cond"], "unit_tokens": ["ms/cm"]},
    "Conc_B": {"header_tokens": ["conc", "b"], "unit_tokens": ["%"]},
    "UV_280_CUT": {"header_tokens": ["uv", "280", "cut"], "unit_tokens": ["mau"]},
}

FRACTION_VALIDATION_RULE = {"header_tokens": ["fraction"], "unit_tokens": ["fraction"]}


def normalize_text(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    return " ".join(text.strip().lower().split())


def contains_all_tokens(text: str, tokens: list[str]) -> bool:
    normalized_text = normalize_text(text)
    normalized_tokens = [normalize_text(token) for token in tokens]
    return all(token in normalized_text for token in normalized_tokens)


def auto_detect_data_series_mapping(df: pd.DataFrame) -> dict[str, dict[str, int]]:
    if len(df) < 2:
        raise ValueError("The input dataframe does not contain enough header rows for DATA_SERIES validation.")

    detected_mapping: dict[str, dict[str, int]] = {}
    column_count = len(df.columns)

    for series_name, rules in SERIES_VALIDATION_RULES.items():
        matched_pair: dict[str, int] | None = None

        for vol_col in range(column_count - 1):
            data_col = vol_col + 1
            header_text = normalize_text(df.iloc[0, vol_col])
            volume_unit = normalize_text(df.iloc[1, vol_col])
            data_unit = normalize_text(df.iloc[1, data_col])

            if not contains_all_tokens(header_text, rules["header_tokens"]):
                continue
            if "ml" not in volume_unit:
                continue
            if not contains_all_tokens(data_unit, rules["unit_tokens"]):
                continue

            matched_pair = {"vol_col": vol_col, "data_col": data_col}
            break

        if matched_pair is None:
            raise ValueError(
                f"Unable to auto-detect a valid mapping for '{series_name}'. "
                "Please check the CSV header layout or update DATA_SERIES."
            )

        detected_mapping[series_name] = matched_pair

    return detected_mapping


def validate_data_series_mapping(df: pd.DataFrame) -> tuple[dict[str, dict[str, int]], list[str]]:
    detected_mapping = auto_detect_data_series_mapping(df)
    mismatches: list[str] = []

    for series_name, expected in DATA_SERIES.items():
        detected = detected_mapping.get(series_name)
        if detected != expected:
            mismatches.append(
                f"{series_name}: expected {expected}, detected {detected}"
            )

    return detected_mapping, mismatches


def auto_detect_fraction_mapping(df: pd.DataFrame) -> dict[str, int]:
    if len(df) < 2:
        raise ValueError("The input dataframe does not contain enough header rows for Fraction validation.")

    column_count = len(df.columns)

    for vol_col in range(column_count - 1):
        data_col = vol_col + 1
        header_text = normalize_text(df.iloc[0, vol_col])
        volume_unit = normalize_text(df.iloc[1, vol_col])
        data_unit = normalize_text(df.iloc[1, data_col])

        if not contains_all_tokens(header_text, FRACTION_VALIDATION_RULE["header_tokens"]):
            continue
        if "ml" not in volume_unit:
            continue
        if not contains_all_tokens(data_unit, FRACTION_VALIDATION_RULE["unit_tokens"]):
            continue

        return {"vol_col": vol_col, "data_col": data_col}

    raise ValueError(
        "Unable to auto-detect a valid Fraction mapping. "
        "Please check the CSV header layout."
    )


def detect_encoding(file_path: Path) -> str:
    raw = file_path.read_bytes()[:10000]

    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"

    for encoding in ("utf-16", "utf-8", "latin-1"):
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue

    return "utf-8"


def load_dataframe(file_path: Path) -> pd.DataFrame:
    encoding = detect_encoding(file_path)

    try:
        content = file_path.read_text(encoding=encoding)
    except UnicodeDecodeError:
        content = file_path.read_text(encoding="utf-8", errors="ignore")

    content = content.replace("\x00", "")
    return pd.read_csv(io.StringIO(content), sep="\t")


def extract_processed_data(df: pd.DataFrame, series_mapping: dict[str, dict[str, int]]) -> pd.DataFrame:
    processed = pd.DataFrame()

    for name, info in series_mapping.items():
        volume = pd.to_numeric(df.iloc[2:, info["vol_col"]], errors="coerce").reset_index(drop=True)
        values = pd.to_numeric(df.iloc[2:, info["data_col"]], errors="coerce").reset_index(drop=True)
        processed[f"{name}_Volume"] = volume
        processed[name] = values

    processed = processed.dropna(how="all").reset_index(drop=True)
    return processed


def extract_fraction_data(df: pd.DataFrame, fraction_mapping: dict[str, int]) -> pd.DataFrame:
    fraction_df = pd.DataFrame(
        {
            "Frac_Volume": pd.to_numeric(df.iloc[2:, fraction_mapping["vol_col"]], errors="coerce").reset_index(drop=True),
            "Frac": df.iloc[2:, fraction_mapping["data_col"]].reset_index(drop=True),
        }
    )

    fraction_df = fraction_df.dropna(subset=["Frac"])
    fraction_df = fraction_df[fraction_df["Frac"] != ""].reset_index(drop=True)
    return fraction_df


def style_plot() -> None:
    plt.rcParams.update(
        {
            "font.family": "Arial",
            "font.weight": "bold",
            "axes.labelweight": "bold",
            "font.size": 26,
            "axes.labelsize": 26,
            "xtick.labelsize": 20,
            "ytick.labelsize": 20,
            "legend.fontsize": 20,
            "lines.linewidth": 3.5,
        }
    )


def compute_uv_axis_limits(processed_data: pd.DataFrame, fraction_df: pd.DataFrame, include_cut_trace: bool) -> tuple[tuple[float, float], tuple[float, float]]:
    trace_pairs = [("UV_280_Volume", "UV_280")]
    if include_cut_trace:
        trace_pairs.append(("UV_280_CUT_Volume", "UV_280_CUT"))
    traces = []
    for volume_col, value_col in trace_pairs:
        valid = processed_data[[volume_col, value_col]].dropna()
        valid = valid[valid[volume_col] >= 0]
        traces.append(valid.rename(columns={volume_col: "volume", value_col: "uv"}))
    combined = pd.concat(traces, ignore_index=True)
    if combined.empty:
        raise ValueError("No valid non-negative-volume UV samples.")
    volume_max = float(combined["volume"].max())
    automatic_x = (0.0, volume_max)
    if X_LIMITS is None and not fraction_df.empty:
        volume_max = max(volume_max, float(fraction_df["Frac_Volume"].max()))
        automatic_x = (0.0, volume_max + max(volume_max * 0.03, 0.5))
    x_limits = resolve_limits(X_LIMITS, automatic_x, "X_LIMITS")
    selected = combined[combined["volume"].between(*x_limits)]["uv"]
    automatic_y = local_uv_limits(selected)
    y_limits = resolve_limits(UV_Y_LIMITS, automatic_y, "UV_Y_LIMITS")
    return x_limits, y_limits


def add_fraction_markers(ax: plt.Axes, fraction_df: pd.DataFrame, show_labels: bool = False, x_limits=None) -> None:
    if x_limits is not None:
        fraction_df = fraction_df[fraction_df["Frac_Volume"].between(*x_limits)]
    for volume in fraction_df["Frac_Volume"]:
        ax.axvline(
            x=volume,
            color="darkgreen",
            linestyle="-",
            alpha=0.8,
            ymin=0.005,
            ymax=0.01,
            clip_on=False,
        )

    if show_labels:
        for _, row in fraction_df.iterrows():
            volume = row["Frac_Volume"]
            label = str(row["Frac"])
            if label.endswith(".1") or label.endswith(".7"):
                ax.text(
                    volume,
                    FRACTION_LABEL_Y,
                    label,
                    transform=ax.get_xaxis_transform(),
                    rotation=45,
                    verticalalignment="top",
                    horizontalalignment="center",
                    fontsize=14,
                    color="darkgreen",
                    bbox={
                        "facecolor": "white",
                        "alpha": 0,
                        "pad": 1,
                        "edgecolor": "none",
                        "boxstyle": "round",
                    },
                )


def export_dataframe_outputs(
    file_path: Path,
    output_dir: Path,
    raw_df: pd.DataFrame,
    processed_data: pd.DataFrame,
    fraction_df: pd.DataFrame,
    detected_mapping: dict[str, dict[str, int]],
    mapping_mismatches: list[str],
) -> list[str]:
    html_report = Path(output_dir) / f"{file_path.stem}_data_report.html"
    raw_head20 = raw_df.head(20)
    processed_head20 = processed_data.head(20)
    data_series_df = pd.DataFrame.from_dict(DATA_SERIES, orient="index").reset_index()
    data_series_df = data_series_df.rename(columns={"index": "Series"})
    detected_series_df = pd.DataFrame.from_dict(detected_mapping, orient="index").reset_index()
    detected_series_df = detected_series_df.rename(columns={"index": "Series"})
    mapping_status = "Matched default DATA_SERIES mapping." if not mapping_mismatches else "Detected mapping differs from default DATA_SERIES mapping."
    mapping_details_html = "<br>".join(escape(item) for item in mapping_mismatches) if mapping_mismatches else "None"

    report_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape(file_path.stem)} Data Report</title>
  <style>
    body {{
      font-family: Arial, sans-serif;
      margin: 24px;
      line-height: 1.4;
    }}
    h1, h2 {{
      margin-bottom: 12px;
    }}
    .meta {{
      margin-bottom: 24px;
      padding: 12px 16px;
      background: #f5f5f5;
      border-radius: 8px;
    }}
    .table-wrap {{
      overflow-x: auto;
      margin-bottom: 32px;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      font-size: 12px;
    }}
    th, td {{
      border: 1px solid #d0d0d0;
      padding: 6px 8px;
      text-align: right;
      white-space: nowrap;
    }}
    th {{
      background: #efefef;
    }}
    td:first-child, th:first-child {{
      text-align: left;
    }}
  </style>
</head>
<body>
  <h1>{escape(file_path.stem)} Data Report</h1>
  <div class="meta">
    <div><strong>Source CSV:</strong> {escape(file_path.name)}</div>
    <div><strong>Processed rows:</strong> {len(processed_data)}</div>
    <div><strong>Fraction rows:</strong> {len(fraction_df)}</div>
    <div><strong>Mapping status:</strong> {escape(mapping_status)}</div>
    <div><strong>Mapping details:</strong> {mapping_details_html}</div>
  </div>
  <h2>Default DATA_SERIES</h2>
  <div class="table-wrap">
    {data_series_df.to_html(index=False, classes="dataframe", border=0)}
  </div>
  <h2>Detected DATA_SERIES</h2>
  <div class="table-wrap">
    {detected_series_df.to_html(index=False, classes="dataframe", border=0)}
  </div>
  <h2>Raw Data Head 20</h2>
  <div class="table-wrap">
    {raw_head20.to_html(index=False, classes="dataframe", border=0)}
  </div>
  <h2>Processed Data Head 20</h2>
  <div class="table-wrap">
    {processed_head20.to_html(index=False, classes="dataframe", border=0)}
  </div>
  <h2>Fraction Data</h2>
  <div class="table-wrap">
    {fraction_df.to_html(index=False, classes="dataframe", border=0)}
  </div>
</body>
</html>
"""
    html_report.write_text(report_html, encoding="utf-8")

    return [html_report.name]


def plot_chromatogram(
    processed_data: pd.DataFrame,
    fraction_df: pd.DataFrame,
    output_path: Path,
    include_cut_trace: bool,
    show_labels: bool = False,
) -> None:
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    x_limits, y_limits = compute_uv_axis_limits(processed_data, fraction_df, include_cut_trace)

    ax.set_ylabel("UV 280 (mAU)", color="black")
    ax.plot(processed_data["UV_280_Volume"], processed_data["UV_280"], color="blue", label="UV 280 (mAU)")

    if include_cut_trace:
        ax.plot(
            processed_data["UV_280_CUT_Volume"],
            processed_data["UV_280_CUT"],
            color="yellow",
            label="UV 280 Cut (mAU)",
        )

    add_fraction_markers(ax, fraction_df, show_labels, x_limits)

    lines, labels = ax.get_legend_handles_labels()
    ax.legend(
        lines,
        labels,
        loc="lower right",
        bbox_to_anchor=(1.0, 1.02),
        borderaxespad=0,
    )
    ax.grid(axis="y", linestyle="--", alpha=0.7)
    ax.grid(axis="x", visible=False)
    ax.set_xlim(*x_limits)
    ax.set_ylim(*y_limits)

    ax.set_xlabel("Volume (mL)", labelpad=42)
    plt.subplots_adjust(bottom=0.34)

    fig.savefig(output_path, dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)


def log_message(message: str, log_lines: list[str]) -> None:
    print(message)
    log_lines.append(message)


def analyse_file(file_path: Path, log_lines: list[str], output_dir: Optional[Path] = None) -> None:
    out_dir = Path(output_dir) if output_dir else file_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    log_message(f"Processing: {file_path.name}", log_lines)
    raw_df = load_dataframe(file_path)
    validated_mapping, mapping_mismatches = validate_data_series_mapping(raw_df)
    fraction_mapping = auto_detect_fraction_mapping(raw_df)
    processed_data = extract_processed_data(raw_df, validated_mapping)
    fraction_df = extract_fraction_data(raw_df, fraction_mapping)
    exported_files = export_dataframe_outputs(
        file_path,
        out_dir,
        raw_df,
        processed_data,
        fraction_df,
        validated_mapping,
        mapping_mismatches,
    )
    log_message(f"Validated DATA_SERIES: {validated_mapping}", log_lines)
    log_message(f"Validated Fraction mapping: {fraction_mapping}", log_lines)
    if mapping_mismatches:
        for mismatch in mapping_mismatches:
            log_message(f"Mapping mismatch: {mismatch}", log_lines)

    x_range, y_range = compute_uv_axis_limits(processed_data, fraction_df, INCLUDE_CUT_TRACE)
    log_message(f"Display x (mL): {x_range}; UV y (mAU): {y_range}", log_lines)
    style_plot()
    # plot_chromatogram(processed_data, fraction_df, file_path.with_name(f"{file_path.stem}_raw.jpg"), True, show_labels=False)
    # plot_chromatogram(processed_data, fraction_df, file_path.with_name(f"{file_path.stem}_raw_noted.jpg"), True, show_labels=True)
    plot_chromatogram(processed_data, fraction_df, out_dir / f"{file_path.stem}.jpg", INCLUDE_CUT_TRACE, show_labels=False)
    plot_chromatogram(processed_data, fraction_df, out_dir / f"{file_path.stem}_noted.jpg", INCLUDE_CUT_TRACE, show_labels=True)

    # log_message(f"Saved: {file_path.stem}_raw.jpg", log_lines)
    # log_message(f"Saved: {file_path.stem}_raw_noted.jpg", log_lines)
    log_message(f"Saved: {file_path.stem}.jpg", log_lines)
    log_message(f"Saved: {file_path.stem}_noted.jpg", log_lines)
    for exported_file in exported_files:
        log_message(f"Saved: {exported_file}", log_lines)


def main(target_dir: Optional[str] = None) -> None:
    directory = Path(target_dir) if target_dir else Path(__file__).resolve().parent
    csv_files = sorted(directory.glob("*.csv"))
    log_lines: list[str] = []
    log_path = directory / "log.md"

    try:
        if not csv_files:
            raise FileNotFoundError(f"No csv files were found in {directory}.")

        log_message(f"Detected {len(csv_files)} csv files.", log_lines)
        for csv_file in csv_files:
            analyse_file(csv_file, log_lines)

        log_message("All processing completed.", log_lines)
    except Exception as error:
        log_message(f"ERROR: {type(error).__name__}: {error}", log_lines)
        raise
    finally:
        if directory.is_dir():
            log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Plot an AKTA SEC run exported as a tab-separated CSV."
    )
    parser.add_argument("csv", nargs="?", help="CSV to plot; without it every CSV beside this script is used")
    parser.add_argument("-o", "--outdir", help="output folder (default: the CSV folder)")
    parser.add_argument("--x-min", type=float, help="volume axis start in mL")
    parser.add_argument("--x-max", type=float, help="volume axis end in mL")
    parser.add_argument("--uv-min", type=float, help="UV axis minimum in mAU")
    parser.add_argument("--uv-max", type=float, help="UV axis maximum in mAU")
    parser.add_argument("--include-cut", action="store_true", help="also draw the UV 280 cut trace")
    parser.add_argument("--fraction-label-y", type=float, help="fraction label offset in axes fraction")
    parser.add_argument("--dpi", type=int, help="figure resolution (default: 300)")
    parser.add_argument("--width", type=float, help="figure width in inches (default: 12)")
    parser.add_argument("--height", type=float, help="figure height in inches (default: 10)")
    return parser



def _pair(low, high, name):
    """One-sided bounds are allowed; the missing side stays automatic."""
    if low is None and high is None:
        return None
    return (low, high)


def _window(low, high, name):
    if low is None and high is None:
        return None
    if low is None or high is None:
        raise SystemExit(f"{name}: give both bounds or neither.")
    return checked_limits((low, high), name)


def cli(argv=None):
    global X_LIMITS, UV_Y_LIMITS, FRACTION_LABEL_Y, FIGURE_DPI, FIGURE_SIZE
    global INCLUDE_CUT_TRACE
    args = build_parser().parse_args(argv)

    X_LIMITS = _pair(args.x_min, args.x_max, "Volume range")
    UV_Y_LIMITS = _pair(args.uv_min, args.uv_max, "UV range")
    if args.include_cut:
        INCLUDE_CUT_TRACE = True
    if args.fraction_label_y is not None:
        FRACTION_LABEL_Y = args.fraction_label_y
    if args.dpi is not None:
        FIGURE_DPI = args.dpi
    if args.width is not None or args.height is not None:
        FIGURE_SIZE = (
            args.width if args.width is not None else FIGURE_SIZE[0],
            args.height if args.height is not None else FIGURE_SIZE[1],
        )

    if args.csv:
        csv_path = Path(args.csv).expanduser().resolve()
        if not csv_path.is_file():
            raise SystemExit(f"CSV not found: {csv_path}")
        out_dir = Path(args.outdir).expanduser().resolve() if args.outdir else csv_path.parent
        log_lines = []
        try:
            analyse_file(csv_path, log_lines, out_dir)
            log_message("All processing completed.", log_lines)
        finally:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "log.md").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    else:
        main(args.outdir)


if __name__ == "__main__":
    cli()

