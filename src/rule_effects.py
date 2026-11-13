# rule_effects.py - how much does each main-file rule limit consolidation?
#
#
# Method: solve the problem once with all rules, then once more for each rule
# switched off on its own, keeping everything else identical (same data, same tour generation, same
# Gurobi model). The cost difference is what that single rule costs the company.
# The relaxed plans break a real rule, so they are NOT valid plans: they live in outputs/whatif/ and
# are only used for this table. The last row is different: counting a wait of 30+ minutes as the
# driver break is an alternative reading the instructor allowed; we keep the stricter rule and report
# here what the alternative would save.

import json
import subprocess
import sys

INSTANCE = sys.argv[1] if len(sys.argv) > 1 else "main"
CASES = [("none", "All rules (the real plan)"),
         ("no_lifo", "Without strict LIFO (any delivery order)"),
         ("no_compat", "Without compatibility (groups may mix)"),
         ("no_reefer", "Without refrigerated equipment (chilled on DRY)"),
         ("no_hours", "Without facility opening hours (open 0-24)"),
         ("no_break", "Without the 30-minute driver break"),
         ("wait_break", "Waiting of 30+ min counts as the break (allowed alternative)")]

results = []
for relax, label in CASES:
    print(f"running {relax} ...", flush=True)
    run = subprocess.run([sys.executable, "src/approach_a.py", INSTANCE, relax], capture_output=True, text=True)
    if run.returncode != 0:
        raise SystemExit(f"{relax} failed:\n{run.stdout[-2000:]}\n{run.stderr[-2000:]}")
    folder = "outputs" if relax == "none" else "outputs/whatif"
    tag = "" if relax == "none" else f"_{relax}"
    summary = json.load(open(f"{folder}/plan_{INSTANCE}{tag}.json"))["summary"]
    n_cand = len(json.load(open(f"{folder}/candidates_{INSTANCE}{tag}.json"))["candidates"])
    results.append((relax, label, summary, n_cand))

base = results[0][2]
lines = [f"# Effect of each rule: {INSTANCE} file", "",
         "Each row switches off ONE rule and re-optimizes; everything else is unchanged. "
         "Rows other than the first are what-if numbers, not valid plans.", "",
         "| Case | Total cost (CAD) | Cost of the rule (CAD) | Savings vs all-LTL (%) | Candidate tours | "
         "Shipments consolidated | Shipments on LTL | Tours with 1 / 2 / 3 / 4 shipments |",
         "|---|---|---|---|---|---|---|---|"]
for relax, label, s, n_cand in results:
    rule_cost = s["total_cost"] - base["total_cost"]
    sizes = " / ".join(str(s["tours_by_size"].get(str(n), s["tours_by_size"].get(n, 0))) for n in range(1, 5))
    lines.append(f"| {label} | {s['total_cost']:,.2f} | {'-' if relax == 'none' else f'{round(-rule_cost, 2) + 0.0:,.2f}'} | "
                 f"{s['savings_pct']:.1f} | {n_cand:,} | {s['n_shipments_consolidated']} | "
                 f"{s['n_shipments_ltl']} | {sizes} |")

ranked = sorted(results[1:], key=lambda r: r[2]["total_cost"])
lines += ["", "Ranking, from the rule that limits consolidation most to least:"]
for k, (relax, label, s, n_cand) in enumerate(ranked, 1):
    lines.append(f"{k}. {label}: CAD {base['total_cost'] - s['total_cost']:,.2f} "
                 f"({100 * (base['total_cost'] - s['total_cost']) / base['total_cost']:.2f}% of the real cost)")

out = f"outputs/rule_effects_{INSTANCE}.md"
open(out, "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
print(f"\nTable written to {out}")