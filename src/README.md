# Code

Run every command from the repository folder (`mgsc404_project`), in this order.
Without an argument a script uses the simplified file; add `main` for the main file.

| Step | Command | What it does | Expected result (simplified / main) |
|---|---|---|---|
| 1 | `python src/loader.py` | Reads the workbook, computes LTL costs, checks the data | all-LTL baseline CAD 93,298.35 / 1,557,535.85 |
| 2 | `python src/approach_a.py` | Builds every feasible tour, Gurobi selects, writes `outputs/plan_<file>.json` | CAD 36,246.15 (61.2%) / 1,140,762.95 (26.8%) |
| 3 | `python src/checker.py outputs/plan_simplified.json` | Independent check of the plan, writes `outputs/check_<file>.json` | ACCEPT, 0 violations |
| 4 | `python src/test_checker.py` | Builds one valid and three broken plans in `outputs/tests/` and runs the checker on each (simplified only) | All checker tests passed |
| 5 | `python src/heuristic.py` | Savings heuristic on the same candidate tours, compared with Gurobi | heuristic CAD 36,349.65 / 1,158,522.70 |
| 6 | `python src/checker.py outputs/plan_heuristic_simplified.json` | Independent check of the heuristic plan | ACCEPT, 0 violations |
| 7 | `python src/ltl_reasons.py` | Why each shipment stays on LTL | `outputs/ltl_reasons_<file>.md` |
| 8 | `python src/results.py` | Results tables and charts | `outputs/results_<file>.md`, PNG charts |
| 9 | `python src/rule_effects.py` | Main file only (about 2 to 5 minutes): re-solves with one rule switched off at a time, plus the waiting-as-break alternative | LIFO costs most, CAD 24,764.65 |
| 10 | `python src/fleet_value.py main` | Main file only: value of one more tractor of each type (shadow prices and exact re-solve) | best: D03 DRY, about CAD 15,000 per week |

Requirements: `pip install pandas openpyxl matplotlib gurobipy` and a Gurobi academic licence
(the free pip licence is limited to 2,000 variables). The published outputs were produced with Gurobi 13.0.3:
a different Gurobi version gives the same costs but may pick a different plan with the same cost.

| File | Role |
|---|---|
| `loader.py` | Data: one dictionary per sheet, LTL cost per shipment, data checks |
| `approach_a.py` | Stop orders, evaluator (all rules of `docs/rules.md`), candidate tours, one Gurobi model per day, plan export, results summary, route printout. A second argument runs a what-if (`no_lifo`, `no_compat`, `no_reefer`, `no_hours`, `no_break`, `wait_break`) into `outputs/whatif/` |
| `checker.py` | Independent checker: reads only the plan and the workbook, recomputes everything, rejects malformed plans with a reason |
| `test_checker.py` | Evidence for the checker: valid, overload, missed window, double-booked tractor |
| `heuristic.py` | Greedy savings heuristic on the same candidate tours |
| `ltl_reasons.py` | Classifies every LTL shipment by reason |
| `results.py` | Results tables and charts |
| `rule_effects.py` | What each main-file rule costs, and what counting waiting as the break would save |
| `fleet_value.py` | What one more tractor of each type would save per week |
