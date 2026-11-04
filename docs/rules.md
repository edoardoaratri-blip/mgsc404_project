# Rules sheet: how we interpret the brief

**Status:** DRAFT v0.1, to be approved by the whole group. After approval, change it only by agreement and note each change in the change log at the bottom.

**Purpose.** This is the single source of truth for every rule. The evaluator (`src/evaluator.py`) and the independent checker (`src/checker.py`) both implement this sheet, **separately and without sharing code**. If they disagree on a plan, either one of them has a bug or this sheet is ambiguous. Fix the sheet first, then the code.

**Sources:** the project brief (`Project_1-Consolidation.pdf`), the data README (`Readme_project1.pdf`) and the workbooks. Every rule cites its source. Where the sources are silent, the rule is marked **[ASSUMPTION]** and listed in section 9 to confirm with the instructor.

Constraint labels (M1 to M3, F1 to F13) refer to the formulation document.

---

## 0. Numerical conventions (read this first)

**R0.1 Integer time.** All times are multiples of 0.25 h. This is verified on both files: windows, facility hours, depot hours, shifts, service times and `drive_hours`. Internally, convert every time to **integer ticks of 15 minutes**: `tick = round(hours * 4)`. All time arithmetic and comparisons are then exact. Never compare floating-point hours with `==`.

**R0.2 Absolute time.** absolute time = 24 × day + hour (README §2). An hour value h on day d becomes 24d + h, which is 4(24d + h) in ticks.

**R0.3 Money.** Compute costs in floating point, but compare costs with a tolerance of CAD 0.01 and report them rounded to 2 decimals. Never round intermediate values.

**R0.4 Read values from the workbook.** Never hard-code a number from the README example (900, 2.20, 45,000 and so on). Read every value from its sheet. The README example is a **test**, not a source of constants (README §6).

**R0.5 Input validation (README §6).** Stop with an error if any of these fails:
- shipment, facility, depot, tractor and equipment IDs are unique;
- every reference is valid;
- every demand and duration is positive;
- every window satisfies open < close;
- every ordered pair of distinct locations has exactly one distance row;
- every shipment matches exactly one LTL rate row.

Both workbooks pass these checks.

---

## 1. Shipments and service (F1, F2, M1)

**R1.1 Served once (M1).** Every shipment is served exactly once: either in exactly one selected tour, or on LTL. A shipment is never split.

**R1.2 Pickup before delivery (F1).** Within a tour, each shipment has exactly one pickup event and exactly one delivery event, and the pickup comes first.

**R1.3 Same day (F2).** All shipments on a tour have the same `day`, and the whole tour (departure to return) happens on that day.

**R1.4 Events.** Each pickup and each delivery is a separate service event of `pickup_service_hours` or `delivery_service_hours` (0.5 h in both files). This is true **even when two events are at the same facility**: two events at the same address take 2 × 0.5 h, one after the other. Handling counts as duty and is not a break (README §3).

**R1.5 Same-location travel.** Travel between two consecutive events at the same location takes 0 miles and 0 h (README: "same-location travel is zero and has no row"). This happens often: on the simplified file 18 (day, origin) pairs have two or more shipments, and on the main file 161.

---

## 2. Time windows and opening hours (F6, F7)

**R2.1 Service interval.** An event with service start s and handling time σ occupies [s, s + σ].

**R2.2 Window rule (README §3).** For a pickup of shipment i on day d, with all values in ticks:

- earliest start = 24d + max(`pickup_open_hour`, facility `open_hour`)
- latest end = 24d + min(`pickup_close_hour`, facility `close_hour`)
- the event is feasible if earliest start ≤ s **and** s + σ ≤ latest end.

Deliveries use the same rule with the `delivery_*` columns and the destination facility.

**R2.3 Boundaries.**
- Finishing **exactly** at closing time is allowed (≤, not <).
- Arriving at closing time is **too late**, because the full 0.5 h of handling must fit (README §5, point 3).

**R2.4 Waiting.** A tractor that arrives early waits until the earliest start. Waiting time counts as duty (README §3). The truck waits outside the site, so there is no queue or dock capacity to model.

**R2.5 Start as early as possible at each stop.** Once the tractor has arrived, service starts at max(arrival, earliest start). Delaying service at a facility can never help, so all the scheduling freedom is in the departure time (R4.4).

**R2.6 Depot and shift (F7).** The tractor departs no earlier than 24d + max(`shift_start_hour`, depot `open_hour`), and returns no later than 24d + min(`shift_end_hour`, depot `close_hour`). Returning exactly at the limit is allowed.

**R2.7 No overnight tours.** A tour never spans two days. This follows from R2.6, since every shift ends by 20:00.

---

## 3. Capacity (F4)

**R3.1 Three separate dimensions.** Weight (lb), floor length (ft) and pallet positions are checked separately against the **assigned tractor's** equipment row. Use DRY or REEFER as assigned, never the largest capacity in the table (README §3).

**R3.2 Additive loads.** On board = the sum of all shipments picked up and not yet delivered. No stacking or packing gains (README §3).

**R3.3 Check after every event.** The load is checked after every pickup and every delivery. In practice, only pickups can raise the load. The load is feasible if it is ≤ capacity (equal is allowed).

**R3.4 Empty at the end.** The trailer is empty when it returns to the depot. This follows from R1.2.

---

## 4. Driving, duty and tour structure (F3, F5, F8, F9, M2)

**R4.1 Lanes.** Travel uses the directed `distance_matrix` row (from, to) exactly as given: `distance_miles` and `drive_hours`.
- Never compute shortest paths or go through an intermediate location (README §3). The direct lane is used even where a two-leg path would be faster: this happens for 12 location triples on the simplified file and 30 on the main file.
- Never assume the reverse lane has the same value. The current files happen to be symmetric, but the code must not depend on it.

**R4.2 Driving limit (F8).** Total driving = the sum of `drive_hours` over all legs, including the depot approach and the return. It must be ≤ `max_drive_hours` (8 simplified, 11 main).

**R4.3 Duty limit (F9).** Duty = return time − departure time. It includes driving, handling, waiting and breaks, and must be ≤ `max_duty_hours` (12 simplified, 14 main). **Time spent at the depot before departure is not duty**: the duty clock starts at departure.

**R4.4 Choosing the departure time.** For a fixed stop order, the generator tries every departure tick from the earliest allowed (R2.6), simulating each with R2.5. It keeps the feasible schedule with the **shortest duty**; ties go to the earliest departure. The search runs up to the latest departure that still lets the first service finish inside its window. Do not stop earlier: leaving later can still remove waiting at a later stop.
- Rationale: leaving later can only remove waiting, and the cost does not depend on timing.
- This makes the generator **exact** for a given order: if any feasible schedule exists, it finds one.

**R4.5 Stop limit (F3).** N = 2 × (number of shipments) ≤ `max_stops`: at most 3 shipments per tour on the simplified file and 4 on the main file. Depot departure and return are not events.

**R4.6 One tour per tractor per day (M2).** A tractor does at most one tour per day. A tractor that is not used costs nothing.

**R4.7 Rest between days.** `min_rest_hours` is already guaranteed by the fixed shifts: the shortest gap between shifts is 12 h on the simplified file and 10 h on the main file, both ≥ the minimum. No extra check is needed, but the checker reports it as a sanity check.

---

## 5. Costs (objective)

**R5.1 LTL cost.**
- Match on `freight_class`, the weight band and the distance band.
- **Lower bounds are inclusive and upper bounds exclusive** (README §3): 15,000 lb belongs to the band that **starts** at 15,000.
- The distance is the **direct** origin-to-destination `distance_miles`, not any tour distance.
- Cost l_i = `base_cost_cad` × (1 + `fuel_surcharge_pct`). A surcharge of 0.15 means 15%.
- A missing match or more than one match is an input error, never a zero cost.

**R5.2 Truckload (TL) cost.** For a tour with total miles M (including both depot legs) and N events, using the assigned tractor's equipment row in `tl_costs`:

```
c = max(minimum_linehaul_cad, M × linehaul_cad_per_mile) + max(0, N − 2) × extra_stop_cad
```

There is no fuel surcharge, hourly cost or driver cost on top (README §3).

**R5.3 Reference values** (to test the code, not to use as constants):
- all-LTL = CAD 93,298.35 (simplified) and CAD 1,557,535.85 (main);
- the README tour D01→F01→F02→F04→F03→D01 with T01 = 350 mi, 4 events, CAD 1,000.00, 7 h driving, 9 h duty;
- S001 + S002 by LTL = CAD 2,742.75.

---

## 6. Main-file rules (F10 to F13)

These are switched on by the data: `lifo_required`, the equipment rows and the groups. On the simplified file they are always satisfied. Implement them anyway, so the same code runs on both files.

**R6.1 Equipment (F10).**
- A `chilled` shipment may only ride on equipment with `chilled_capable = 1` (REEFER).
- Ambient freight may ride on DRY or REEFER (README §3).
- REEFER has its own capacities (42,000 lb, 48 ft, 24 pallets) and costs (2.55 per mile, 1,050 minimum, 65 per extra stop): read them from the sheets.

**R6.2 Compatibility (F11).** Two shipments i and j are **on board together** if π_i < ρ_j and π_j < ρ_i, where π is the position of the pickup and ρ the position of the delivery. While on board together they must have the **same `temperature` and the same `compatibility_group`**. Shipments that do not overlap may differ: for example, deliver a food load, then pick up an industrial one.

Groups on the main file: ambient-general 652, ambient-food 32, ambient-industrial 38, chilled-food 47, chilled-industrial 31.

**R6.3 Strict LIFO (F12), only when `lifo_required = 1`.**
- Treat the trailer as a stack. Every pickup pushes the shipment on top. Every delivery must remove the shipment **currently on top**.
- Equivalently: if π_i < π_j < ρ_i, then ρ_j < ρ_i. P1 P2 D2 D1 is valid; P1 P2 D1 D2 is invalid.
- There is no rehandling (README §3).
- When `lifo_required = 0` (side access), any shipment on board may be delivered next.

**R6.4 Driver break (F13), main file.**
- **Definitions.** G = the driving accumulated since the last break (or since departure). A break is 0.5 h of uninterrupted off-duty time at a **stopped location**, taken **after** the service of some event j and before driving on.
- **Rule.** G must never exceed `break_after_drive_hours` = 8 h. A leg cannot be split by a break. This is safe because every single lane is ≤ 8 h: the longest is 4.5 h on the simplified file and 6.75 h on the main file.
- **Effect.** A break resets G only. It counts toward duty (R4.3) and delays every later event by 0.5 h. It does **not** reset total driving (R4.2).
- **Handling.** Handling time never counts as a break.
- **[ASSUMPTION] Waiting is not a break.** We never count waiting as a break, which is conservative: the README allows it only "if explicitly recorded". Open question Q2.
- **Where to place it.** Since total driving ≤ 11 h < 16 h, a tour needs **at most one** break. The generator tries "no break" and "break after event j" for every j, and keeps the feasible option with the shortest duty.
- **Simplified file.** No break is ever needed: the 8 h drive cap equals the threshold (brief, table on page 2).

---

## 7. Candidate generation (what the tour set R contains)

**R7.1 Simplified file: complete enumeration.** For each day, list every set of 1, 2 or 3 shipments (20, 190 and 1,140 sets per day). For each set, list every order that satisfies R1.2: 1, 6 and 90 orders. For each tractor group (R7.3), keep the orders that pass all the rules above. Because the enumeration is complete, a zero MIP gap is a **global** optimum.

**R7.2 Main file: restricted enumeration.**
- Build triples only from sets whose sub-pairs are all feasible, and quadruples only from sets whose sub-triples are all feasible.
- Skip any set that has to carry two incompatible shipments together. With strict LIFO the number of orders per set of 1, 2, 3 and 4 shipments drops to 1, 4, 30 and 336.
- This rule **can miss feasible tours**, because direct lanes do not always obey the triangle inequality (R4.1). Report the main-file result as "optimal over the generated candidates" and state this rule in the report (brief, grading section).

**R7.3 Tractor groups (recommended).** Tractors with the same home depot, equipment and shift are interchangeable:
- simplified: 2 groups of 4;
- main: 9 groups (D01 DRY 6–18 × 4, D01 DRY 6–20 × 1, D01 REEFER × 1, D02 DRY × 5, D02 REEFER × 1, D03 DRY × 5, D03 REEFER × 1, D04 DRY × 5, D04 REEFER × 1).

Generate each candidate once per **group**, not once per tractor, and replace M2 with "selected tours of group g on day d ≤ number of tractors in g". Then give the selected tours actual tractor IDs in any order. This gives the same optimum, with 4 to 5 times fewer variables and no symmetry, which also helps Gurobi. **If we use it, the formulation must state it.**

---

## 8. Reporting definitions (brief, "Results and recommendation")

**R8.1 Shipment counts.** The number of shipments on LTL, on dedicated tours (1 shipment) and on consolidated tours (2 or more).

**R8.2 Total tour miles.** The sum of M over the selected tours, including empty depot legs.

**R8.3 Utilization [ASSUMPTION].** The brief asks for weight and floor-length utilization separately but does not define them. We report:
- **Peak utilization:** max load ÷ capacity on each tour, averaged over tours.
- **Mile-weighted utilization:** Σ over legs (miles × load) ÷ Σ over legs (miles × capacity), over all legs of all selected tours, including empty legs.

Both are computed for weight and for floor length. Open question Q3.

**R8.4 Extra transit time.** For each shipment on a tour: extra time = (delivery service end − pickup service end) − (direct `drive_hours` from origin to destination + delivery service time). It is 0 when the shipment rides alone with no waiting. Report the average and the maximum. Never report an extra calendar day (brief).

**R8.5 Run facts.** Report the Gurobi version, the parameters we change, the runtime per day and in total, the status, the objective, the MIP gap, the number of candidates and the checker verdict.

---

## 9. Open questions for the instructor

- **Q1.** Is a set-partitioning formulation acceptable as the full MILP, if F1 to F13 are written out mathematically but enforced during candidate generation?
- **Q2.** May waiting of 0.5 h or more count as the driver break?
- **Q3.** Which definition of weight and floor-length utilization do you expect?
- **Q4.** May we group identical tractors (R7.3) in the model, as long as the plan reports individual tractor IDs?

---

## Change log

| Date | Version | Change | Agreed by |
|---|---|---|---|
| 2026-10-27 | 0.1 | First draft | (to approve) |
