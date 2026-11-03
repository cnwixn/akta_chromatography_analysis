# AKTA chromatography analysis

Plot IMAC and size-exclusion runs exported from the AKTA system. Two routes
produce the same figures: a small local web interface for interactive work, and
the two Python scripts for batch or scripted runs. The web interface does not
re-implement anything — it sets the parameters on the scripts and calls them.

## Contents

| File | What it does |
| --- | --- |
| `webapp.py` | Local web interface: pick a CSV, set the axes, preview the figures, save them anywhere. |
| `static/index.html` | The page `webapp.py` serves. |
| `imac_analysis.py` | IMAC engine: UV 280 against the Buffer B programme, with fraction markers. |
| `sec_analysis.py` | SEC engine: UV 280 with fraction markers, optionally with the cut trace. |
| `start.bat` | Windows launcher: builds `.venv`, installs the dependencies, opens the page. |
| `requirements.txt` | `matplotlib` and `pandas`. |

Every run writes, next to the CSV (or wherever you point it):

| Output | Contents |
| --- | --- |
| `<run>.jpg` | Clean chromatogram, green fraction ticks, no fraction text. |
| `<run>_noted.jpg` | Same figure with the fraction numbers under the axis. |
| `<run>_data_report.html` | Detected column mapping, the first 20 raw and processed rows, and every fraction. |
| `log.md` | The run log: detected channels, final axis limits, files written. |

## Install

Windows, no setup beyond Python itself: double-click `start.bat`. It creates a
private `.venv`, installs the dependencies and opens
<http://127.0.0.1:8765> in the browser. On a machine without internet, put the
wheel files for matplotlib, pandas and their dependencies in a `wheels/` folder
beside `start.bat`; the launcher installs from there instead.

Any platform:

```
pip install -r requirements.txt
python webapp.py --open
```

Python 3.9 or newer. `python webapp.py --port 9000 --host 0.0.0.0` if you need a
different port or want to reach the page from another machine on the network.

## Web interface

1. Pick `IMAC` or `SEC`.
2. Drop the AKTA CSV on the drop zone, or paste the path of a file that is
   already on the computer.
3. Leave the output folder empty to write the figures beside the CSV, or give a
   folder such as `C:\data\figures`.
4. Everything under *Plot settings* is optional. An empty volume or UV bound
   means "let the script choose it", which is the right choice for the first
   look at a run.
5. Press *Build figures*. The clean and annotated figures appear side by side
   with a download link each, plus the data report and the log.

`Elution window` exists only for IMAC. With both bounds empty the UV axis is
scaled from the whole displayed range, which the first high peak can dominate;
setting the window to the elution interval scales the UV axis from the peaks
that matter.

## Command line

```
python imac_analysis.py run.csv
python imac_analysis.py run.csv -o figures --x-max 60 --uv-max 400 --elution-min 20 --elution-max 55
python sec_analysis.py run.csv --x-min 2.5 --x-max 24 --uv-max 40
python imac_analysis.py
```

Without a CSV argument the script processes every CSV in its own folder, which
is the workflow the old notebooks assumed. With one, only that file is plotted.

| Option | Default | Meaning |
| --- | --- | --- |
| `csv` | every CSV in the folder | AKTA export to read |
| `-o`, `--outdir` | folder of the CSV | where the figures and the log are written |
| `--x-min`, `--x-max` | automatic | volume axis in mL |
| `--uv-min`, `--uv-max` | automatic | UV axis in mAU |
| `--elution-min`, `--elution-max` | none | IMAC only: interval used to scale the UV axis |
| `--b-min`, `--b-max` | `0`, `100` | IMAC only: B-buffer axis in percent |
| `--include-cut` | off | SEC only: also draw the UV 280 cut trace |
| `--fraction-label-y` | `-0.065` | vertical offset of the fraction labels, axes fraction |
| `--dpi` | `300` | figure resolution |
| `--width`, `--height` | `12`, `10` | figure size in inches |

## What the scripts assume about the CSV

The export is tab separated. Rows 1 and 2 are headers, so the data starts at row
3, and columns come in pairs: the first holding the volume in mL, the second the
measurement. The scripts check the header names and units before plotting and
report a mismatch instead of guessing.

| Script | Series | Volume column | Value column |
| --- | --- | --- | --- |
| both | UV 280 | 1 | 2 |
| both | Conductivity | 3 | 4 |
| both | Conc B | 5 | 6 |
| `imac_analysis.py` | fractions | 7 | 8 |
| `sec_analysis.py` | fractions | 11 | 12 |
| `sec_analysis.py` | UV 280 Cut | 13 | 14 |

Column numbers are one based here and zero based in the code. `sec_analysis.py`
plots the primary UV 280 trace and draws the UV 280 cut trace next to it when
`--include-cut` is given; it does not subtract one channel from the other, so
pick the trace you want instead of relying on a subtraction.

## Figure settings

Arial, bold labels, 26 pt, line width 3.5, 12 × 10 inch figure, horizontal grid
only, fraction ticks in dark green. The annotated figure adds the fraction
numbers at 45° below the axis. Export is 300 dpi and tight-cropped; raise `--dpi`
for print.

## Licence

MIT, see [LICENSE](LICENSE).
