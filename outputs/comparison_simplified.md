# Comparison: simplified file

| Method | Total cost (CAD) | Savings vs all-LTL (CAD) | Savings (%) | Tours | Shipments on LTL | Dedicated | Consolidated | Tour miles |
|---|---|---|---|---|---|---|---|---|
| All-LTL | 93,298.35 | 0.00 | 0.0 | 0 | 60 | 0 | 0 | 0 |
| Savings heuristic | 36,349.65 | 56,948.70 | 61.0 | 24 | 8 | 0 | 52 | 7,893 |
| Gurobi (Approach A) | 36,246.15 | 57,052.20 | 61.2 | 24 | 8 | 0 | 52 | 7,953 |

Gurobi saves CAD 103.50 more than the heuristic (0.3% of the heuristic's cost). Both use the same candidate tours, so the difference comes only from choosing the best combination instead of the best tour first.
Tours in both plans: 11; only in Gurobi's: 13; only in the heuristic's: 13.
