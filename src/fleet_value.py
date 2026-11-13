# fleet_value.py - what is one more tractor worth? (main file by default)
#
# Run after approach_a.py:   python src/fleet_value.py main
#
# Every tractor already drives every day, so the fleet is what limits consolidation.
# Two ways to measure the value of one more tractor, using the SAME candidate tours as approach_a.py:
#   1. Shadow prices. Solve the LP relaxation (variables between 0 and 1) and read the dual value of
#      constraint C2 ("tours of tractor type p on day d <= number of tractors of type p").
#      It estimates the saving of one more tractor of that type on that day. The real model has binary
#      variables and no shadow prices, so this is an estimate; it is reliable here because the LP
#      relaxation is almost as good as the real model (the gap is printed).
#   2. Exact re-solve. Add one tractor of one type, solve the real (binary) model again, compare costs.
# Writes outputs/fleet_value_<instance>.md

import json
import sys

import gurobipy as gp
from gurobipy import GRB
import pandas as pd

INSTANCE = sys.argv[1] if len(sys.argv) > 1 else "main"
data = json.load(open(f"outputs/candidates_{INSTANCE}.json"))
ltl_cost = data["ltl_cost"]
profiles = data["profiles"]
tours = data["candidates"]

day_of = {}
for row in pd.read_excel(data["workbook"], "shipments").itertuples():
    day_of[row.shipment_id] = row.day
days = sorted(set(day_of.values()))

# ---------------- 1. LP relaxation: shadow prices of C2 ----------------
lp_total = 0.0
mip_total = 0.0
shadow = {}                                   # (profile, day) -> CAD saved by one more tractor
for d in days:
    day_I = [i for i in ltl_cost if day_of[i] == d]
    day_Q = [t for t in tours if t["day"] == d]
    for relax in (False, True):
        m = gp.Model()
        m.Params.OutputFlag = 0
        kind = GRB.CONTINUOUS if relax else GRB.BINARY
        x = {}
        for t in day_Q:
            x[t["tour_id"]] = m.addVar(vtype=kind, ub=1)
        y = {}
        for i in day_I:
            y[i] = m.addVar(vtype=kind, ub=1)
        m.setObjective(gp.quicksum(t["cost_cad"] * x[t["tour_id"]] for t in day_Q)
                       + gp.quicksum(ltl_cost[i] * y[i] for i in day_I), GRB.MINIMIZE)
        for i in day_I:                                                       # C1
            m.addConstr(y[i] + gp.quicksum(x[t["tour_id"]] for t in day_Q if i in t["shipments"]) == 1)
        c2 = {}
        for p in profiles:                                                    # C2
            terms = [x[t["tour_id"]] for t in day_Q if t["profile"] == p["profile"]]
            if terms:
                c2[p["profile"]] = m.addConstr(gp.quicksum(terms) <= len(p["tractor_ids"]))
        m.optimize()
        if relax:
            lp_total += m.ObjVal
            for pi, con in c2.items():
                shadow[(pi, d)] = -con.Pi     # Pi <= 0 on a "<=" constraint of a minimisation
        else:
            mip_total += m.ObjVal

# ---------------- 2. exact re-solve with one more tractor of each type ----------------
exact = {}
for p in profiles:
    total = 0.0
    for d in days:
        day_I = [i for i in ltl_cost if day_of[i] == d]
        day_Q = [t for t in tours if t["day"] == d]
        m = gp.Model()
        m.Params.OutputFlag = 0
        m.Params.MIPGap = 0.0
        x = {}
        for t in day_Q:
            x[t["tour_id"]] = m.addVar(vtype=GRB.BINARY)
        y = {}
        for i in day_I:
            y[i] = m.addVar(vtype=GRB.BINARY)
        m.setObjective(gp.quicksum(t["cost_cad"] * x[t["tour_id"]] for t in day_Q)
                       + gp.quicksum(ltl_cost[i] * y[i] for i in day_I), GRB.MINIMIZE)
        for i in day_I:
            m.addConstr(y[i] + gp.quicksum(x[t["tour_id"]] for t in day_Q if i in t["shipments"]) == 1)
        for q in profiles:
            terms = [x[t["tour_id"]] for t in day_Q if t["profile"] == q["profile"]]
            extra = 1 if q["profile"] == p["profile"] else 0
            if terms:
                m.addConstr(gp.quicksum(terms) <= len(q["tractor_ids"]) + extra)
        m.optimize()
        total += m.ObjVal
    exact[p["profile"]] = mip_total - total

# ---------------- report ----------------
lines = [f"# Value of one more tractor: {INSTANCE} file", "",
         f"Real plan (binary model): CAD {mip_total:,.2f}. LP relaxation: CAD {lp_total:,.2f} "
         f"(gap CAD {mip_total - lp_total:,.2f}, {100 * (mip_total - lp_total) / mip_total:.3f}%).", "",
         "Saving per week from ONE more tractor of each type (same candidate tours). "
         "Shadow price = LP estimate; exact = binary model solved again with the extra tractor.", "",
         "| Depot | Equipment | Shift (as) | Tractors now | Shadow price (CAD/week) | Exact saving (CAD/week) |",
         "|---|---|---|---|---|---|"]
ranked = sorted(profiles, key=lambda p: -exact[p["profile"]])
for p in ranked:
    week_shadow = sum(shadow.get((p["profile"], d), 0.0) for d in days)
    lines.append(f"| {p['depot_id']} | {p['equipment_id']} | {p['tractor_ids'][0]} | {len(p['tractor_ids'])} | "
                 f"{week_shadow:,.2f} | {exact[p['profile']]:,.2f} |")
best = ranked[0]
lines += ["", f"Best place for one more tractor: {best['depot_id']} {best['equipment_id']} "
          f"(shift as {best['tractor_ids'][0]}), CAD {exact[best['profile']]:,.2f} per week."]

out = f"outputs/fleet_value_{INSTANCE}.md"
open(out, "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
print(f"\nTable written to {out}")
