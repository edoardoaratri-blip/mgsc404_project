# test_checker.py - evidence that the checker works (brief, deliverable 3).
#
# Run from the repository folder, after approach_a.py has written outputs/plan_simplified.json:
#     python src/test_checker.py
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

# 1. overload: squeeze a same-day LTL shipment onto a tour at the moment its load is highest
eq = pd.read_excel(wb, "equipment").iloc[0]
cap = (eq.weight_capacity_lb, eq.length_capacity_feet, eq.pallet_capacity)
over = copy.deepcopy(valid)
done = False
for t in over["tours"]:
    load, peak, peak_at = [0, 0, 0], None, 0
    for n, e in enumerate(t["events"]):
        s = ship.loc[e["shipment_id"]]
        g = 1 if e["type"] == "P" else -1
        load = [load[0] + g * s.weight_lb, load[1] + g * s.linear_feet, load[2] + g * s.pallets]
        if peak is None or max(load[k] / cap[k] for k in range(3)) > max(peak[k] / cap[k] for k in range(3)):
            peak, peak_at = list(load), n
    for l in over["ltl"]:
        sid = l["shipment_id"]
        s = ship.loc[sid]
        extra = (s.weight_lb, s.linear_feet, s.pallets)
        if s.day == t["day"] and any(peak[k] + extra[k] > cap[k] for k in range(3)):
            e0 = t["events"][peak_at]
            t["events"].insert(peak_at + 1, dict(seq=0, type="P", shipment_id=sid, location_id=s.origin_id,
                                                 arrival=e0["service_end"], service_start=e0["service_end"],
                                                 service_end=e0["service_end"] + 0.5, break_after=False))
            t["events"].append(dict(seq=0, type="D", shipment_id=sid, location_id=s.destination_id,
                                    arrival=t["return"], service_start=t["return"], service_end=t["return"] + 0.5,
                                    break_after=False))
            for n, e in enumerate(t["events"], 1):
                e["seq"] = n
            t["shipments"].append(sid)
            over["ltl"] = [x for x in over["ltl"] if x["shipment_id"] != sid]
            done = True
            break
    if done:
        break
if not done:
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
