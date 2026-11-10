# ltl_reasons.py - which shipments stay on LTL, and why?
#
# Every shipment the Gurobi plan leaves on LTL gets exactly one of three reasons, tested in this order:
#   A  No feasible truck tour   No tractor can carry it, not even alone, without breaking a rule.
#   B  Truck never cheaper      Some truck tour is feasible, but every one costs more than its LTL price, so a truck would lose money.
#   C  Better use of tractors   A truck tour cheaper than LTL existed, but Gurobi used the tractors for combinations that save more in total.

import json

from loader import *          # INSTANCE, shipments, hours, drive, tractors, equipment, rule

cand = json.load(open(f"outputs/candidates_{INSTANCE}.json"))
plan = json.load(open(f"outputs/plan_{INSTANCE}.json"))
ltl_cost = cand["ltl_cost"]
feasible = set(cand["feasible_shipments"])
dedicated = cand["dedicated_cost"]
profiles = cand["profiles"]

# candidate tours (all cheaper than LTL) that contain each shipment
tours_with = {}
for t in cand["candidates"]:
    for i in t["shipments"]:
        tours_with.setdefault(i, []).append(t)

# what the plan used: tractors per (tractor type, day)
tractor_profile = {k: p["profile"] for p in profiles for k in p["tractor_ids"]}
used = {}
for t in plan["tours"]:
    key = (tractor_profile[t["tractor_id"]], t["day"])
    used[key] = used.get(key, 0) + 1


def why_no_tour(i):
    """Which rule stops a dedicated tour for shipment i?
    Each tractor type is checked with the earliest possible schedule; the first rule it breaks is
    recorded. Returns those reasons with how many tractor types hit each one."""
    s = shipments[i]
    o, d = s["origin_id"], s["destination_id"]
    first_failure = {}
    for p in profiles:
        t0 = tractors[p["tractor_ids"][0]]
        eq = equipment[p["equipment_id"]]
        dep_open = max(t0["shift_start_hour"], hours[p["depot_id"]][0])
        back_by = min(t0["shift_end_hour"], hours[p["depot_id"]][1])
        if s["temperature"] == "chilled" and int(eq["chilled_capable"]) != 1:
            why = "needs a refrigerated tractor"
        elif (s["weight_lb"] > eq["weight_capacity_lb"] or s["linear_feet"] > eq["length_capacity_feet"]
              or s["pallets"] > eq["pallet_capacity"]):
            why = "too large for the trailer"
        else:
            d1, d2, d3 = drive[(p["depot_id"], o)], drive[(o, d)], drive[(d, p["depot_id"])]
            p_lo = max(s["pickup_open_hour"], hours[o][0])
            p_hi = min(s["pickup_close_hour"], hours[o][1]) - s["pickup_service_hours"]
            q_lo = max(s["delivery_open_hour"], hours[d][0])
            q_hi = min(s["delivery_close_hour"], hours[d][1]) - s["delivery_service_hours"]
            start_p = max(dep_open + d1, p_lo)
            start_d = max(start_p + s["pickup_service_hours"] + d2, q_lo)
            ret = start_d + s["delivery_service_hours"] + d3
            depart = max(dep_open, start_p - d1)            # leave as late as possible: no waiting at pickup
            if start_p > p_hi:
                why = "pickup window closes before a tractor can get there"
            elif start_d > q_hi:
                why = "delivery window closes before the load can get there"
            elif ret > back_by:
                why = "tractor cannot be back at the depot before its shift/depot closes"
            elif d1 + d2 + d3 > rule["max_drive_hours"]:
                why = "round trip exceeds the driving limit"
            elif ret - depart > rule["max_duty_hours"]:
                why = "round trip exceeds the duty limit"
            else:
                why = "other timing combination (break or waiting)"
        first_failure[why] = first_failure.get(why, 0) + 1
    # a chilled shipment can only ride a refrigerated tractor: report why THOSE tractors fail
    if len(first_failure) > 1:
        first_failure.pop("needs a refrigerated tractor", None)
    ranked = sorted(first_failure.items(), key=lambda kv: (-kv[1], kv[0]))
    return "; ".join(f"{why} ({n} tractor type{'s' if n > 1 else ''})" for why, n in ranked)


rows = []
for item in sorted(plan["ltl"], key=lambda x: x["shipment_id"]):
    i = item["shipment_id"]
    s = shipments[i]
    if i not in feasible:
        reason = "A: no feasible truck tour"
        detail = "even alone: " + why_no_tour(i)
    elif i not in tours_with:
        reason = "B: truck never cheaper than LTL"
        detail = (f"cheapest dedicated truck CAD {dedicated[i]:,.2f} vs LTL CAD {ltl_cost[i]:,.2f}"
                  if i in dedicated else "feasible only together with others, and those tours cost more than LTL")
    else:
        options = tours_with[i]
        best = max(options, key=lambda t: sum(ltl_cost[j] for j in t["shipments"]) - t["cost_cad"])
        best_saving = sum(ltl_cost[j] for j in best["shipments"]) - best["cost_cad"]
        tractors_full = all(used.get((t["profile"], t["day"]), 0) >= len(profiles[t["profile"]]["tractor_ids"])
                            for t in options)
        reason = "C: better use of tractors"
        why = "every tractor that could take it was used for tours saving more" if tractors_full \
            else "its partners were placed on tours saving more"
        detail = f"{len(options)} cheaper-than-LTL tour(s), best would save CAD {best_saving:,.2f}; {why}"
    rows.append((i, s["day"], f"{s['origin_id']}->{s['destination_id']}", ltl_cost[i], reason, detail))

counts = {}
for r in rows:
    counts[r[4]] = counts.get(r[4], 0) + 1

lines = [f"# Shipments left on LTL: {INSTANCE} file", "",
         f"{len(rows)} of {len(ltl_cost)} shipments stay on LTL "
         f"(LTL cost CAD {sum(r[3] for r in rows):,.2f}).", "",
         "| Reason | Shipments | LTL cost (CAD) |", "|---|---|---|"]
for reason in sorted(counts):
    lines.append(f"| {reason} | {counts[reason]} | {sum(r[3] for r in rows if r[4] == reason):,.2f} |")
lines += ["", "| Shipment | Day | Lane | LTL cost (CAD) | Reason | Detail |", "|---|---|---|---|---|---|"]
for i, d, lane, c, reason, detail in rows:
    lines.append(f"| {i} | {d} | {lane} | {c:,.2f} | {reason} | {detail} |")

out = f"outputs/ltl_reasons_{INSTANCE}.md"
open(out, "w").write("\n".join(lines) + "\n")
print("\n".join(lines[:8 + len(counts)]))
if len(rows) <= 20:
    print("\n".join(lines[8 + len(counts):]))
print(f"\nFull table written to {out}")