# loader.py - reads the workbook and prepares every table the other scripts need.

# Other scripts reuse everything with:  from loader import *
# (they inherit the same choice: python src/approach_a.py main)

import sys
import pandas as pd

INSTANCE = sys.argv[1] if len(sys.argv) > 1 else "simplified"     # "simplified" or "main"
path = f"data/project1_{INSTANCE}.xlsx"

# read the sheets
shipments_df = pd.read_excel(path, "shipments")
facilities_df = pd.read_excel(path, "facilities")
depots_df = pd.read_excel(path, "depots")
dist_df = pd.read_excel(path, "distance_matrix")
ltl_df = pd.read_excel(path, "ltl_rates")
tl_df = pd.read_excel(path, "tl_costs")
equip_df = pd.read_excel(path, "equipment")
tractors_df = pd.read_excel(path, "tractors")
rules_df = pd.read_excel(path, "driver_rules")
params_df = pd.read_excel(path, "parameters")

# shipments
# we transform the table into a dictionary of dictionaries
shipments = {}
for row in shipments_df.to_dict("records"):
    shipments[row["shipment_id"]] = row

# opening hours of every location 
hours = {}
for row in facilities_df.itertuples():
    hours[row.facility_id] = (row.open_hour, row.close_hour)
for row in depots_df.itertuples():
    hours[row.depot_id] = (row.open_hour, row.close_hour)

# miles and drive hours between locations
miles = {}
drive = {}
for row in dist_df.itertuples():
    miles[(row.from_id, row.to_id)] = row.distance_miles
    drive[(row.from_id, row.to_id)] = row.drive_hours
# same location -> 0 miles, 0 hours (the matrix has no row for it)
for loc in hours:
    miles[(loc, loc)] = 0
    drive[(loc, loc)] = 0

# tractors, equipment, truckload costs
tractors = {}
for row in tractors_df.to_dict("records"):
    tractors[row["tractor_id"]] = row

equipment = {}
for row in equip_df.to_dict("records"):
    equipment[row["equipment_id"]] = row

tl_cost = {}
for row in tl_df.to_dict("records"):
    tl_cost[row["equipment_id"]] = row

# rules and parameters
rule = dict(zip(rules_df.parameter, rules_df.value))
param = dict(zip(params_df.parameter, params_df.value))

# LTL cost of each shipment = base cost * (1 + fuel surcharge)
ltl_cost = {}
for s in shipments.values():
    d = miles[(s["origin_id"], s["destination_id"])]   # distance origin-destination, not tour one
    match = ltl_df[(ltl_df.freight_class == s["freight_class"])    # boolean mask
                   & (ltl_df.weight_from_lb <= s["weight_lb"]) & (s["weight_lb"] < ltl_df.weight_to_lb)  # merge of two masks
                   & (ltl_df.distance_from_miles <= d) & (d < ltl_df.distance_to_miles)]    # merge of two masks
    if len(match) != 1:     # always one row
        raise ValueError(f"{s['shipment_id']}: {len(match)} LTL rate rows match")
    r = match.iloc[0]
    ltl_cost[s["shipment_id"]] = r.base_cost_cad * (1 + r.fuel_surcharge_pct)

# basic data checks
for s in shipments.values():
    if s["origin_id"] not in hours or s["destination_id"] not in hours:
        raise ValueError(f"{s['shipment_id']}: unknown facility")
    if not (s["pickup_open_hour"] < s["pickup_close_hour"] and s["delivery_open_hour"] < s["delivery_close_hour"]):
        raise ValueError(f"{s['shipment_id']}: window open >= close")
for t in tractors.values():
    if t["home_depot_id"] not in hours or t["equipment_id"] not in equipment or t["equipment_id"] not in tl_cost:
        raise ValueError(f"{t['tractor_id']}: unknown depot or equipment")

# extra data checks (rules R0.5)
if shipments_df["shipment_id"].duplicated().any():     # true if a value has already been seen
    raise ValueError("duplicate shipment_id")
for s in shipments.values():
    for col in ("weight_lb", "linear_feet", "pallets"):
        if not s[col] > 0:
            raise ValueError(f"{s['shipment_id']}: {col} must be positive")
for a in hours:
    for b in facilities_df.facility_id:
        if a != b and ((a, b) not in drive or (b, a) not in drive):
            raise ValueError(f"missing distance {a} <-> {b}")

        
# summary
if __name__ == "__main__":
    print("instance:", INSTANCE)
    print("shipments:", len(shipments), "| tractors:", len(tractors), "| locations:", len(hours))
    print("rules:", rule)
    print("parameters:", param)
    print("all-LTL baseline: CAD", round(sum(ltl_cost.values()), 2))
    for day in sorted(set(s["day"] for s in shipments.values())):
        day_cost = sum(ltl_cost[i] for i, s in shipments.items() if s["day"] == day)
        n = sum(1 for s in shipments.values() if s["day"] == day)
        print(f"  day {day}: {n} shipments, LTL CAD {day_cost:,.2f}")
