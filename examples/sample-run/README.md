# Sample run

A complete `audit` run for a fictional Next.js site, `studio-site`, so you can see what ship-site produces before you install it.

- Inputs (what the audits and gates write): [`findings/`](findings), [`gates.json`](gates.json), [`state.json`](state.json)
- Outputs (written by `build_report.py`): [`report.md`](report.md), [`plan.md`](plan.md), [`findings.json`](findings.json)

Rebuild the outputs from the inputs:

```bash
python3 skills/ship-site/scripts/build_report.py examples/sample-run --title "studio-site v1.4.0"
```

All hosts are `example.com`; screenshots and logs referenced in the evidence are not included.
