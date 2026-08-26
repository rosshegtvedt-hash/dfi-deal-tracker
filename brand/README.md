# Brand assets, vendored

`rcfh_chart.py` and `rcfh_bathymetric.mplstyle` are copied verbatim from the
`rcfh-advisory-brand` skill. They are vendored here for two reasons:

1. `export_charts.py` must run for anyone who clones this repo, without the
   skill being installed.
2. The skill directory is not resolvable by the Windows Python interpreter on
   this machine, so importing it in place is not an option.

**The skill remains the source of truth.** When it changes, re-copy these
files rather than editing them here. Nothing in this folder should be
modified locally; local deviations belong in `export_charts.py`.
