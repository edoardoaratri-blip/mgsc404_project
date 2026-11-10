# Data formats between the code modules

**Status:** v0.2, matches the code in `src/` as of 2026-11-09. Change it only by agreement and log the change at the bottom.

**Why this file matters.** These files are the only contact points between the scripts. If every script follows them, each part can be written, tested and rerun on its own.

```
workbook ──► loader.py ──► approach_a.py ──┬──► candidates_<instance>.json ──► heuristic.py ──► plan_heuristic_<instance>.json
                                           │                               └─► ltl_reasons.py
                                           └──► plan_<instance>.json ──► checker.py ──► check_<instance>.json
                                                                     └─► results.py ──► results_<instance>.md / figures
```

The checker reads **only** a plan and the workbook. It never imports `loader.py`, `approach_a.py` or any other project script.

## General conventions

| Item | Convention |
|---|---|
| File type | JSON, UTF-8 |
| `<instance>` | `simplified` or `main` |
| Location | `outputs/`; what-if runs (one rule switched off) go to `outputs/whatif/` with the rule in the name, e.g. `plan_main_no_lifo.json` |
| Times | **hour of the day** as a decimal on the 0.25 grid (8.5 = 08:30), together with the `day` field. Absolute time = 24 × day + hour (rules R0.2). |
| Durations | hours, decimal, 0.25 grid |
| Distances | miles |
| Money | CAD, rounded to 2 decimals |
| IDs | exactly as in the workbook (`S001`, `T01`, `D01`, `F03`) |
| Event types | `"P"` = pickup, `"D"` = delivery |

---

## 1. Candidate tours: `outputs/candidates_<instance>.json`

Written by `approach_a.py`, read by `heuristic.py` and `ltl_reasons.py`. Every candidate has already passed every rule in `rules.md`, uses the cheapest stop order for its shipments and tractor type, and costs less than sending its shipments by LTL.

```json
{
  "instance": "simplified",
  "workbook": "data/project1_simplified.xlsx",
  "enumeration": "complete up to 3 shipments per tour",
  "relaxation": "none",
  "ltl_cost": {"S001": 1397.25, "S002": 1345.5},
  "feasible_shipments": ["S001", "S002"],
  "dedicated_cost": {"S001": 900.0},
  "profiles": [
    {"profile": 0, "depot_id": "D01", "equipment_id": "DRY", "tractor_ids": ["T01", "T02", "T03", "T04"]}
  ],
  "candidates": [
    {"tour_id": 92, "day": 1, "profile": 0, "shipments": ["S009", "S014"],
     "events": ["... same structure as in the plan, below ..."],
     "departure": 7.0, "return": 17.0, "miles": 382, "drive_hours": 8.0, "duty_hours": 10.0, "cost_cad": 1000.0}
  ]
}
```

| Field | Meaning |
|---|---|
| `ltl_cost` | LTL cost of every shipment (rules R5.1) |
| `feasible_shipments` | shipments that appear in at least one feasible tour, at any cost (used by `ltl_reasons.py`) |
| `dedicated_cost` | cheapest feasible tour carrying the shipment alone, at any cost |
| `profiles` | tractor types: tractors with the same depot, equipment and shift are interchangeable (rules R7.3) |
| `candidates[].profile` | which tractor type drives the tour; the tractor ID is chosen when the plan is built |

---

## 2. Plan: `outputs/plan_<instance>.json` (Gurobi) and `outputs/plan_heuristic_<instance>.json`

Written by `approach_a.py` and by `heuristic.py` in the same format, read by `checker.py` and `results.py`. This is the deliverable the project instructions ask for: the shipments on each tour, their order, the tractor, the times and the cost.

```json
{
  "instance": "simplified",
  "workbook": "data/project1_simplified.xlsx",
  "summary": {"status": "OPTIMAL", "total_cost": 36246.15, "all_ltl_baseline": 93298.35, "savings_pct": 61.15,
              "...": "more results, see below"},
  "solver_per_day": [
    {"day": 1, "status": "OPTIMAL", "objective": 11921.4, "mip_gap": 0.0, "runtime_s": 0.01,
     "variables": 556, "constraints": 28, "candidate_tours": 134}
  ],
  "tours": [
    {
      "tour_id": 92, "day": 1, "tractor_id": "T01", "depot_id": "D01", "equipment_id": "DRY",
      "shipments": ["S009", "S014"],
      "events": [
        {"seq": 1, "type": "P", "shipment_id": "S014", "location_id": "F01",
         "arrival": 8.0, "service_start": 8.0, "service_end": 8.5, "break_after": false},
        {"seq": 2, "type": "P", "shipment_id": "S009", "location_id": "F11",
         "arrival": 9.25, "service_start": 9.25, "service_end": 9.75, "break_after": false}
      ],
      "departure": 7.0, "return": 17.0, "miles": 382, "drive_hours": 8.0, "duty_hours": 10.0, "cost_cad": 1000.0
    }
  ],
  "ltl": [
    {"shipment_id": "S007", "cost_cad": 2375.9}
  ]
}
```

**Field rules**
- Every shipment of the workbook appears **exactly once**: inside one tour's `shipments`, or in `ltl` (constraint M1).
- `tractor_id` is a real tractor ID, used at most once per day (constraint M2).
- `events` are in driving order, `seq` from 1. `break_after: true` (main file only) means a 0.5 h break starts at that event's `service_end`.
- `depot_id` and `equipment_id` are copied for readability. **The checker looks them up from `tractor_id` in the workbook and treats a mismatch as an error.**
- `summary.total_cost` = sum of tour `cost_cad` + sum of LTL `cost_cad`.
- `summary` (Gurobi plan) also holds: `relaxation`, `gurobi_version`, `status`, `objective`, `max_mip_gap`, `runtime_s` (Gurobi solve time), `total_runtime_s` (whole run), `candidate_tours`, `complete_enumeration`, `all_triples`, `tl_cost`, `ltl_cost`, `savings`, `n_tours`, `tours_by_size`, the shipment counts (`n_shipments_ltl`, `n_shipments_dedicated`, `n_shipments_consolidated`), utilization, `total_tour_miles` and extra time. The heuristic plan has `method` instead of the Gurobi fields and no `solver_per_day`.

---

## 3. Checker report: `outputs/check_<plan name>.json`

Written by `checker.py`, next to the plan it checked (`plan_simplified.json` → `check_simplified.json`, `plan_heuristic_main.json` → `check_heuristic_main.json`). The checker **recomputes everything from the workbook**: loads, times, miles, driving, duty, costs and LTL rates. It never trusts the numbers written in the plan; it only compares against them.

```json
{
  "plan_file": "outputs/plan_simplified.json",
  "verdict": "ACCEPT",
  "n_violations": 0,
  "violations": [
    {"code": "CAPACITY_PALLETS", "rule": "R3.1", "tour_id": 172, "seq": 3, "detail": "28 pallets > 26"}
  ],
  "recomputed": {"tl_cost": 24400.0, "ltl_cost": 11846.15, "total_cost": 36246.15, "n_tours": 24, "n_ltl": 8}
}
```

`verdict` is `ACCEPT` only if `violations` is empty.

**Violation codes**

| Code | Rule | Meaning |
|---|---|---|
| `SHIPMENT_MISSING` / `SHIPMENT_DUPLICATE` | R1.1 | A shipment is not served, or is served twice |
| `PRECEDENCE` | R1.2 | A delivery comes before its pickup, or an event is missing |
| `WRONG_DAY` | R1.3 | A shipment is on a tour of another day |
| `STOP_LIMIT` | R4.5 | Too many events |
| `CAPACITY_WEIGHT` / `CAPACITY_LENGTH` / `CAPACITY_PALLETS` | R3.1 | Overload after some event |
| `WINDOW` | R2.2, R2.3 | Service starts too early or ends too late |
| `TIME_FLOW` | R1.4, R2.4, R4.1 | Times inconsistent with travel and handling (for example, arrival earlier than possible) |
| `SHIFT_DEPOT` | R2.6 | Departure or return outside the shift or depot hours |
| `DRIVE_LIMIT` / `DUTY_LIMIT` | R4.2, R4.3 | Driving or duty limit exceeded |
| `TRACTOR_DOUBLE_BOOKED` | R4.6 | The same tractor has two tours on one day |
| `EQUIPMENT` | R6.1 | Chilled freight on non-chilled equipment |
| `COMPATIBILITY` | R6.2 | Incompatible shipments on board together |
| `LIFO` | R6.3 | A delivery that is not on top of the stack |
| `BREAK` | R6.4 | More than 8 h of driving since the last break |
| `COST_MISMATCH` | R5 | Recomputed cost differs from the plan by more than CAD 0.01 |

---

## 4. Checker evidence files (project instructions, deliverable 3)

Written by `test_checker.py` to `outputs/tests/`, each with its checker report:

| File | Change from the valid plan | Result |
|---|---|---|
| `plan_valid.json` | none | `ACCEPT` |
| `plan_overload.json` | an LTL shipment added to a tour at facilities the tour already visits, schedule and cost recomputed | REJECT: a CAPACITY_* code (which one depends on the plan), possibly with WINDOW on the added shipment’s pickup.|
| `plan_missed_window.json` | one tour's last delivery starts 15 minutes after its latest possible start | `REJECT`: `WINDOW` only |
| `plan_double_booked.json` | two tours of the same day and depot given the same `tractor_id` | `REJECT`: `TRACTOR_DOUBLE_BOOKED` only |

These four reports are the evidence the project instructions ask for.

---

## Notes

- **Large files.** `candidates_*.json` (about 4 MB on the main file) and `outputs/whatif/` can be recreated in about a minute: keep them out of Git (`.gitignore`). **Do commit** the plans, the checker reports, `outputs/tests/`, the result tables and the figures, because they are deliverables.

## Change log

| Date | Version | Change | Agreed by |
|---|---|---|---|
| 2026-10-27 | 0.1 | First draft | (to approve) |
| 2026-11-09 | 0.2 | Matched to the code: candidate file fields, plan `summary` and `solver_per_day`, heuristic plan, checker report fields, what-if folder, final checker evidence | |
