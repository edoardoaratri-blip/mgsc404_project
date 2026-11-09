# Code

Run every command from the repository folder (`mgsc404_project`), in this order.
Add `main` at the end of a command for the main file.

| Step | Command | What it does | Expected result (simplified) |
| 1 | `python src/loader.py` | Reads the workbook, computes LTL costs, checks the data | all-LTL baseline CAD 93,298.35 |
| 2 | `python src/approach_a.py` | Builds every feasible tour, Gurobi selects, writes `outputs/plan_simplified.json` | total CAD 36,246.15, savings 61.2% |
| 3 | `python src/checker.py outputs/plan_simplified.json` | Independent check of the plan, writes `outputs/check_simplified.json` | ACCEPT, 0 violations |
| 4 | `python src/test_checker.py` | Builds three broken plans in `outputs/tests/` and shows the checker rejects them | All checker tests passed |

Main file: `python src/approach_a.py main`, then `python src/checker.py outputs/plan_main.json`
(expected: CAD 1,140,762.95, savings 26.8%, ACCEPT).

Requirements: `pip install pandas openpyxl gurobipy` and a Gurobi academic licence
(the free pip licence is limited to 2,000 variables).

| File | Role |
| `loader.py` | Data: one dictionary per sheet, LTL cost per shipment, data checks |
| `approach_a.py` | Stop orders, evaluator (all rules of `docs/rules.md`), candidate tours, one Gurobi model per day, plan export, results summary, route printout |
| `checker.py` | Independent checker: reads only the plan and the workbook, recomputes everything |
| `test_checker.py` | Evidence for the checker: valid, overload, missed window, double-booked tractor |
