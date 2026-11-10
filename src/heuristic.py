# greedy savings heuristic, used as the comparison required by the project
#
# The rules, stated so that someone else can rerun them by hand:
#   Candidate tours  The same feasible tours Gurobi chooses from:
#                    every tour already passes every rule contained in rules.md, uses the cheapest stop order
#                    for its shipments and tractor type, and costs less than sending its shipments by LTL.
#   Pairing rule     savings(tour) = sum of the LTL costs of its shipments, truckload cost of the tour.
#                    Consider tours from the largest savings to the smallest.
#   Selection rule   Take a tour if (a) none of its shipments is already on a selected tour and
#                    (b) its tractor type still has a free tractor on that day. Otherwise skip it.
#   Timing rule      Each selected tour keeps the evaluator's schedule (leave as early as needed,
#                    shortest duty). Tractors of the same type are interchangeable; they are numbered
#                    in the order their tours are selected.
#   Tie-breaking     Equal savings: fewer miles first, then the lower tour_id. The result is therefore
#                    identical on every rerun.
#   Leftovers        Every shipment not on a selected tour goes by LTL.

import json
import os
import sys
import time

INSTANCE = sys.argv[1] if len(sys.argv) > 1 else "simplified"
cand_file = f"outputs/candidates_{INSTANCE}.json"
if not os.path.exists(cand_file):
    raise SystemExit(f"{cand_file} not found: run  python src/approach_a.py {INSTANCE}  first.")
data = json.load(open(cand_file))

ltl_cost = data["ltl_cost"]                      # shipment -> LTL cost (CAD)
profiles = data["profiles"]                      # tractor types: depot, equipment, tractor ids
tours = data["candidates"]
all_ltl = sum(ltl_cost.values())

t_start = time.time()

# pairing rule
for t in tours:
    t["savings"] = sum(ltl_cost[i] for i in t["shipments"]) - t["cost_cad"]
ranked = sorted(tours, key=lambda t: (-t["savings"], t["miles"], t["tour_id"]))

# selection rule
assigned = set()                                 # shipments already on a selected tour
used = {}                                        # (profile, day) -> tractors already used
selected = []
for t in ranked:
    if t["savings"] <= 0:
        break                                    # never happens: the pool must have only positive savings
    if any(i in assigned for i in t["shipments"]):
        continue
    key = (t["profile"], t["day"])
    tractor_ids = profiles[t["profile"]]["tractor_ids"]
    if used.get(key, 0) >= len(tractor_ids):
        continue
    tractor = tractor_ids[used.get(key, 0)]      # next free tractor of this type
    used[key] = used.get(key, 0) + 1
    assigned.update(t["shipments"])
    selected.append((t, tractor))

ltl_ships = sorted(i for i in ltl_cost if i not in assigned)
runtime = time.time() - t_start

# safety-check
served = [i for t, _ in selected for i in t["shipments"]] + ltl_ships
assert sorted(served) == sorted(ltl_cost), "every shipment must be served exactly once"   # every shipment must appear either on one selected tour or on LTL.
# If a future change breaks the selection logic, the script stops here and doesn't write a wrong plan.

# Plan written in the same format as Gurobi's 
# (so that it can be verified by the checker and the results.py file can read both plans using same code)
selected.sort(key=lambda s: (s[0]["day"], s[1]))
plan_tours = []
for t, tractor in selected:
    p = profiles[t["profile"]]
    plan_tours.append(dict(
        tour_id=t["tour_id"], day=t["day"], tractor_id=tractor, depot_id=p["depot_id"],
        equipment_id=p["equipment_id"], shipments=t["shipments"], events=t["events"],
        departure=t["departure"], **{"return": t["return"]}, miles=t["miles"],
        drive_hours=t["drive_hours"], duty_hours=t["duty_hours"], cost_cad=t["cost_cad"]))

tl_total = sum(t["cost_cad"] for t in plan_tours)
ltl_total = sum(ltl_cost[i] for i in ltl_ships)
total = tl_total + ltl_total
summary = dict(
    instance=INSTANCE, method="greedy savings heuristic", candidate_tours=len(tours),
    runtime_s=round(runtime, 3), all_ltl_baseline=round(all_ltl, 2), tl_cost=round(tl_total, 2),
    ltl_cost=round(ltl_total, 2), total_cost=round(total, 2), savings=round(all_ltl - total, 2),
    savings_pct=round(100 * (all_ltl - total) / all_ltl, 2), n_tours=len(plan_tours),
    n_shipments_ltl=len(ltl_ships),
    n_shipments_dedicated=sum(1 for t in plan_tours if len(t["shipments"]) == 1),
    n_shipments_consolidated=sum(len(t["shipments"]) for t in plan_tours if len(t["shipments"]) > 1),
    total_tour_miles=sum(t["miles"] for t in plan_tours))
plan = dict(instance=INSTANCE, workbook=data["workbook"], summary=summary, tours=plan_tours,
            ltl=[dict(shipment_id=i, cost_cad=ltl_cost[i]) for i in ltl_ships])
out_file = f"outputs/plan_heuristic_{INSTANCE}.json"
json.dump(plan, open(out_file, "w"), indent=2)
print(f"Heuristic plan written to {out_file}")

# Comparison table
rows = [("All-LTL", all_ltl, 0, len(ltl_cost), 0, 0, 0)]
rows.append(("Savings heuristic", total, len(plan_tours), len(ltl_ships),
             summary["n_shipments_dedicated"], summary["n_shipments_consolidated"], summary["total_tour_miles"]))
gurobi_file = f"outputs/plan_{INSTANCE}.json"
gurobi_total = None
if os.path.exists(gurobi_file):
    g = json.load(open(gurobi_file))["summary"]
    gurobi_total = g["total_cost"]
    rows.append(("Gurobi (Approach A)", gurobi_total, g["n_tours"], g["n_shipments_ltl"],
                 g["n_shipments_dedicated"], g["n_shipments_consolidated"], g["total_tour_miles"]))

lines = [f"# Comparison: {INSTANCE} file", "",
         "| Method | Total cost (CAD) | Savings vs all-LTL (CAD) | Savings (%) | Tours | "
         "Shipments on LTL | Dedicated | Consolidated | Tour miles |",
         "|---|---|---|---|---|---|---|---|---|"]
for name, cost, n_t, n_l, n_d, n_c, mi in rows:
    lines.append(f"| {name} | {cost:,.2f} | {all_ltl - cost:,.2f} | {100 * (all_ltl - cost) / all_ltl:.1f} | "
                 f"{n_t} | {n_l} | {n_d} | {n_c} | {mi:,.0f} |")
if gurobi_total is not None:
    gap = total - gurobi_total
    lines += ["", f"Gurobi saves CAD {gap:,.2f} more than the heuristic "
                  f"({100 * gap / total:.1f}% of the heuristic's cost). Both use the same candidate tours, "
                  f"so the difference comes only from choosing the best combination instead of the "
                  f"best tour first."]
    g_tours = {tuple(sorted(t["shipments"])) for t in json.load(open(gurobi_file))["tours"]}
    h_tours = {tuple(sorted(t["shipments"])) for t in plan_tours}
    lines.append(f"Tours in both plans: {len(g_tours & h_tours)}; only in Gurobi's: {len(g_tours - h_tours)}; "
                 f"only in the heuristic's: {len(h_tours - g_tours)}.")
open(f"outputs/comparison_{INSTANCE}.md", "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
print(f"\nComparison written to outputs/comparison_{INSTANCE}.md")