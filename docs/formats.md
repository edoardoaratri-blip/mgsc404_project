# Data formats between the code modules

**Status:** DRAFT v0.1, to be approved by both coders before the code depends on it. After approval, change it only by agreement and log the change at the bottom.

**Why this file matters.** These two formats are the only contact points between our modules. If both sides follow them, each person can write and test their part alone, at different times, with fake data.

```
workbook ──► loader + evaluator + candidates (Person 1) ──► candidates_<instance>.json
                                                                    │
                                                                    ▼
                                             model.py (Person 2) ──► plan_<instance>.json
                                                                    │
                                    workbook ──► checker.py (Person 2) ──► check_<instance>.json
```

The checker reads **only** the plan and the workbook. It never imports `evaluator.py`, `candidates.py` or `model.py`.

## General conventions

| Item | Convention |
|---|---|
| File type | JSON, UTF-8, written with `json.dump(obj, f, indent=2)` |
| `<instance>` | `simplified` or `main` |
| Location | `outputs/` (the generated files can be large; see the note at the end) |
| Times | **hour of the day** as a decimal on the 0.25 grid (8.5 = 08:30), together with the `day` field. Absolute time = 24 × day + hour (rules R0.2). |
| Durations | hours, decimal, 0.25 grid |
| Distances | miles |
| Money | CAD, rounded to 2 decimals |
| IDs | exactly as in the workbook (`S001`, `T01`, `D01`, `F03`) |
| Event types | `"P"` = pickup, `"D"` = delivery |

---

## 1. Candidate tours: `outputs/candidates_<instance>.json`

Written by `candidates.py` and read by `model.py`. It contains only feasible tours: the evaluator has already checked every rule in `rules.md`.

```json
{
  "instance": "simplified",
  "generated_by": "candidates.py",
  "rules_version": "0.1",
  "enumeration": "complete, up to 3 shipments per tour",
  "tractor_groups": [
    {"group_id": "D01-DRY-6-18", "depot_id": "D01", "equipment_id": "DRY",
     "tractor_ids": ["T01", "T02", "T03", "T04"]}
  ],
  "candidates": [
    {
      "tour_id": "d1-D01-DRY-6-18-000123",
      "day": 1,
      "group_id": "D01-DRY-6-18",
      "shipments": ["S001", "S002"],
      "events": [
        {"seq": 1, "type": "P", "shipment_id": "S001", "location_id": "F01",
         "arrival": 8.0,  "service_start": 8.0,  "service_end": 8.5,  "break_after": false},
        {"seq": 2, "type": "P", "shipment_id": "S002", "location_id": "F02",
         "arrival": 9.5,  "service_start": 9.5,  "service_end": 10.0, "break_after": false},
        {"seq": 3, "type": "D", "shipment_id": "S002", "location_id": "F04",
         "arrival": 12.0, "service_start": 12.0, "service_end": 12.5, "break_after": false},
        {"seq": 4, "type": "D", "shipment_id": "S001", "location_id": "F03",
         "arrival": 13.5, "service_start": 13.5, "service_end": 14.0, "break_after": false}
      ],
      "departure": 7.0,
      "return": 16.0,
      "miles": 350.0,
      "drive_hours": 7.0,
      "duty_hours": 9.0,
      "cost_cad": 1000.0
    }
  ]
}
```

The example is the README tour: D01→F01→F02→F04→F03→D01 on day 1. Under rules R4.4 it departs at 07:00, because any later departure gives the same 9 h duty and ties go to the earliest departure.

**Field rules**
- `tour_id` is unique in the file.
- `shipments` lists each shipment once. The number of shipments is 1 for a dedicated tour and 2 or more for a consolidated one.
- `events` is in driving order, with `seq` starting at 1 and `2 × len(shipments)` events.
- `break_after: true` on at most one event (main file only). It means the 0.5 h break starts at that event's `service_end`.
- `cost_cad` is the full TL cost from rules R5.2. **The model uses this number as is and never recomputes it.**
- If we do not use tractor groups (rules R7.3), replace `group_id` with `tractor_id` and leave out `tractor_groups`.

---

## 2. Plan: `outputs/plan_<instance>.json`

Written by `model.py` and read by `checker.py` and `results.py`. This is the deliverable the brief asks for: "the shipments on each tour, their order, the tractor, the times, and the cost".

```json
{
  "instance": "simplified",
  "workbook": "data/project1_simplified.xlsx",
  "solver": {
    "gurobi_version": "12.0.x",
    "parameters": {"MIPGap": 0.0, "TimeLimit": 600},
    "per_day": [
      {"day": 1, "status": "OPTIMAL", "objective": 0.0, "mip_gap": 0.0,
       "runtime_s": 0.0, "n_candidates": 0}
    ],
    "candidate_set": "complete enumeration up to 3 shipments per tour"
  },
  "tours": [
    {
      "tour_id": "d1-D01-DRY-6-18-000123",
      "day": 1,
      "tractor_id": "T01",
      "depot_id": "D01",
      "equipment_id": "DRY",
      "shipments": ["S001", "S002"],
      "events": [ "... same structure as in the candidates file ..." ],
      "departure": 7.0,
      "return": 16.0,
      "miles": 350.0,
      "drive_hours": 7.0,
      "duty_hours": 9.0,
      "cost_cad": 1000.0
    }
  ],
  "ltl": [
    {"shipment_id": "S003", "cost_cad": 0.0}
  ],
  "totals": {
    "tl_cost_cad": 0.0,
    "ltl_cost_cad": 0.0,
    "total_cost_cad": 0.0,
    "all_ltl_baseline_cad": 93298.35
  }
}
```

The zeros above are placeholders. The example structure is real.

**Field rules**
- Every shipment of the workbook appears **exactly once**, either inside one tour's `shipments` or in `ltl`. This is how the plan expresses M1.
- `tractor_id` is a real tractor ID. A tractor appears in at most one tour per day (M2).
- `depot_id` and `equipment_id` are copied for readability. **The checker must look them up from `tractor_id` in the workbook, and treat a mismatch as an error.**
- `totals.total_cost_cad` = sum of tour `cost_cad` + sum of LTL `cost_cad`, and it must equal the Gurobi objective (within CAD 0.01).

---

## 3. Checker report: `outputs/check_<instance>.json`

Written by `checker.py`. The checker **recomputes everything from the workbook**: loads, times, miles, driving, duty, costs and LTL rates. It never trusts the numbers written in the plan; it only compares against them.

```json
{
  "plan_file": "outputs/plan_simplified.json",
  "verdict": "ACCEPT",
  "n_violations": 0,
  "violations": [
    {"code": "CAPACITY_WEIGHT", "rule": "R3.1", "tour_id": "...", "seq": 2,
     "detail": "load 46000 lb > capacity 45000 lb after event 2"}
  ],
  "recomputed": {"total_cost_cad": 0.0, "matches_plan": true}
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

## 4. Checker evidence files (brief, deliverable 3)

Stored in `outputs/tests/`. Each is a copy of the valid simplified plan with **one** change, made by hand or by a short script:

| File | Change from the valid plan | Expected verdict |
|---|---|---|
| `plan_valid.json` | none | `ACCEPT` |
| `plan_overload.json` | add a heavy shipment to a tour, moving it out of `ltl` and inserting its events, so the weight exceeds capacity | `REJECT` with `CAPACITY_*` |
| `plan_missed_window.json` | shift one tour's times later, so a service ends after its window | `REJECT` with `WINDOW` |
| `plan_double_booked.json` | give two tours of the same day the same `tractor_id` | `REJECT` with `TRACTOR_DOUBLE_BOOKED` |

Keep the checker's output for each one. These four reports are the evidence the brief asks for.

---

## Notes

- **Large files.** On the main file, `candidates_main.json` may be tens of MB. Add `outputs/candidates_*.json` to `.gitignore`: it can be regenerated in a few minutes. **Do commit** the plans, the checker reports and `outputs/tests/`, because they are deliverables.
- **Fake data for testing.** Until the real modules exist, Person 1 can test against a hand-written `plan_valid.json`, and Person 2 can test the model with 3 or 4 hand-written candidates in this format.

## Change log

| Date | Version | Change | Agreed by |
|---|---|---|---|
| 2026-10-27 | 0.1 | First draft | (to approve) |
