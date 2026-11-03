# AKTA chromatography analysis

Plot IMAC and size-exclusion runs exported from the AKTA system. Both scripts read the tab-separated CSV that the instrument writes and produce publication-ready figures next to the data file.

## Contents

| File | What it does |
| --- | --- |
| `imac_analysis.py` | UV280 against the Buffer B programme, with fraction markers. Writes `<run>.jpg` and `<run>_Fracs.jpg`. |
| `sec_analysis.py` | Corrected UV280 against conductivity, with fraction markers. Writes `<run>.jpg`. |

## Install

```
pip install -r requirements.txt
```

## Usage

```
python imac_analysis.py run.csv
python imac_analysis.py run.csv --xmax 60 --uv-max 400 --dpi 600
python sec_analysis.py run.csv
python sec_analysis.py run.csv --ymax 40
```

If no file is given, the script uses the only CSV in the current directory, which is the workflow the old notebooks assumed. Pass the path explicitly when there are several.

Common options:

| Option | Default | Meaning |
| --- | --- | --- |
| `csv` | the only CSV in the folder | AKTA export to read |
| `-o`, `--outdir` | folder of the input file | where the figures are written |
| `--dpi` | `1200` | figure resolution |

`imac_analysis.py` also takes `--xmax` (30 mL), `--uv-max` (200 mAU) and `--b-max` (100 %). `sec_analysis.py` takes `--ymax` (30 mAU).

## What the scripts assume about the CSV

The export is tab separated. Rows 1 and 2 are headers, so the data starts at row 3. Columns come in pairs, the first one holding the volume in mL and the second one the measurement.

| Script | Series | Volume column | Value column |
| --- | --- | --- | --- |
| both | UV 280 | 1 | 2 |
| both | Conductivity | 3 | 4 |
| both | Conc B | 5 | 6 |
| `sec_analysis.py` | UV 280 Cut | 13 | 14 |
| `imac_analysis.py` | fractions | 7 | 8 |
| `sec_analysis.py` | fractions | 11 | 12 |

Column numbers are zero based in the code. `sec_analysis.py` subtracts the reference channel from the primary UV280 trace before plotting.

## Figure settings

Times New Roman, bold labels, 20 pt, line width 3.0, 12 × 8 inch figure, horizontal grid only. The IMAC script also writes a version with more fraction labels at higher resolution for checking fraction numbers.
