# Comparison: main file

| Method | Total cost (CAD) | Savings vs all-LTL (CAD) | Savings (%) | Tours | Shipments on LTL | Dedicated | Consolidated | Tour miles |
|---|---|---|---|---|---|---|---|---|
| All-LTL | 1,557,535.85 | 0.00 | 0.0 | 0 | 800 | 0 | 0 | 0 |
| Savings heuristic | 1,158,522.70 | 399,013.15 | 25.6 | 168 | 509 | 62 | 229 | 66,950 |
| Gurobi (Approach A) | 1,140,762.95 | 416,772.90 | 26.8 | 168 | 492 | 39 | 269 | 68,078 |

Gurobi saves CAD 17,759.75 more than the heuristic (1.5% of the heuristic's cost). Both use the same candidate tours, so the difference comes only from choosing the best combination instead of the best tour first.
Tours in both plans: 106; only in Gurobi's: 62; only in the heuristic's: 62.
