# checker.py - independent checker for an exported plan.
#
# Run from the repository folder:
#     python src/checker.py outputs/plan_simplified.json
#     python src/checker.py outputs/plan_main.json
# Options:
#     --workbook PATH           use this workbook instead of the one named in the plan
#     --tol-t HOURS             time tolerance (default 1e-5 h, about 0.04 s)
#     --allow-other-workbook    do not reject a workbook that is not the course workbook
#
# It reads ONLY the plan file and the workbook, with its own code.
# It does not import loader.py, approach_a.py or anything else from the project, and it never
# trusts the numbers written in the plan: it recomputes locations, loads, times, miles, driving,
# duty and costs from the workbook and compares. Rules follow docs/rules.md.
# A plan that is malformed or refers to unknown shipments is REJECTED with a reason, never a crash.
# Output: a verdict (ACCEPT / REJECT), warnings, and outputs/check_<plan name>.json
#
# Plan format (what the exporter must write, see docs/formats.md):
#   {"workbook": "...xlsx", "summary": {"total_cost": ...},
#    "ltl":   [{"shipment_id", "cost_cad"}],
#    "tours": [{"tour_id", "tractor_id", "day", "depot_id", "equipment_id", "shipments": [...],
#               "departure", "return", "miles", "cost_cad",
#               "events": [{"seq", "type": "P"|"D", "shipment_id", "location_id", "arrival",
#                           "service_start", "service_end",
#                           "break_after": true}]}]}   # optional: 0.5 h break after service (R6.4)
#
# Driver break (R6.4): the break is always 0.5 h after a service. Waiting never counts as the
# break, so a plan that relies on waiting is rejected with BREAK.

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

TOL_C = 0.01
SHEETS = ["shipments", "facilities", "distance_matrix", "ltl_rates", "tl_costs",
          "equipment", "tractors", "depots", "driver_rules", "parameters"]

# The problem, not the plan, fixes the data. Fingerprints of the course workbooks (all 10 data sheets).
# lineterminator="\n" makes the fingerprint the same on Windows, macOS and Linux.
KNOWN_WORKBOOKS = {
    "simplified": dict(n_shipments=60, all_ltl=93298.35,
                       sha256="4e9aa51549fc8f6fc648c578d5c037d6f6153ab3aba4f2c4ece2b0487a60d47f"),
    "main": dict(n_shipments=800, all_ltl=1557535.85,
                 sha256="e7f35b7464a5364df3639abb38f9010c2d67aea79738749604af9c280095fd1d"),
}


def fingerprint(wb):
    h = hashlib.sha256()
    for s in SHEETS:
        h.update(s.encode())
        h.update(pd.read_excel(wb, s).to_csv(index=False, float_format="%.10g", lineterminator="\n").encode())
    return h.hexdigest()


class Checker:
    def __init__(self, plan, wb, tol_t, allow_other_workbook):
        self.plan, self.wb, self.tol_t = plan, wb, tol_t
        self.violations, self.warnings, self.tours_out = [], [], []
        self.load_workbook(allow_other_workbook)

    def load_workbook(self, allow_other):
        wb = self.wb
        table = lambda name, key: pd.read_excel(wb, name).set_index(key).to_dict("index")
        self.ship = table("shipments", "shipment_id")
        self.fac = table("facilities", "facility_id")
        self.dep = table("depots", "depot_id")
        self.tlc = table("tl_costs", "equipment_id")
        self.eqp = table("equipment", "equipment_id")
        self.trac = table("tractors", "tractor_id")
        self.rates = pd.read_excel(wb, "ltl_rates").to_dict("records")
        dr = pd.read_excel(wb, "driver_rules")
        pr = pd.read_excel(wb, "parameters")
        self.rules = dict(zip(dr["parameter"], dr["value"]))
        self.params = dict(zip(pr["parameter"], pr["value"]))
        self.lane = {(r.from_id, r.to_id): (float(r.distance_miles), float(r.drive_hours))
                     for r in pd.read_excel(wb, "distance_matrix").itertuples()}
        self.hours = {f: (r["open_hour"], r["close_hour"]) for f, r in self.fac.items()}
        self.hours.update({d: (r["open_hour"], r["close_hour"]) for d, r in self.dep.items()})
        self.max_drive = self.rules["max_drive_hours"]
        self.max_duty = self.rules["max_duty_hours"]
        self.break_after = self.rules["break_after_drive_hours"]
        self.break_len = self.rules["break_hours"]
        self.max_stops = int(self.params["max_stops"])
        self.lifo = int(self.params["lifo_required"]) == 1
        self.ltl_cache = {}
        self.baseline = sum(self.ltl_price(s) for s in self.ship)
        sha = fingerprint(wb)
        match = [k for k, v in KNOWN_WORKBOOKS.items() if v["sha256"] == sha]
        self.instance = match[0] if match else None
        if not match and not allow_other:
            self.flag("WORKBOOK_UNRECOGNISED", "R0",
                      f"{Path(wb).name} is not the course workbook (fingerprint {sha[:12]}...); "
                      "use --allow-other-workbook only if the instance really changed")

    def ltl_price(self, sid):
        if sid in self.ltl_cache:
            return self.ltl_cache[sid]
        s = self.ship[sid]
        miles = self.leg(s["origin_id"], s["destination_id"])[0]
        m = [r for r in self.rates if r["freight_class"] == s["freight_class"]
             and r["weight_from_lb"] <= s["weight_lb"] < r["weight_to_lb"]
             and r["distance_from_miles"] <= miles < r["distance_to_miles"]]
        if len(m) != 1:
            raise ValueError(f"{sid}: {len(m)} LTL rate rows (expected exactly 1)")
        self.ltl_cache[sid] = float(m[0]["base_cost_cad"] * (1 + m[0]["fuel_surcharge_pct"]))
        return self.ltl_cache[sid]

    def leg(self, a, b):
        if a == b:
            return 0.0, 0.0
        if (a, b) not in self.lane:
            raise KeyError(f"no distance row {a}->{b}")
        return self.lane[(a, b)]

    def flag(self, code, rule_ref, detail, tour_id=None, seq=None):
        self.violations.append(dict(code=code, rule=rule_ref, tour_id=tour_id, seq=seq, detail=detail))

    def warn(self, code, detail, tour_id=None):
        self.warnings.append(dict(code=code, tour_id=tour_id, detail=detail))

    def run(self):
        plan = self.plan
        tours, ltl = plan.get("tours"), plan.get("ltl")
        if not isinstance(tours, list) or not isinstance(ltl, list):
            self.flag("MALFORMED", "R0", "the plan needs a list 'tours' and a list 'ltl'")
            tours, ltl = [], []
        served = {}
        seen_ids, seen_key = set(), {}
        tl_total = 0.0
        for i, t in enumerate(tours):
            if not isinstance(t, dict):
                self.flag("MALFORMED", "R0", f"tour #{i + 1} is not an object")
                continue
            tid = t.get("tour_id", f"#{i + 1}")
            if tid in seen_ids:
                self.flag("MALFORMED", "R0", f"tour_id {tid} is used twice", tid)
            seen_ids.add(tid)
            try:
                tl_total += self.check_tour(t, tid, served, seen_key)
            except (KeyError, TypeError, ValueError, AttributeError) as ex:
                self.flag("MALFORMED", "R0", f"{type(ex).__name__}: {ex}", tid)
        ltl_total = 0.0
        for i, l in enumerate(ltl):
            sid = l.get("shipment_id") if isinstance(l, dict) else None
            if sid not in self.ship:
                self.flag("SHIPMENT_UNKNOWN", "R1.1", f"LTL entry #{i + 1} refers to {sid!r}, not in the workbook")
                continue
            served.setdefault(sid, []).append("LTL")
            price = self.ltl_price(sid)
            ltl_total += price
            if "cost_cad" not in l:
                self.flag("MALFORMED", "R5.1", f"{sid}: LTL entry without cost_cad")
            elif abs(price - l["cost_cad"]) > TOL_C:
                self.flag("COST_MISMATCH", "R5.1", f"{sid}: plan CAD {l['cost_cad']}, recomputed {price:.2f}")
        for sid in self.ship:
            if sid not in served:
                self.flag("SHIPMENT_MISSING", "R1.1", f"{sid} is not served")
            elif len(served[sid]) > 1:
                self.flag("SHIPMENT_DUPLICATE", "R1.1", f"{sid} served {len(served[sid])} times: {served[sid]}")
        total = tl_total + ltl_total
        claimed = (plan.get("summary") or {}).get("total_cost")
        if claimed is None:
            self.warn("NO_TOTAL", "the plan states no summary.total_cost, so the solver objective was not compared")
        elif abs(claimed - total) > TOL_C:
            self.flag("COST_MISMATCH", "R5", f"plan total CAD {claimed}, recomputed CAD {total:.2f}")
        if total > self.baseline + TOL_C:
            self.warn("ABOVE_ALL_LTL", f"total {total:,.2f} is above the all-LTL baseline {self.baseline:,.2f}")
        return dict(tl_cost=round(tl_total, 2), ltl_cost=round(ltl_total, 2), total_cost=round(total, 2),
                    all_ltl_baseline=round(self.baseline, 2),
                    saving_pct=round(100 * (1 - total / self.baseline), 2) if self.baseline else None,
                    n_tours=len(tours), n_ltl=len(ltl))

    def check_tour(self, t, tid, served, seen_key):
        tol = self.tol_t
        flag = lambda code, ref, detail, seq=None: self.flag(code, ref, detail, tid, seq)
        missing = [k for k in ("tractor_id", "day", "departure", "return", "events", "shipments") if k not in t]
        if missing:
            flag("MALFORMED", "R0", f"missing field(s) {missing}")
            return 0.0
        key = (t["tractor_id"], t["day"])
        if key in seen_key:
            flag("TRACTOR_DOUBLE_BOOKED", "R4.6", f"tractor {key[0]} has tours {seen_key[key]} and {tid} on day {key[1]}")
        seen_key[key] = tid
        if t["tractor_id"] not in self.trac:
            flag("SHIFT_DEPOT", "R2.6", f"unknown tractor {t['tractor_id']}")
            return 0.0
        tr = self.trac[t["tractor_id"]]
        depot, eq_id = tr["home_depot_id"], tr["equipment_id"]
        if t.get("depot_id") != depot or t.get("equipment_id") != eq_id:
            flag("SHIFT_DEPOT", "R2.6", f"plan says depot/equipment {t.get('depot_id')}/{t.get('equipment_id')}, "
                 f"workbook says {depot}/{eq_id}")
        cap, day, ev = self.eqp[eq_id], t["day"], t["events"]
        if not isinstance(ev, list) or not ev:
            flag("EMPTY_TOUR", "R4.5", "a tour needs at least one pickup and one delivery")
            return 0.0
        for n, e in enumerate(ev):
            if not isinstance(e, dict) or e.get("type") not in ("P", "D") or e.get("shipment_id") not in self.ship \
                    or not isinstance(e.get("service_start"), (int, float)):
                unknown = isinstance(e, dict) and e.get("shipment_id") not in self.ship
                flag("SHIPMENT_UNKNOWN" if unknown else "MALFORMED", "R1.1",
                     f"event #{n + 1} is malformed or refers to an unknown shipment: {e!r}")
                return 0.0
        seq = lambda n: ev[n].get("seq", n)

        if len(ev) > self.max_stops:
            flag("STOP_LIMIT", "R4.5", f"{len(ev)} events > {self.max_stops}")
        pos = {}
        for n, e in enumerate(ev):
            pos.setdefault((e["type"], e["shipment_id"]), []).append(n)
        ev_ships = sorted({e["shipment_id"] for e in ev})
        if ev_ships != sorted(t["shipments"]):
            flag("LIST_MISMATCH", "R1.2", f"events cover {ev_ships}, tour lists {sorted(t['shipments'])}")
        for sid in ev_ships:
            p, d = pos.get(("P", sid), []), pos.get(("D", sid), [])
            if len(p) != 1 or len(d) != 1 or p[0] > d[0]:
                flag("PRECEDENCE", "R1.2", f"{sid}: pickups {p}, deliveries {d}")
            if self.ship[sid]["day"] != day:
                flag("WRONG_DAY", "R1.3", f"{sid} is a day-{self.ship[sid]['day']} shipment on a day-{day} tour")
            served.setdefault(sid, []).append(f"tour {tid}")

        load, stack = [0.0, 0.0, 0.0], []
        for n, e in enumerate(ev):
            s, sid = self.ship[e["shipment_id"]], e["shipment_id"]
            if e["type"] == "P":
                if s["temperature"] == "chilled" and int(cap["chilled_capable"]) != 1:
                    flag("EQUIPMENT", "R6.1", f"chilled {sid} on {eq_id}", seq(n))
                for other in stack:
                    o = self.ship[other]
                    if o["temperature"] != s["temperature"] or o["compatibility_group"] != s["compatibility_group"]:
                        flag("COMPATIBILITY", "R6.2", f"{sid} ({s['temperature']}/{s['compatibility_group']}) "
                             f"on board with {other} ({o['temperature']}/{o['compatibility_group']})", seq(n))
                stack.append(sid)
                sign = 1
            else:
                if sid in stack:
                    if self.lifo and stack[-1] != sid:
                        flag("LIFO", "R6.3", f"delivers {sid} but {stack[-1]} is on top", seq(n))
                    stack.remove(sid)
                sign = -1
            load = [load[0] + sign * s["weight_lb"], load[1] + sign * s["linear_feet"], load[2] + sign * s["pallets"]]
            if load[0] > cap["weight_capacity_lb"]:
                flag("CAPACITY_WEIGHT", "R3.1", f"{load[0]:.0f} lb > {cap['weight_capacity_lb']}", seq(n))
            if load[1] > cap["length_capacity_feet"]:
                flag("CAPACITY_LENGTH", "R3.1", f"{load[1]:.0f} ft > {cap['length_capacity_feet']}", seq(n))
            if load[2] > cap["pallet_capacity"]:
                flag("CAPACITY_PALLETS", "R3.1", f"{load[2]:.0f} pallets > {cap['pallet_capacity']}", seq(n))
        if stack:
            flag("PRECEDENCE", "R1.2", f"the truck is not empty at the end: {stack}")

        t_dep = t["departure"]
        if t_dep < max(tr["shift_start_hour"], self.hours[depot][0]) - tol:
            flag("SHIFT_DEPOT", "R2.6", f"departs {t_dep} before shift/depot opening")
        clock, here = t_dep, depot
        total_drive = since_break = total_miles = 0.0
        for n, e in enumerate(ev):
            s, sid = self.ship[e["shipment_id"]], e["shipment_id"]
            where = s["origin_id"] if e["type"] == "P" else s["destination_id"]
            if e.get("location_id") not in (None, where):
                flag("LOCATION", "R1.2", f"{sid} {e['type']} at {e['location_id']}, should be {where}", seq(n))
            mi, hr = self.leg(here, where)
            total_miles += mi
            total_drive += hr
            since_break += hr
            if since_break > self.break_after + tol:
                flag("BREAK", "R6.4", f"{since_break:.2f} h of driving since the last break", seq(n))
            clock += hr
            if "arrival" in e and abs(e["arrival"] - clock) > tol:
                flag("TIME_FLOW", "R4.1", f"arrival {e['arrival']} but travel gives {clock}", seq(n))
            if e["type"] == "P":
                w_open, w_close, svc = s["pickup_open_hour"], s["pickup_close_hour"], s["pickup_service_hours"]
            else:
                w_open, w_close, svc = s["delivery_open_hour"], s["delivery_close_hour"], s["delivery_service_hours"]
            f_open, f_close = self.hours[where]
            start = e["service_start"]
            if start < clock - tol:
                flag("TIME_FLOW", "R2.4", f"service starts {start} before it can ({clock})", seq(n))
            if "service_end" in e and abs(e["service_end"] - start - svc) > tol:
                flag("TIME_FLOW", "R1.4", f"service lasts {e['service_end'] - start} h, should be {svc}", seq(n))
            if start < max(w_open, f_open) - tol or start + svc > min(w_close, f_close) + tol:
                flag("WINDOW", "R2.2", f"service {start}-{start + svc} outside window [{w_open},{w_close}] "
                     f"and hours [{f_open},{f_close}]", seq(n))
            clock = max(clock, start) + svc
            if e.get("break_after"):
                clock += self.break_len
                since_break = 0.0
            here = where
        mi, hr = self.leg(here, depot)
        total_miles += mi
        total_drive += hr
        since_break += hr
        if since_break > self.break_after + tol:
            flag("BREAK", "R6.4", f"{since_break:.2f} h of driving since the last break (return leg)")
        clock += hr
        if t["return"] < clock - tol:
            flag("TIME_FLOW", "R4.1", f"return {t['return']} but travel gives {clock}")
        end_time = max(clock, t["return"])
        if end_time > min(tr["shift_end_hour"], self.hours[depot][1]) + tol:
            flag("SHIFT_DEPOT", "R2.6", f"returns {end_time} after shift/depot closing")
        if total_drive > self.max_drive + tol:
            flag("DRIVE_LIMIT", "R4.2", f"{total_drive} h driving > {self.max_drive}")
        if end_time - t_dep > self.max_duty + tol:
            flag("DUTY_LIMIT", "R4.3", f"{end_time - t_dep} h duty > {self.max_duty}")

        c = self.tlc[eq_id]
        cost = max(c["minimum_linehaul_cad"], total_miles * c["linehaul_cad_per_mile"]) \
            + c["extra_stop_cad"] * max(0, len(ev) - 2)
        if "cost_cad" not in t or "miles" not in t:
            flag("MALFORMED", "R5.2", "tour without miles or cost_cad")
        elif abs(cost - t["cost_cad"]) > TOL_C or abs(total_miles - t["miles"]) > tol:
            flag("COST_MISMATCH", "R5.2", f"plan {t['miles']} mi / CAD {t['cost_cad']}, "
                 f"recomputed {total_miles} mi / CAD {cost:.2f}")
        alt = sum(self.ltl_price(sid) for sid in ev_ships)
        if cost > alt + TOL_C:
            self.warn("TOUR_DEARER_THAN_LTL", f"costs {cost:.2f} but its shipments cost {alt:.2f} by LTL", tid)
        self.tours_out.append(dict(tour_id=tid, tractor_id=t["tractor_id"], day=day, events=len(ev),
                                   miles=round(total_miles, 3), driving_h=round(total_drive, 3),
                                   duty_h=round(end_time - t_dep, 3), cost=round(cost, 2),
                                   ltl_alternative=round(alt, 2)))
        return cost


def main(argv=None):
    ap = argparse.ArgumentParser(description="Independent checker for an exported plan.")
    ap.add_argument("plan", nargs="?", default="outputs/plan_simplified.json")
    ap.add_argument("--workbook")
    ap.add_argument("--tol-t", type=float, default=1e-5)
    ap.add_argument("--allow-other-workbook", action="store_true")
    args = ap.parse_args(argv)
    plan_file = args.plan
    with open(plan_file) as f:
        plan = json.load(f)
    wb = args.workbook or plan.get("workbook")
    if not wb or not Path(wb).exists():
        print(f"REJECT | workbook {wb!r} not found (name it in the plan or pass --workbook)")
        return 2
    ck = Checker(plan, wb, args.tol_t, args.allow_other_workbook)
    recomputed = ck.run()
    verdict = "ACCEPT" if not ck.violations else "REJECT"
    report = dict(plan_file=plan_file, workbook=str(wb), instance=ck.instance, verdict=verdict,
                  n_violations=len(ck.violations), violations=ck.violations, warnings=ck.warnings,
                  recomputed=recomputed, tours=ck.tours_out, tolerances=dict(time_h=args.tol_t, cost_cad=TOL_C))
    out = Path(plan_file).with_name("check_" + Path(plan_file).stem.replace("plan_", "") + ".json")
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"{verdict} | {len(ck.violations)} violation(s) | {len(ck.warnings)} warning(s) | "
          f"recomputed total CAD {recomputed['total_cost']:,.2f} | report: {out}")
    for v in ck.violations[:30]:
        print(f"  {v['code']:<22} {v['rule']:<5} tour {v['tour_id']} event {v['seq']}: {v['detail']}")
    for w in ck.warnings[:10]:
        print(f"  WARN {w['code']:<20} tour {w['tour_id']}: {w['detail']}")
    return 0 if verdict == "ACCEPT" else 1


if __name__ == "__main__":
    sys.exit(main())
