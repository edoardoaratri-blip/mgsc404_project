# Results: main file

Gurobi status: OPTIMAL, gap 0.0000%, Gurobi 13.0.3, 4,726 candidate tours (optimal over the candidate tours).

| Metric | All-LTL | Savings heuristic | Gurobi (Approach A) |
|---|---|---|---|
| Total cost (CAD) | 1,557,535.85 | 1,158,522.70 | 1,140,762.95 |
| Savings vs all-LTL (CAD) | 0.00 | 399,013.15 | 416,772.90 |
| Savings vs all-LTL (%) | 0.00 | 25.62 | 26.76 |
| Tours | 0 | 168 | 168 |
| Shipments on LTL | 800 | 509 | 492 |
| Shipments on a dedicated tour | 0 | 62 | 39 |
| Shipments on a tour with 2+ shipments | 0 | 229 | 269 |
| Weight utilization, peak per tour (avg %) |  | 42.92 | 46.02 |
| Floor-length utilization, peak per tour (avg %) |  | 55.84 | 56.54 |
| Weight utilization, mile-weighted (%) |  | 16.19 | 16.81 |
| Floor-length utilization, mile-weighted (%) |  | 21.93 | 21.92 |
| Total tour miles (incl. depot legs) | 0.00 | 66,950.00 | 68,078.00 |
|   of which empty miles |  | 36,820.00 | 37,339.00 |
| Extra time vs direct trip, average (h) |  | 0.39 | 0.42 |
| Extra time vs direct trip, maximum (h) |  | 5.00 | 4.00 |
| Checker verdict |  | ACCEPT | ACCEPT |
| Gurobi solve time (s) |  |  | 0.14 |
| Total run time (s) |  | 0.01 | 9.80 |
