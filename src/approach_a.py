# approach_a.py - Approach A: build every feasible tour in Python, then let Gurobi select.
#
# Run from the repository folder:
#     python src/approach_a.py            (simplified file)
#     python src/approach_a.py main       (main file)
#
# Steps (same structure as the team's notebook):
#   1. read the data                      (src/loader.py)
#   2. LTL cost of every shipment         (src/loader.py)  -> all-LTL baseline
#   3. stop orders for a set of shipments
#   4. evaluator: is one stop order feasible for one tractor profile, and what does it cost?
#   5. candidate tour pool Q
#   6. Gurobi selection model (x = tour selected, y = shipment on LTL)
#   7. plan export (outputs/plan_<instance>.json) + summary + route printout
#
# Every rule follows docs/rules.md. Times are handled in integer quarter-hours ("ticks").

import itertools
import json
import os
import time

import gurobipy as gp
from gurobipy import GRB

from loader import *          # INSTANCE, shipments, hours, miles, drive, tractors, equipment,
                              # tl_cost, rule, param, ltl_cost

MAIN = INSTANCE == "main"
TIME_LIMIT = 600              # seconds per Gurobi solve
MIP_GAP = 0.0

# Candidate-pool settings.
# Simplified file: every set of up to 3 shipments is tried, so the pool is complete
# and Gurobi's answer is the global optimum.
# Main file: every single and every pair is tried; sets of 3 and 4 are only built from sets
# whose smaller subsets are all feasible. State this in the report: the main result is
# optimal over this pool. PARTNER_K (optional) keeps only each shipment's K best partners;
# tested at 15 it changes nothing, so it is off.
COMPLETE_ENUMERATION = not MAIN
PARTNER_K = None

# One binary per (tour, tractor) mirrors the handwritten formulation (T_kd).
# On the main file identical tractors are grouped instead (same optimum, fewer variables).
TRACTOR_INDEXED = not MAIN

os.makedirs("outputs", exist_ok=True)


def tk(hours_value):
    """hours -> integer quarter-hour ticks (every time in the data is on the 0.25 h grid)"""
    return int(round(hours_value * 4))


MAX_DRIVE = tk(rule["max_drive_hours"])
MAX_DUTY = tk(rule["max_duty_hours"])
BREAK_AFTER = tk(rule["break_after_drive_hours"])
BREAK_LEN = tk(rule["break_hours"])
MAX_STOPS = int(param["max_stops"])
MAX_N = MAX_STOPS // 2                      # most shipments on one tour
LIFO = int(param["lifo_required"]) == 1

I = sorted(shipments)
D = sorted({shipments[i]["day"] for i in I})
BASELINE = sum(ltl_cost.values())
print(f"Instance: {INSTANCE} | shipments: {len(I)} | days: {D} | all-LTL baseline: CAD {BASELINE:,.2f}")

# ---------------------------------------------------------------------------
# Tractor profiles: tractors with the same depot, equipment and shift are identical.
# ---------------------------------------------------------------------------
PROFILE = {}                                 # (depot, equipment, shift start, shift end) -> [tractor ids]
for k in sorted(tractors):
    t = tractors[k]
    key = (t["home_depot_id"], t["equipment_id"], t["shift_start_hour"], t["shift_end_hour"])
    PROFILE.setdefault(key, []).append(k)
PROF_LIST = list(PROFILE)

PROF = []                                    # everything the evaluator needs, per profile
for depot, eq, s_start, s_end in PROF_LIST:
    e = equipment[eq]
    c = tl_cost[eq]
    PROF.append(dict(
        depot=depot, eq=eq,
        cap=(e["weight_capacity_lb"], e["length_capacity_feet"], e["pallet_capacity"]),
        chilled=int(e["chilled_capable"]) == 1,
        rate=c["linehaul_cad_per_mile"], minimum=c["minimum_linehaul_cad"], stop_fee=c["extra_stop_cad"],
        earliest=tk(max(s_start, hours[depot][0])),        # earliest departure (hour of day)
        latest=tk(min(s_end, hours[depot][1])),            # latest return
    ))
print(f"Tractors: {len(tractors)} in {len(PROF_LIST)} profiles | max stops {MAX_STOPS} | LIFO {LIFO} | "
      f"drive <= {rule['max_drive_hours']} h | duty <= {rule['max_duty_hours']} h | "
      f"break {rule['break_hours']} h after {rule['break_after_drive_hours']} h of driving")

# ---------------------------------------------------------------------------
# Step 3: stop orders. Built once per number of shipments n, on positions 0..n-1.
# Each event is (kind, position): pickup before delivery; strict LIFO when LIFO = True.
# ---------------------------------------------------------------------------
ORDERS = {}
for n in range(1, MAX_N + 1):
    out = []

    def extend(seq, picked, board):
        if len(seq) == 2 * n:
            out.append(tuple(seq))
            return
        for p in range(n):                                   # next event: a pickup
            if p not in picked:
                extend(seq + [("P", p)], picked | {p}, board + [p])
        options = board[-1:] if LIFO else board              # next event: a delivery
        for p in options:
            extend(seq + [("D", p)], picked, [b for b in board if b != p])

    extend([], set(), [])
    ORDERS[n] = out
print("Stop orders per set size:", {n: len(o) for n, o in ORDERS.items()})


# ---------------------------------------------------------------------------
# Step 4: evaluator
# ---------------------------------------------------------------------------
def evaluate(sub, order, pi):
    """Is this stop order feasible for tractor profile pi? Returns the tour dict or None."""
    pr = PROF[pi]
    seq = [(kind, sub[p]) for kind, p in order]
    n_ev = len(seq)
    if n_ev > MAX_STOPS:
        return None

    # capacity after every event (3 dimensions), equipment, compatibility of freight on board
    load = [0.0, 0.0, 0.0]
    board = []
    for kind, i in seq:
        s = shipments[i]
        if kind == "P":
            if s["temperature"] == "chilled" and not pr["chilled"]:
                return None
            for j in board:
                o = shipments[j]
                if o["temperature"] != s["temperature"] or o["compatibility_group"] != s["compatibility_group"]:
                    return None
            board.append(i)
            sign = 1
        else:
            board.remove(i)
            sign = -1
        load[0] += sign * s["weight_lb"]
        load[1] += sign * s["linear_feet"]
        load[2] += sign * s["pallets"]
        if load[0] > pr["cap"][0] or load[1] > pr["cap"][1] or load[2] > pr["cap"][2]:
            return None

    # route, miles, driving
    locs = [pr["depot"]]
    for kind, i in seq:
        locs.append(shipments[i]["origin_id"] if kind == "P" else shipments[i]["destination_id"])
    locs.append(pr["depot"])
    legs = [tk(drive[(a, b)]) for a, b in zip(locs, locs[1:])]
    total_drive = sum(legs)
    if total_drive > MAX_DRIVE:
        return None
    total_miles = sum(miles[(a, b)] for a, b in zip(locs, locs[1:]))

    # earliest start / latest start / service time of every event (hour-of-day ticks)
    lo, hi, svc = [], [], []
    for (kind, i), f in zip(seq, locs[1:-1]):
        s = shipments[i]
        if kind == "P":
            w_open, w_close, sv = s["pickup_open_hour"], s["pickup_close_hour"], s["pickup_service_hours"]
        else:
            w_open, w_close, sv = s["delivery_open_hour"], s["delivery_close_hour"], s["delivery_service_hours"]
        svc.append(tk(sv))
        lo.append(tk(max(w_open, hours[f][0])))
        hi.append(tk(min(w_close, hours[f][1])) - tk(sv))   # latest START so that service ENDS in time

    # break options: none, or 0.5 h after the service of event b (main file only)
    if total_drive <= BREAK_AFTER:
        break_options = [None]
    else:
        break_options = []
        for b in range(n_ev):
            before = sum(legs[: b + 1])                       # depot -> ... -> event b
            after = sum(legs[b + 1:])                         # event b -> ... -> depot
            if before <= BREAK_AFTER and after <= BREAK_AFTER:
                break_options.append(b)

    best = None
    for brk in break_options:
        # forward pass from the earliest departure; waiting is allowed, lateness is not
        t = pr["earliest"]
        starts = []
        cum_wait = 0
        slack = None                                        # how much later we could leave
        ok = True
        for j in range(n_ev):
            t += legs[j]
            start = max(t, lo[j])
            if start > hi[j]:
                ok = False
                break
            cum_wait += start - t
            room = cum_wait + (hi[j] - start)
            slack = room if slack is None else min(slack, room)
            starts.append(start)
            t = start + svc[j] + (BREAK_LEN if brk == j else 0)
        if not ok:
            continue
        ret = t + legs[-1]
        if ret > pr["latest"]:
            continue
        # leaving later removes waiting (duty) without making the return later
        delay = min(slack, cum_wait)
        depart = pr["earliest"] + delay
        duty = ret - depart
        if duty > MAX_DUTY:
            continue
        if best is None or duty < best[0]:
            best = (duty, depart, brk)
    if best is None:
        return None

    duty, depart, brk = best
    # final schedule with the chosen departure
    events = []
    t = depart
    for j, (kind, i) in enumerate(seq):
        t += legs[j]
        start = max(t, lo[j])
        events.append(dict(seq=j + 1, type=kind, shipment_id=i, location_id=locs[j + 1],
                           arrival=t / 4, service_start=start / 4, service_end=(start + svc[j]) / 4,
                           break_after=(brk == j)))
        t = start + svc[j] + (BREAK_LEN if brk == j else 0)
    ret = t + legs[-1]

    cost = max(pr["minimum"], total_miles * pr["rate"]) + pr["stop_fee"] * max(0, n_ev - 2)
    return dict(sub=sub, prof=pi, cost=cost, events=events, departure=depart / 4, ret=ret / 4,
                miles=total_miles, drive_hours=total_drive / 4, duty_hours=(ret - depart) / 4)


# README test case: T01 does S001 + S002 for CAD 1,000 (simplified file only)
if not MAIN:
    test = evaluate(("S001", "S002"), (("P", 0), ("P", 1), ("D", 1), ("D", 0)),
                    PROF_LIST.index(("D01", "DRY", 6, 18)))
    assert test and test["miles"] == 350 and test["cost"] == 1000 and test["drive_hours"] == 7 \
        and test["duty_hours"] == 9 and test["departure"] == 7, test
    print("README test tour: 350 mi, 7 h driving, 9 h duty, departs 07:00, CAD 1,000 -> OK")


# ---------------------------------------------------------------------------
# Step 5: candidate tour pool Q
# For every set and profile keep only the cheapest feasible order (cost does not depend on timing),
# and only if it is cheaper than sending the same shipments by LTL.
# ---------------------------------------------------------------------------
Q = []
feasible_sets = set()               # sets with at least one feasible tour (any profile, any cost)


def build_tours(sub):
    ltl_sum = sum(ltl_cost[i] for i in sub)
    any_feasible = False
    best_cost = None
    for pi in range(len(PROF)):
        best = None
        for order in ORDERS[len(sub)]:
            tour = evaluate(sub, order, pi)
            if tour and (best is None or (tour["cost"], tour["duty_hours"]) < (best["cost"], best["duty_hours"])):
                best = tour
        if best:
            any_feasible = True
            best_cost = best["cost"] if best_cost is None else min(best_cost, best["cost"])
            if best["cost"] < ltl_sum - 1e-6:
                best["day"] = shipments[sub[0]]["day"]
                Q.append(best)
    if any_feasible:
        feasible_sets.add(sub)
    return best_cost


t0 = time.time()
for d in D:
    day_ships = [i for i in I if shipments[i]["day"] == d]
    q_before = len(Q)
    for i in day_ships:                                      # size 1: dedicated tours
        build_tours((i,))
    pair_saving = {i: {} for i in day_ships}
    for a, b in itertools.combinations(day_ships, 2):        # size 2: every pair
        c = build_tours((a, b))
        if c is not None:
            pair_saving[a][b] = pair_saving[b][a] = ltl_cost[a] + ltl_cost[b] - c
    partners = {i: set(pair_saving[i]) for i in day_ships}
    if PARTNER_K:
        top = {i: set(sorted(pair_saving[i], key=pair_saving[i].get, reverse=True)[:PARTNER_K]) for i in day_ships}
        partners = {i: {j for j in pair_saving[i] if j in top[i] or i in top[j]} for i in day_ships}
    for n in range(3, MAX_N + 1):                            # sizes 3 .. MAX_N
        if COMPLETE_ENUMERATION:
            sets_n = itertools.combinations(day_ships, n)
        else:
            prev = sorted(s for s in feasible_sets if len(s) == n - 1 and shipments[s[0]]["day"] == d)
            sets_n = []
            for s in prev:
                common = set.intersection(*(partners[i] for i in s))
                for v in sorted(common):
                    if v <= s[-1]:
                        continue
                    cand = s + (v,)
                    if all(tuple(x for x in cand if x != y) in feasible_sets for y in cand):
                        sets_n.append(cand)
        for sub in sets_n:
            build_tours(sub)
    print(f"day {d}: {len(Q) - q_before} candidate tours ({time.time() - t0:.0f} s so far)")

for k, t in enumerate(Q):
    t["id"] = k
print(f"Candidate tours |Q| = {len(Q)} | by size:",
      {n: sum(1 for t in Q if len(t["sub"]) == n) for n in range(1, MAX_N + 1)})

T_i = {i: [] for i in I}
for t in Q:
    for i in t["sub"]:
        T_i[i].append(t["id"])

# ---------------------------------------------------------------------------
# Step 6: Gurobi selection model
#   x[t,k] = 1 if tractor k runs tour t          (or x[t] with grouped tractors)
#   y[i]   = 1 if shipment i goes by LTL
#   min  sum c_t x[t,k] + sum l_i y_i
#   C1   y_i + sum_{t in T_i} x[t,k] = 1           every shipment served exactly once
#   C2   sum_{t in T_kd} x[t,k] <= 1               one tour per tractor per day
#        (grouped: sum over the profile's tours <= number of tractors in the profile)
#   C3   binary
# ---------------------------------------------------------------------------
# Every shipment and every tour belongs to one day, and C2 is written per day,
# so the model splits into one independent model per day (same optimum, smaller models).
chosen = []                                                     # (tour, tractor id)
ltl_ships = []
per_day = []
for d in D:
    day_I = [i for i in I if shipments[i]["day"] == d]
    day_Q = [t for t in Q if t["day"] == d]

    model = gp.Model(f"consolidation_day{d}")
    model.Params.OutputFlag = 0
    model.Params.TimeLimit = TIME_LIMIT
    model.Params.MIPGap = MIP_GAP

    x = {}
    for t in day_Q:
        ks = PROFILE[PROF_LIST[t["prof"]]] if TRACTOR_INDEXED else [None]
        for k in ks:
            x[t["id"], k] = model.addVar(vtype=GRB.BINARY, name=f"x[{t['id']},{k}]")
    y = {i: model.addVar(vtype=GRB.BINARY, name=f"y[{i}]") for i in day_I}

    model.setObjective(gp.quicksum(Q[tid]["cost"] * var for (tid, k), var in x.items())
                       + gp.quicksum(ltl_cost[i] * y[i] for i in day_I), GRB.MINIMIZE)

    x_of_tour = {}
    for (tid, k), var in x.items():
        x_of_tour.setdefault(tid, []).append(var)
    for i in day_I:                                             # C1
        model.addConstr(y[i] + gp.quicksum(v for tid in T_i[i] for v in x_of_tour[tid]) == 1, name=f"C1[{i}]")
    if TRACTOR_INDEXED:                                         # C2
        for k in sorted(tractors):
            terms = [var for (tid, kk), var in x.items() if kk == k]
            if terms:
                model.addConstr(gp.quicksum(terms) <= 1, name=f"C2[{k},{d}]")
    else:
        for pi, pkey in enumerate(PROF_LIST):
            terms = [x[t["id"], None] for t in day_Q if t["prof"] == pi]
            if terms:
                model.addConstr(gp.quicksum(terms) <= len(PROFILE[pkey]), name=f"C2[{pi},{d}]")

    model.optimize()
    if model.SolCount == 0:
        raise SystemExit(f"Day {d}: no solution found (Gurobi status {model.Status}).")
    status = {GRB.OPTIMAL: "OPTIMAL", GRB.TIME_LIMIT: "TIME_LIMIT"}.get(model.Status, str(model.Status))
    per_day.append(dict(day=d, status=status, objective=round(model.ObjVal, 2), mip_gap=model.MIPGap,
                        runtime_s=round(model.Runtime, 2), variables=model.NumVars,
                        constraints=model.NumConstrs, candidate_tours=len(day_Q)))
    print(f"day {d}: Gurobi {status} | {model.NumVars} variables, {model.NumConstrs} constraints | "
          f"objective CAD {model.ObjVal:,.2f} | gap {model.MIPGap:.4%} | {model.Runtime:.2f} s")

    if TRACTOR_INDEXED:
        for (tid, k), var in x.items():
            if var.X > 0.5:
                chosen.append((Q[tid], k))
    else:
        used = {}
        for (tid, _), var in sorted(x.items()):
            if var.X > 0.5:
                t = Q[tid]
                n_used = used.get(t["prof"], 0)
                chosen.append((t, PROFILE[PROF_LIST[t["prof"]]][n_used]))
                used[t["prof"]] = n_used + 1
    ltl_ships += [i for i in day_I if y[i].X > 0.5]

all_optimal = all(p["status"] == "OPTIMAL" for p in per_day)
objective = sum(p["objective"] for p in per_day)
print(f"Total objective CAD {objective:,.2f} | " + ("all days optimal over the candidate pool" +
      (" (pool is complete, so this is the global optimum)." if COMPLETE_ENUMERATION else " (pool is limited, see settings).")
      if all_optimal else "NOT all days proved optimal (time limit)."))

# ---------------------------------------------------------------------------
# Step 7: plan export, summary, routes
# ---------------------------------------------------------------------------
chosen.sort(key=lambda c: (c[0]["day"], c[1]))
plan_tours = []
for t, k in chosen:
    pr = PROF[t["prof"]]
    plan_tours.append(dict(
        tour_id=t["id"], day=t["day"], tractor_id=k, depot_id=pr["depot"], equipment_id=pr["eq"],
        shipments=list(t["sub"]), events=t["events"], departure=t["departure"], **{"return": t["ret"]},
        miles=t["miles"], drive_hours=t["drive_hours"], duty_hours=t["duty_hours"], cost_cad=round(t["cost"], 2)))

tl_total = sum(t["cost_cad"] for t in plan_tours)
ltl_total = sum(ltl_cost[i] for i in ltl_ships)
total = tl_total + ltl_total

# results the brief asks for
weight_peak, floor_peak, extra = [], [], []
loaded_w = cap_w = loaded_l = cap_l = 0.0
for t in plan_tours:
    cap = equipment[t["equipment_id"]]
    w = l = pw = pl = 0.0
    locs = [t["depot_id"]] + [e["location_id"] for e in t["events"]] + [t["depot_id"]]
    for n_leg, (a, b) in enumerate(zip(locs, locs[1:])):          # mile-weighted load on each leg
        loaded_w += miles[(a, b)] * w
        loaded_l += miles[(a, b)] * l
        cap_w += miles[(a, b)] * cap["weight_capacity_lb"]
        cap_l += miles[(a, b)] * cap["length_capacity_feet"]
        if n_leg < len(t["events"]):
            e = t["events"][n_leg]
            sign = 1 if e["type"] == "P" else -1
            w += sign * shipments[e["shipment_id"]]["weight_lb"]
            l += sign * shipments[e["shipment_id"]]["linear_feet"]
            pw, pl = max(pw, w), max(pl, l)
    weight_peak.append(pw / cap["weight_capacity_lb"])
    floor_peak.append(pl / cap["length_capacity_feet"])
    end = {(e["type"], e["shipment_id"]): e["service_end"] for e in t["events"]}
    for i in t["shipments"]:
        s = shipments[i]
        direct = drive[(s["origin_id"], s["destination_id"])] + s["delivery_service_hours"]
        extra.append(end[("D", i)] - end[("P", i)] - direct)

summary = dict(
    instance=INSTANCE, gurobi_version=".".join(map(str, gp.gurobi.version())),
    status="OPTIMAL" if all_optimal else "NOT ALL OPTIMAL", objective=round(objective, 2),
    max_mip_gap=max(p["mip_gap"] for p in per_day), runtime_s=round(sum(p["runtime_s"] for p in per_day), 2),
    candidate_tours=len(Q), complete_enumeration=COMPLETE_ENUMERATION, partner_k=PARTNER_K,
    all_ltl_baseline=round(BASELINE, 2), tl_cost=round(tl_total, 2), ltl_cost=round(ltl_total, 2),
    total_cost=round(total, 2), savings=round(BASELINE - total, 2),
    savings_pct=round(100 * (BASELINE - total) / BASELINE, 2),
    n_tours=len(plan_tours),
    n_shipments_ltl=len(ltl_ships),
    n_shipments_dedicated=sum(1 for t in plan_tours if len(t["shipments"]) == 1),
    n_shipments_consolidated=sum(len(t["shipments"]) for t in plan_tours if len(t["shipments"]) > 1),
    avg_peak_weight_util=round(sum(weight_peak) / len(weight_peak), 4) if weight_peak else None,
    avg_peak_floor_util=round(sum(floor_peak) / len(floor_peak), 4) if floor_peak else None,
    mile_weighted_weight_util=round(loaded_w / cap_w, 4) if cap_w else None,
    mile_weighted_floor_util=round(loaded_l / cap_l, 4) if cap_l else None,
    total_tour_miles=sum(t["miles"] for t in plan_tours),
    avg_extra_hours_vs_direct=round(sum(extra) / len(extra), 3) if extra else None,
    max_extra_hours_vs_direct=max(extra) if extra else None)

plan = dict(instance=INSTANCE, workbook=path, summary=summary, solver_per_day=per_day, tours=plan_tours,
            ltl=[dict(shipment_id=i, cost_cad=round(ltl_cost[i], 2)) for i in ltl_ships])
out_file = f"outputs/plan_{INSTANCE}.json"
with open(out_file, "w") as f:
    json.dump(plan, f, indent=2)

print()
for key, value in summary.items():
    print(f"  {key}: {value}")
print(f"\nPlan written to {out_file}\n")


def clock(h):
    return f"{int(h):02d}:{int(round((h - int(h)) * 60)):02d}"


for n, t in enumerate(plan_tours, 1):
    ltl_alt = sum(ltl_cost[i] for i in t["shipments"])
    print(f"ROUTE {n} | day {t['day']} | tractor {t['tractor_id']} | depot {t['depot_id']} | {t['shipments']}")
    print(f"   leaves depot {clock(t['departure'])}")
    for e in t["events"]:
        action = "PICK UP" if e["type"] == "P" else "DELIVER"
        print(f"   {action:8} {e['shipment_id']} at {e['location_id']} | arrive {clock(e['arrival'])} | "
              f"service {clock(e['service_start'])}-{clock(e['service_end'])}" + ("  + 30 min break" if e["break_after"] else ""))
    print(f"   back at depot {clock(t['return'])} | {t['miles']} mi | {t['drive_hours']} h driving | "
          f"{t['duty_hours']} h duty | truckload CAD {t['cost_cad']:,.2f} vs LTL CAD {ltl_alt:,.2f}")
print("Shipments left on LTL:", ltl_ships)
