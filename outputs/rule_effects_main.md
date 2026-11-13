# Effect of each rule: main file

Each row switches off ONE rule and re-optimizes; everything else is unchanged. Rows other than the first are what-if numbers, not valid plans.

| Case | Total cost (CAD) | Cost of the rule (CAD) | Savings vs all-LTL (%) | Candidate tours | Shipments consolidated | Shipments on LTL | Tours with 1 / 2 / 3 / 4 shipments |
|---|---|---|---|---|---|---|---|
| All rules (the real plan) | 1,140,762.95 | - | 26.8 | 4,726 | 269 | 492 | 39 / 118 / 11 / 0 |
| Without strict LIFO (any delivery order) | 1,115,998.30 | 24,764.65 | 28.4 | 5,410 | 301 | 472 | 27 / 122 / 19 / 0 |
| Without compatibility (groups may mix) | 1,128,085.85 | 12,677.10 | 27.6 | 4,858 | 276 | 487 | 37 / 117 / 14 / 0 |
| Without refrigerated equipment (chilled on DRY) | 1,139,406.75 | 1,356.20 | 26.9 | 5,055 | 267 | 492 | 41 / 114 / 13 / 0 |
| Without facility opening hours (open 0-24) | 1,140,762.95 | 0.00 | 26.8 | 4,726 | 269 | 492 | 39 / 118 / 11 / 0 |
| Without the 30-minute driver break | 1,130,119.05 | 10,643.90 | 27.4 | 5,052 | 277 | 486 | 37 / 116 / 15 / 0 |
| Waiting of 30+ min counts as the break (allowed alternative) | 1,137,956.25 | 2,806.70 | 26.9 | 4,791 | 272 | 490 | 38 / 118 / 12 / 0 |

Ranking, from the rule that limits consolidation most to least:
1. Without strict LIFO (any delivery order): CAD 24,764.65 (2.17% of the real cost)
2. Without compatibility (groups may mix): CAD 12,677.10 (1.11% of the real cost)
3. Without the 30-minute driver break: CAD 10,643.90 (0.93% of the real cost)
4. Waiting of 30+ min counts as the break (allowed alternative): CAD 2,806.70 (0.25% of the real cost)
5. Without refrigerated equipment (chilled on DRY): CAD 1,356.20 (0.12% of the real cost)
6. Without facility opening hours (open 0-24): CAD 0.00 (0.00% of the real cost)
