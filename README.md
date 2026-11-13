# MGSC 404 Project 1: consolidating LTL shipments into truckload tours

For each day, every shipment either goes alone by LTL or rides on one of our tractors, possibly together with
other shipments. We minimise total cost in two steps (Approach A):

1. **Generate:** Python builds every feasible tour (1 to 3 shipments on the simplified file, 1 to 4 on the main
   file), simulating each one stop by stop against every rule in `docs/rules.md`.
2. **Select:** a Gurobi set-partitioning model, one per day, picks the cheapest combination of tours so that
   every shipment is served exactly once and no tractor drives more than one tour per day.

An independent checker re-verifies every plan from the workbook.

## Results

| | Simplified | Main |
|---|---|---|
| All-LTL baseline (CAD) | 93,298.35 | 1,557,535.85 |
| Gurobi plan (CAD) | **36,246.15** (61.2% saving) | **1,140,762.95** (26.8% saving) |
| Savings heuristic (CAD) | 36,349.65 | 1,158,522.70 |
| Optimality | global optimum | optimal over the generated tours (every 1-, 2- and 3-shipment tour) |
| Checker | ACCEPT, 0 violations | ACCEPT, 0 violations |

## How to run

Requirements: Python 3, `pip install pandas openpyxl matplotlib gurobipy`, and a Gurobi academic licence.
Run everything from this folder:

```
python src/loader.py
python src/approach_a.py
python src/checker.py outputs/plan_simplified.json
python src/test_checker.py
python src/heuristic.py
python src/checker.py outputs/plan_heuristic_simplified.json
python src/ltl_reasons.py
python src/results.py

python src/loader.py main
python src/approach_a.py main
python src/checker.py outputs/plan_main.json
python src/heuristic.py main
python src/checker.py outputs/plan_heuristic_main.json
python src/ltl_reasons.py main
python src/results.py main
python src/rule_effects.py
python src/fleet_value.py main
```

`src/README.md` explains each step and its expected result.

## Folders

| Folder | Content |
|---|---|
| `data/` | The two course workbooks |
| `docs/` | `rules.md` (how we read every rule), `formats.md` (file formats between the scripts) |
| `src/` | The code |
| `outputs/` | Plans, checker reports, result tables and charts; `outputs/tests/` holds the checker evidence, `outputs/whatif/` the what-if runs |
