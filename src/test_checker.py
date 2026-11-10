# test_checker.py - used as evidence that the checker works
#
# Writes four plans to outputs/tests/ and runs the checker on each:
#   plan_valid.json            the real plan                        -> must be ACCEPTED
#   plan_overload.json         a heavy shipment squeezed onto a tour -> REJECTED with CAPACITY_*
#   plan_missed_window.json    one delivery finishes 15 min late    -> REJECTED with WINDOW
#   plan_double_booked.json    one tractor given two tours in a day -> REJECTED with TRACTOR_DOUBLE_BOOKED

import copy
import json
import os
import subprocess
import sys

import pandas as pd

SRC = "outputs/plan_simplified.json"
OUT = "outputs/tests"
os.makedirs(OUT, exist_ok=True)
valid = json.load(open(SRC))
wb = valid["workbook"]
ship = pd.read_excel(wb, "shipments").set_index("shipment_id")
fac = pd.read_excel(wb, "facilities").set_index("facility_id")
dmat = pd.read_excel(wb, "distance_matrix")
drive = {(r.from_id, r.to_id): r.drive_hours for r in dmat.itertuples()}
trac = pd.read_excel(wb, "tractors").set_index("tractor_id")

# 1. overload: put an LTL shipment onto a tour whose route ALREADY passes its pickup and delivery
#    facilities, so no extra driving is needed; the schedule and cost are recomputed exactly.
#    We keep the case with the fewest violations OTHER than capacity (ideally none). In the simplified
#    plan the tours are so tight that the extra hour of loading always makes one later stop late, so
#    the cleanest case shows the capacity errors plus one window error.
eq = pd.read_excel(wb, "equipment").iloc[0]
cap = (eq.weight_capacity_lb, eq.length_capacity_feet, eq.pallet_capacity)
tl = pd.read_excel(wb, "tl_costs").iloc[0]
 
 
def leg(a, b):
    return 0.0 if a == b else drive[(a, b)]
 
 
def window(sid, kind, loc):
    s = ship.loc[sid]
    w = (s.pickup_open_hour, s.pickup_close_hour) if kind == "P" else (s.delivery_open_hour, s.delivery_close_hour)
    svc = s.pickup_service_hours if kind == "P" else s.delivery_service_hours
    return float(max(w[0], fac.loc[loc].open_hour)), float(svc)        # plain numbers, so JSON can save them
 
 
def reschedule(t):
    """Recompute arrival / service times, return, duty and cost along the new stop order."""
    clock, here = t["departure"], t["depot_id"]
    for n, e in enumerate(t["events"], 1):
        clock += float(leg(here, e["location_id"]))
        earliest, svc = window(e["shipment_id"], e["type"], e["location_id"])
        e.update(seq=n, arrival=clock, service_start=max(clock, earliest), service_end=max(clock, earliest) + svc)
        clock, here = e["service_end"], e["location_id"]
    t["return"] = clock + float(leg(here, t["depot_id"]))
    t["duty_hours"] = t["return"] - t["departure"]
    t["cost_cad"] = round(float(max(tl.minimum_linehaul_cad, t["miles"] * tl.linehaul_cad_per_mile)
                                + tl.extra_stop_cad * max(0, len(t["events"]) - 2)), 2)
 
 
def overloaded(t):
    load = [0, 0, 0]
    for e in t["events"]:
        s = ship.loc[e["shipment_id"]]
        g = 1 if e["type"] == "P" else -1
        load = [load[0] + g * s.weight_lb, load[1] + g * s.linear_feet, load[2] + g * s.pallets]
        if any(load[k] > cap[k] for k in range(3)):
            return True
    return False
 
 
over, over_extra = None, None
for k, t0 in enumerate(valid["tours"]):
    for l in valid["ltl"]:
        sid = l["shipment_id"]
        s = ship.loc[sid]
        locs = [e["location_id"] for e in t0["events"]]
        if s.day != t0["day"]:
            continue
        for a in [n for n, loc in enumerate(locs) if loc == s.origin_id]:
            for b in [n for n, loc in enumerate(locs) if loc == s.destination_id and n >= a]:
                trial = copy.deepcopy(valid)
                t = trial["tours"][k]
                base = dict(break_after=False, arrival=0, service_start=0, service_end=0, seq=0)
                t["events"].insert(b + 1, dict(base, type="D", shipment_id=sid, location_id=s.destination_id))
                t["events"].insert(a + 1, dict(base, type="P", shipment_id=sid, location_id=s.origin_id))
                t["shipments"].append(sid)
                trial["ltl"] = [x for x in trial["ltl"] if x["shipment_id"] != sid]
                if not overloaded(t):
                    continue
                # the extra hour of loading can push later stops late: try leaving earlier, within the shift
                shift_start = float(trac.loc[t["tractor_id"]].shift_start_hour)
                departures = [t0["departure"] - 0.25 * q for q in range(int((t0["departure"] - shift_start) / 0.25) + 1)]
                for dep in departures:
                    t["departure"] = dep
                    reschedule(t)
                    trial["summary"]["total_cost"] = round(sum(x["cost_cad"] for x in trial["tours"])
                                                           + sum(x["cost_cad"] for x in trial["ltl"]), 2)
                    path = f"{OUT}/plan_overload.json"
                    json.dump(trial, open(path, "w"), indent=2)
                    subprocess.run([sys.executable, "src/checker.py", path], capture_output=True, text=True)
                    found = json.load(open(f"{OUT}/check_overload.json"))["violations"]
                    extra = sum(1 for v in found if not v["code"].startswith("CAPACITY_"))
                    if any(v["code"].startswith("CAPACITY_") for v in found) and (over is None or extra < over_extra):
                        over, over_extra = copy.deepcopy(trial), extra
                    if over_extra == 0:
                        break
                if over_extra == 0:
                    break
            if over_extra == 0:
                break
        if over_extra == 0:
            break
    if over_extra == 0:
        break
if over is None:
    raise SystemExit("could not build an overload case from this plan")
 

# 2. missed window: the last delivery of a tour starts 15 min after its latest possible start
late = copy.deepcopy(valid)
for t in late["tours"]:
    e = t["events"][-1]
    s = ship.loc[e["shipment_id"]]
    close = min(s.delivery_close_hour, fac.loc[e["location_id"]].close_hour)
    new_start = close - s.delivery_service_hours + 0.25
    new_return = new_start + s.delivery_service_hours + drive[(e["location_id"], t["depot_id"])]
    shift_end = trac.loc[t["tractor_id"]].shift_end_hour
    if new_start >= e["arrival"] and new_return <= shift_end and new_return - t["departure"] <= 12:
        e["service_start"], e["service_end"] = new_start, new_start + s.delivery_service_hours
        t["return"] = new_return
        t["duty_hours"] = new_return - t["departure"]
        break

# 3. double booked: give a tour the tractor of another tour of the same depot and day
dbl = copy.deepcopy(valid)
a = dbl["tours"][0]
b = next(t for t in dbl["tours"][1:] if t["day"] == a["day"] and t["depot_id"] == a["depot_id"])
b["tractor_id"] = a["tractor_id"]

cases = [("plan_valid.json", valid, "ACCEPT", None),
         ("plan_overload.json", over, "REJECT", "CAPACITY_"),
         ("plan_missed_window.json", late, "REJECT", "WINDOW"),
         ("plan_double_booked.json", dbl, "REJECT", "TRACTOR_DOUBLE_BOOKED")]

all_ok = True
for name, plan, expected, code in cases:
    path = f"{OUT}/{name}"
    json.dump(plan, open(path, "w"), indent=2)
    subprocess.run([sys.executable, "src/checker.py", path], capture_output=True, text=True)
    report = json.load(open(path.replace("plan_", "check_")))
    codes = sorted({v["code"] for v in report["violations"]})
    ok = report["verdict"] == expected and (code is None or any(c.startswith(code) for c in codes))
    all_ok &= ok
    print(f"{'PASS' if ok else 'FAIL'}  {name:<28} verdict {report['verdict']:<7} codes {codes}")

print("\nAll checker tests passed." if all_ok else "\nSome checker tests FAILED.")
sys.exit(0 if all_ok else 1)
