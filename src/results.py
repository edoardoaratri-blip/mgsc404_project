import csv
import json
import os
 
import matplotlib
matplotlib.use("Agg")                       # write PNG files, no window
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
 
from loader import *          # INSTANCE, shipments, miles, drive, equipment, ltl_cost

# colours
INK, INK_2, GRID = "#0b0b0b", "#52514e", "#d9d8d3"
C_GUROBI, C_HEUR, C_LTL = "#2a78d6", "#eb6834", "#8f8e88"
C_PICKUP, C_DELIVERY, C_DRIVE, C_WAIT, C_BREAK = "#2a78d6", "#1baf7a", "#b7b5ad", "#efeee9", "#6250d6"

all_ltl = sum(ltl_cost.values())
 
 
def load(path):
    return json.load(open(path)) if os.path.exists(path) else None
 

# function that measures any plan
def metrics(plan, check):
    """Every result the project instructions list, computed from one plan."""
    tours = plan["tours"]
    total = sum(t["cost_cad"] for t in tours) + sum(l["cost_cad"] for l in plan["ltl"])
    tour_miles = empty_miles = loaded_w = cap_w = loaded_l = cap_l = 0.0
    peak_w, peak_l, extra = [], [], []
    for t in tours:
        cap = equipment[t["equipment_id"]]
        locs = [t["depot_id"]] + [e["location_id"] for e in t["events"]] + [t["depot_id"]]
        w = l = pw = pl = 0.0
        for k, (a, b) in enumerate(zip(locs, locs[1:])):
            leg = miles[(a, b)]
            tour_miles += leg
            if w == 0:
                empty_miles += leg                                  # driving with an empty trailer
            loaded_w += leg * w
            loaded_l += leg * l
            cap_w += leg * cap["weight_capacity_lb"]
            cap_l += leg * cap["length_capacity_feet"]
            if k < len(t["events"]):
                e = t["events"][k]
                sign = 1 if e["type"] == "P" else -1
                w += sign * shipments[e["shipment_id"]]["weight_lb"]
                l += sign * shipments[e["shipment_id"]]["linear_feet"]
                pw, pl = max(pw, w), max(pl, l)
        peak_w.append(pw / cap["weight_capacity_lb"])
        peak_l.append(pl / cap["length_capacity_feet"])
        end = {(e["type"], e["shipment_id"]): e["service_end"] for e in t["events"]}
        for i in t["shipments"]:
            s = shipments[i]
            direct = drive[(s["origin_id"], s["destination_id"])] + s["delivery_service_hours"]
            extra.append(end[("D", i)] - end[("P", i)] - direct)
    n = len(tours)
    return {
        "Total cost (CAD)": total,
        "Savings vs all-LTL (CAD)": all_ltl - total,
        "Savings vs all-LTL (%)": 100 * (all_ltl - total) / all_ltl,
        "Tours": n,
        "Shipments on LTL": len(plan["ltl"]),
        "Shipments on a dedicated tour": sum(1 for t in tours if len(t["shipments"]) == 1),
        "Shipments on a tour with 2+ shipments": sum(len(t["shipments"]) for t in tours if len(t["shipments"]) > 1),
        "Weight utilization, peak per tour (avg %)": 100 * sum(peak_w) / n if n else 0,
        "Floor-length utilization, peak per tour (avg %)": 100 * sum(peak_l) / n if n else 0,
        "Weight utilization, mile-weighted (%)": 100 * loaded_w / cap_w if cap_w else 0,
        "Floor-length utilization, mile-weighted (%)": 100 * loaded_l / cap_l if cap_l else 0,
        "Total tour miles (incl. depot legs)": tour_miles,
        "  of which empty miles": empty_miles,
        "Extra time vs direct trip, average (h)": sum(extra) / len(extra) if extra else 0,
        "Extra time vs direct trip, maximum (h)": max(extra) if extra else 0,
        "Checker verdict": check["verdict"] if check else "not checked",
        "Gurobi solve time (s)": plan["summary"]["runtime_s"] if "gurobi_version" in plan["summary"] else "",
        "Total run time (s)": plan["summary"].get("total_runtime_s", plan["summary"].get("runtime_s", 0)),
    }
 
 
gurobi = load(f"outputs/plan_{INSTANCE}.json")
heur = load(f"outputs/plan_heuristic_{INSTANCE}.json")
if gurobi is None:
    raise SystemExit(f"outputs/plan_{INSTANCE}.json not found: run  python src/approach_a.py {INSTANCE}  first.")
 
columns = {"All-LTL": None}
if heur:
    columns["Savings heuristic"] = metrics(heur, load(f"outputs/check_heuristic_{INSTANCE}.json"))
columns["Gurobi (Approach A)"] = metrics(gurobi, load(f"outputs/check_{INSTANCE}.json"))
keys = list(columns["Gurobi (Approach A)"])
columns["All-LTL"] = {k: "" for k in keys} | {
    "Total cost (CAD)": all_ltl, "Savings vs all-LTL (CAD)": 0.0, "Savings vs all-LTL (%)": 0.0, "Tours": 0,
    "Shipments on LTL": len(ltl_cost), "Shipments on a dedicated tour": 0,
    "Shipments on a tour with 2+ shipments": 0, "Total tour miles (incl. depot legs)": 0.0}
 
 
def fmt(v):
    if isinstance(v, str):
        return v
    return f"{v:,.0f}" if isinstance(v, int) else f"{v:,.2f}"
 
 
names = list(columns)
lines = [f"# Results: {INSTANCE} file", "",
         f"Gurobi status: {gurobi['summary']['status']}, gap {gurobi['summary'].get('max_mip_gap', 0):.4%}, "
         f"Gurobi {gurobi['summary']['gurobi_version']}, {gurobi['summary']['candidate_tours']:,} candidate tours "
         f"({'complete enumeration: global optimum' if gurobi['summary']['complete_enumeration'] else 'optimal over the candidate tours'}).",
         "", "| Metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
for k in keys:
    lines.append(f"| {k} | " + " | ".join(fmt(columns[c][k]) for c in names) + " |")
open(f"outputs/results_{INSTANCE}.md", "w").write("\n".join(lines) + "\n")
with open(f"outputs/results_{INSTANCE}.csv", "w", newline="") as f:
    wr = csv.writer(f)
    wr.writerow(["Metric"] + names)
    for k in keys:
        wr.writerow([k] + [columns[c][k] for c in names])
print("\n".join(lines))
 

# Figure 1: cost comparison, one panel per file solved so far (each with its own axis)
panels = []
for inst in ["simplified", "main"]:
    g = load(f"outputs/plan_{inst}.json")
    h = load(f"outputs/plan_heuristic_{inst}.json")
    if g:
        base = g["summary"]["all_ltl_baseline"]
        bars = [("All-LTL", base, C_LTL)]
        if h:
            bars.append(("Savings\nheuristic", h["summary"]["total_cost"], C_HEUR))
        bars.append(("Gurobi", g["summary"]["total_cost"], C_GUROBI))
        panels.append((inst, base, bars))
 
fig, axes = plt.subplots(1, len(panels), figsize=(5.2 * len(panels), 4.4), squeeze=False)
for ax, (inst, base, bars) in zip(axes[0], panels):
    xs = range(len(bars))
    ax.bar(xs, [b[1] for b in bars], color=[b[2] for b in bars], width=0.62, edgecolor="white", linewidth=2)
    for x, (name, cost, _) in zip(xs, bars):
        label = f"CAD {cost:,.0f}" if name == "All-LTL" else f"CAD {cost:,.0f}\n-{100 * (base - cost) / base:.1f}%"
        ax.text(x, cost + base * 0.015, label, ha="center", va="bottom", fontsize=9, color=INK)
    ax.set_xticks(list(xs), [b[0] for b in bars], fontsize=10, color=INK)
    ax.set_ylim(0, base * 1.18)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v / 1000:,.0f}k"))
    ax.tick_params(axis="y", colors=INK_2, labelsize=9)
    ax.set_ylabel("Total cost (CAD)", color=INK_2, fontsize=9)
    ax.set_title(f"{inst.capitalize()} file", fontsize=11, color=INK, loc="left")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ["top", "right", "left"]:
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(INK_2)
fig.suptitle("Consolidating with Gurobi cuts transport cost well below all-LTL", fontsize=13, color=INK,
             x=0.02, y=0.98, ha="left", fontweight="bold")
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig("outputs/fig_cost_comparison.png", dpi=200, facecolor="white")
plt.close(fig)
 

# Figure 2: route timeline for day 1 of the Gurobi plan (on main file only considers one depot because showing 24 would be unreadable)
DAY = 1          # which day to plot (simplified: 1-3, main: 1-7)
DEPOT = None     # main file only: for example "D02"; None = the depot of the lowest-numbered tractor

day = DAY
day_tours = sorted([t for t in gurobi["tours"] if t["day"] == day], key=lambda t: t["tractor_id"])
if not day_tours:
    raise SystemExit(f"no tours on day {day}")
scope = ""
if len(day_tours) > 12:                     # main file: keep the figure readable, show one depot
    depot = DEPOT if DEPOT else day_tours[0]["depot_id"]
    day_tours = [t for t in day_tours if t["depot_id"] == depot]
    if not day_tours:
        raise SystemExit(f"no tours from depot {depot} on day {day}")
    scope = f", depot {depot}"
fig_h = 1.1 + 0.48 * len(day_tours)
fig, ax = plt.subplots(figsize=(11, fig_h))
for row, t in enumerate(day_tours):
    y = len(day_tours) - 1 - row
    clock = t["departure"]
    for e in t["events"]:
        ax.barh(y, e["arrival"] - clock, left=clock, height=0.55, color=C_DRIVE, edgecolor="white", linewidth=1)
        if e["service_start"] > e["arrival"]:
            ax.barh(y, e["service_start"] - e["arrival"], left=e["arrival"], height=0.55, color=C_WAIT,
                    edgecolor=C_DRIVE, linewidth=0.6)
        colour = C_PICKUP if e["type"] == "P" else C_DELIVERY
        ax.barh(y, e["service_end"] - e["service_start"], left=e["service_start"], height=0.55, color=colour,
                edgecolor="white", linewidth=1)
        ax.text((e["service_start"] + e["service_end"]) / 2, y + 0.42, e["shipment_id"], ha="center",
                va="bottom", fontsize=7, color=INK)
        clock = e["service_end"]
        if e.get("break_after"):
            ax.barh(y, 0.5, left=clock, height=0.55, color=C_BREAK, edgecolor="white", linewidth=1)
            clock += 0.5
    ax.barh(y, t["return"] - clock, left=clock, height=0.55, color=C_DRIVE, edgecolor="white", linewidth=1)
    ax.text(t["return"] + 0.12, y, f"CAD {t['cost_cad']:,.0f}", va="center", fontsize=8, color=INK_2)
ax.set_yticks(range(len(day_tours)), [f"{t['tractor_id']} ({t['depot_id']})" for t in reversed(day_tours)],
              fontsize=9, color=INK)
lo = min(t["departure"] for t in day_tours) - 0.5
hi = max(t["return"] for t in day_tours) + 1.6
ax.set_xlim(lo, hi)
ax.set_xticks(range(int(lo) + 1, int(hi) + 1), [f"{h:02d}:00" for h in range(int(lo) + 1, int(hi) + 1)],
              fontsize=8, color=INK_2)
ax.grid(axis="x", color=GRID, linewidth=0.8)
ax.set_axisbelow(True)
for side in ["top", "right", "left"]:
    ax.spines[side].set_visible(False)
n_ship = sum(len(t["shipments"]) for t in day_tours)
n_shared = sum(len(t["shipments"]) for t in day_tours if len(t["shipments"]) > 1)
ax.set_title(f"{INSTANCE.capitalize()} file, day {day}{scope}: {len(day_tours)} tractors carry {n_ship} shipments, "
             f"{n_shared} of them on shared tours", fontsize=12, color=INK, loc="left", fontweight="bold", pad=24)
handles = [Patch(color=C_DRIVE, label="Driving"), Patch(facecolor=C_WAIT, edgecolor=C_DRIVE, label="Waiting"),
           Patch(color=C_PICKUP, label="Pickup (0.5 h)"), Patch(color=C_DELIVERY, label="Delivery (0.5 h)")]
if any(e.get("break_after") for t in day_tours for e in t["events"]):
    handles.append(Patch(color=C_BREAK, label="Driver break (0.5 h)"))
ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=len(handles), frameon=False, fontsize=8)
fig.tight_layout()
fig.savefig(f"outputs/fig_route_timeline_{INSTANCE}_day{day}.png", dpi=200, facecolor="white")
plt.close(fig)
print(f"\nWritten: outputs/results_{INSTANCE}.md, outputs/results_{INSTANCE}.csv, "
      f"outputs/fig_cost_comparison.png, outputs/fig_route_timeline_{INSTANCE}_day{day}.png")