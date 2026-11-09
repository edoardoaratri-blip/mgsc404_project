# checker.py - independent checker for an exported plan.
#
# Run from the repository folder:
#     python src/checker.py outputs/plan_simplified.json
#     python src/checker.py outputs/plan_main.json
#
# It reads ONLY the plan file and the workbook named inside it, with its own code.
# It does not import loader.py, approach_a.py or anything else from the project, and it never
# trusts the numbers written in the plan: it recomputes loads, times, miles, driving, duty and
# costs from the workbook and compares. Rules follow docs/rules.md.
# Output: a verdict (ACCEPT / REJECT) and outputs/check_<plan name>.json

import json
import sys
from pathlib import Path

import pandas as pd

plan_file = sys.argv[1] if len(sys.argv) > 1 else "outputs/plan_simplified.json"
plan = json.load(open(plan_file))
wb = plan["workbook"]
TOL_T = 1e-6            # time tolerance (hours)
TOL_C = 0.01            # cost tolerance (CAD)

# ---------------- read the workbook (own code) ----------------
ship = pd.read_excel(wb, "shipments").set_index("shipment_id")
fac = pd.read_excel(wb, "facilities").set_index("facility_id")
dep = pd.read_excel(wb, "depots").set_index("depot_id")
dmat = pd.read_excel(wb, "distance_matrix")
rates = pd.read_excel(wb, "ltl_rates")
tlc = pd.read_excel(wb, "tl_costs").set_index("equipment_id")
eqp = pd.read_excel(wb, "equipment").set_index("equipment_id")
trac = pd.read_excel(wb, "tractors").set_index("tractor_id")
drv_rules = dict(zip(pd.read_excel(wb, "driver_rules")["parameter"], pd.read_excel(wb, "driver_rules")["value"]))
params = dict(zip(pd.read_excel(wb, "parameters")["parameter"], pd.read_excel(wb, "parameters")["value"]))

lane = {(r.from_id, r.to_id): (r.distance_miles, r.drive_hours) for r in dmat.itertuples()}
open_close = {f: (r.open_hour, r.close_hour) for f, r in fac.iterrows()}
open_close.update({d: (r.open_hour, r.close_hour) for d, r in dep.iterrows()})

violations = []


def flag(code, rule_ref, detail, tour_id=None, seq=None):
    violations.append(dict(code=code, rule=rule_ref, tour_id=tour_id, seq=seq, detail=detail))


def leg(a, b):
    if a == b:
        return 0.0, 0.0
    if (a, b) not in lane:
        raise KeyError(f"no distance row {a}->{b}")
    return lane[(a, b)]


def ltl_price(sid):
    s = ship.loc[sid]
    miles_direct = leg(s.origin_id, s.destination_id)[0]
    m = rates[(rates.freight_class == s.freight_class)
              & (rates.weight_from_lb <= s.weight_lb) & (s.weight_lb < rates.weight_to_lb)
              & (rates.distance_from_miles <= miles_direct) & (miles_direct < rates.distance_to_miles)]
    if len(m) != 1:
        raise ValueError(f"{sid}: {len(m)} LTL rate rows")
    return float(m.iloc[0].base_cost_cad * (1 + m.iloc[0].fuel_surcharge_pct))


max_drive = drv_rules["max_drive_hours"]
max_duty = drv_rules["max_duty_hours"]
break_after = drv_rules["break_after_drive_hours"]
break_len = drv_rules["break_hours"]
max_stops = int(params["max_stops"])
lifo = int(params["lifo_required"]) == 1

# ---------------- every shipment exactly once (R1.1) ----------------
served = {}
for t in plan["tours"]:
    for sid in t["shipments"]:
        served.setdefault(sid, []).append(f"tour {t['tour_id']}")
for l in plan["ltl"]:
    served.setdefault(l["shipment_id"], []).append("LTL")
for sid in ship.index:
    if sid not in served:
        flag("SHIPMENT_MISSING", "R1.1", f"{sid} is not served")
    elif len(served[sid]) > 1:
        flag("SHIPMENT_DUPLICATE", "R1.1", f"{sid} served {len(served[sid])} times: {served[sid]}")
for sid in served:
    if sid not in ship.index:
        flag("SHIPMENT_MISSING", "R1.1", f"{sid} in the plan but not in the workbook")

# ---------------- one tour per tractor per day (R4.6) ----------------
seen = {}
for t in plan["tours"]:
    key = (t["tractor_id"], t["day"])
    if key in seen:
        flag("TRACTOR_DOUBLE_BOOKED", "R4.6", f"tractor {t['tractor_id']} has tours {seen[key]} and "
             f"{t['tour_id']} on day {t['day']}", t["tour_id"])
    seen[key] = t["tour_id"]

# ---------------- each tour ----------------
tl_total = 0.0
for t in plan["tours"]:
    tid = t["tour_id"]
    if t["tractor_id"] not in trac.index:
        flag("SHIFT_DEPOT", "R2.6", f"unknown tractor {t['tractor_id']}", tid)
        continue
    tr = trac.loc[t["tractor_id"]]
    depot, eq_id = tr.home_depot_id, tr.equipment_id
    if t.get("depot_id") != depot or t.get("equipment_id") != eq_id:
        flag("SHIFT_DEPOT", "R2.6", f"plan says depot/equipment {t.get('depot_id')}/{t.get('equipment_id')}, "
             f"workbook says {depot}/{eq_id}", tid)
    cap = eqp.loc[eq_id]
    day = t["day"]
    ev = t["events"]

    # structure: pickup before delivery, same day, stop limit, shipments list matches events
    if len(ev) > max_stops:
        flag("STOP_LIMIT", "R4.5", f"{len(ev)} events > {max_stops}", tid)
    pos = {}
    for n, e in enumerate(ev):
        pos.setdefault((e["type"], e["shipment_id"]), []).append(n)
    ev_ships = sorted({e["shipment_id"] for e in ev})
    if ev_ships != sorted(t["shipments"]):
        flag("PRECEDENCE", "R1.2", f"events cover {ev_ships}, tour lists {sorted(t['shipments'])}", tid)
    for sid in ev_ships:
        p, d = pos.get(("P", sid), []), pos.get(("D", sid), [])
        if len(p) != 1 or len(d) != 1 or p[0] > d[0]:
            flag("PRECEDENCE", "R1.2", f"{sid}: pickups {p}, deliveries {d}", tid)
        if sid in ship.index and ship.loc[sid].day != day:
            flag("WRONG_DAY", "R1.3", f"{sid} is a day-{ship.loc[sid].day} shipment on a day-{day} tour", tid)

    # loads, equipment, compatibility, LIFO, after every event
    load = [0.0, 0.0, 0.0]
    stack = []
    for e in ev:
        s = ship.loc[e["shipment_id"]]
        expected_loc = s.origin_id if e["type"] == "P" else s.destination_id
        if e["location_id"] != expected_loc:
            flag("TIME_FLOW", "R1.2", f"{e['shipment_id']} {e['type']} at {e['location_id']}, should be {expected_loc}",
                 tid, e["seq"])
        if e["type"] == "P":
            if s.temperature == "chilled" and int(cap.chilled_capable) != 1:
                flag("EQUIPMENT", "R6.1", f"chilled {e['shipment_id']} on {eq_id}", tid, e["seq"])
            for other in stack:
                o = ship.loc[other]
                if o.temperature != s.temperature or o.compatibility_group != s.compatibility_group:
                    flag("COMPATIBILITY", "R6.2", f"{e['shipment_id']} ({s.temperature}/{s.compatibility_group}) "
                         f"on board with {other} ({o.temperature}/{o.compatibility_group})", tid, e["seq"])
            stack.append(e["shipment_id"])
            sign = 1
        else:
            if lifo and stack and stack[-1] != e["shipment_id"]:
                flag("LIFO", "R6.3", f"delivers {e['shipment_id']} but {stack[-1]} is on top", tid, e["seq"])
            if e["shipment_id"] in stack:
                stack.remove(e["shipment_id"])
            sign = -1
        load = [load[0] + sign * s.weight_lb, load[1] + sign * s.linear_feet, load[2] + sign * s.pallets]
        if load[0] > cap.weight_capacity_lb:
            flag("CAPACITY_WEIGHT", "R3.1", f"{load[0]:.0f} lb > {cap.weight_capacity_lb}", tid, e["seq"])
        if load[1] > cap.length_capacity_feet:
            flag("CAPACITY_LENGTH", "R3.1", f"{load[1]:.0f} ft > {cap.length_capacity_feet}", tid, e["seq"])
        if load[2] > cap.pallet_capacity:
            flag("CAPACITY_PALLETS", "R3.1", f"{load[2]:.0f} pallets > {cap.pallet_capacity}", tid, e["seq"])

    # times, windows, driving, breaks, duty
    t_dep = t["departure"]
    if t_dep < max(tr.shift_start_hour, open_close[depot][0]) - TOL_T:
        flag("SHIFT_DEPOT", "R2.6", f"departs {t_dep} before shift/depot opening", tid)
    clock = t_dep
    here = depot
    total_drive = since_break = total_miles = 0.0
    for e in ev:
        mi, hr = leg(here, e["location_id"])
        total_miles += mi
        total_drive += hr
        since_break += hr
        if since_break > break_after + TOL_T:
            flag("BREAK", "R6.4", f"{since_break} h of driving since the last break", tid, e["seq"])
        clock += hr
        if abs(e["arrival"] - clock) > TOL_T:
            flag("TIME_FLOW", "R4.1", f"arrival {e['arrival']} but travel gives {clock}", tid, e["seq"])
        s = ship.loc[e["shipment_id"]]
        if e["type"] == "P":
            w_open, w_close, svc = s.pickup_open_hour, s.pickup_close_hour, s.pickup_service_hours
        else:
            w_open, w_close, svc = s.delivery_open_hour, s.delivery_close_hour, s.delivery_service_hours
        f_open, f_close = open_close[e["location_id"]]
        start, end = e["service_start"], e["service_end"]
        if start < clock - TOL_T:
            flag("TIME_FLOW", "R2.4", f"service starts {start} before arrival {clock}", tid, e["seq"])
        if abs(end - start - svc) > TOL_T:
            flag("TIME_FLOW", "R1.4", f"service lasts {end - start} h, should be {svc}", tid, e["seq"])
        if start < max(w_open, f_open) - TOL_T or start + svc > min(w_close, f_close) + TOL_T:
            flag("WINDOW", "R2.2", f"service {start}-{start + svc} outside window [{w_open},{w_close}] "
                 f"and hours [{f_open},{f_close}]", tid, e["seq"])
        clock = max(clock, start) + svc
        if e.get("break_after"):
            clock += break_len
            since_break = 0.0
        here = e["location_id"]
    mi, hr = leg(here, depot)
    total_miles += mi
    total_drive += hr
    since_break += hr
    if since_break > break_after + TOL_T:
        flag("BREAK", "R6.4", f"{since_break} h of driving since the last break", tid)
    clock += hr
    if abs(t["return"] - clock) > TOL_T:
        flag("TIME_FLOW", "R4.1", f"return {t['return']} but travel gives {clock}", tid)
    if clock > min(tr.shift_end_hour, open_close[depot][1]) + TOL_T:
        flag("SHIFT_DEPOT", "R2.6", f"returns {clock} after shift/depot closing", tid)
    if total_drive > max_drive + TOL_T:
        flag("DRIVE_LIMIT", "R4.2", f"{total_drive} h driving > {max_drive}", tid)
    if clock - t_dep > max_duty + TOL_T:
        flag("DUTY_LIMIT", "R4.3", f"{clock - t_dep} h duty > {max_duty}", tid)

    # cost
    c = tlc.loc[eq_id]
    cost = max(c.minimum_linehaul_cad, total_miles * c.linehaul_cad_per_mile) + c.extra_stop_cad * max(0, len(ev) - 2)
    tl_total += cost
    if abs(cost - t["cost_cad"]) > TOL_C or abs(total_miles - t["miles"]) > TOL_T:
        flag("COST_MISMATCH", "R5.2", f"plan {t['miles']} mi / CAD {t['cost_cad']}, "
             f"recomputed {total_miles} mi / CAD {cost:.2f}", tid)

ltl_total = 0.0
for l in plan["ltl"]:
    price = ltl_price(l["shipment_id"])
    ltl_total += price
    if abs(price - l["cost_cad"]) > TOL_C:
        flag("COST_MISMATCH", "R5.1", f"{l['shipment_id']}: plan CAD {l['cost_cad']}, recomputed {price:.2f}")

total = tl_total + ltl_total
plan_total = plan.get("summary", {}).get("total_cost")
if plan_total is not None and abs(plan_total - total) > TOL_C:
    flag("COST_MISMATCH", "R5", f"plan total CAD {plan_total}, recomputed CAD {total:.2f}")

verdict = "ACCEPT" if not violations else "REJECT"
report = dict(plan_file=plan_file, verdict=verdict, n_violations=len(violations), violations=violations,
              recomputed=dict(tl_cost=round(tl_total, 2), ltl_cost=round(ltl_total, 2), total_cost=round(total, 2),
                              n_tours=len(plan["tours"]), n_ltl=len(plan["ltl"])))
out = Path(plan_file).with_name("check_" + Path(plan_file).stem.replace("plan_", "") + ".json")
json.dump(report, open(out, "w"), indent=2)

print(f"{verdict} | {len(violations)} violation(s) | recomputed total CAD {total:,.2f} | report: {out}")
for v in violations[:30]:
    print(f"  {v['code']:<22} {v['rule']:<5} tour {v['tour_id']} event {v['seq']}: {v['detail']}")
sys.exit(0 if verdict == "ACCEPT" else 1)
