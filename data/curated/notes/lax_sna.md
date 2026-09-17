# LAX vs SNA qualitative notes

Santa Ana is **SNA** (John Wayne / Orange County), not SAT (San Antonio).
"LA" resolves to **LAX**, not the whole Los Angeles metro.

---
id: lax-congestion-volume
airport: LAX
doc_type: qualitative_note
as_of: 2026-09-01
url: https://www.flylax.com/
title: LAX congestion is high absolute delay volume
---

Los Angeles International (LAX) typically **wins on absolute delay volume**:
more operations, more delayed flights, more total minutes. That is not the
same as a single congestion score. Compare **delay percentage**, average
arrival delay, cancellations, operations per runway, live FAA status, and
**constraint type** as separate axes.

LAX is a large, multi-terminal complex with mixed landside and airside
bottlenecks. It is **not** curfew-capped the way John Wayne (SNA) is.
A delay-volume win for LAX does not mean SNA is the better place to add
gates, and it does not mean LAX terminal capex unlocks runway slots.

---
id: sna-curfew
airport: SNA
doc_type: qualitative_note
as_of: 2026-09-01
url: https://www.ocair.com/
title: SNA is high-utilization and curfew-capped
---

John Wayne Airport, Santa Ana (SNA, Orange County) is a **high-utilization**
airfield with a nighttime **curfew** and departure noise limits. After the
curfew window, extra terminal square footage cannot create departures.
Treat SNA as **airside-bound** on noise/curfew even when the building looks
busy.

Do not confuse SNA with SAT (San Antonio). Utilization plus curfew is the
congestion story: SNA can look "worse" on intensity while LAX looks worse
on absolute delay counts. Report both; do not invent one congestion number.

---
id: lax-sna-compare
airport: LAX, SNA
doc_type: compare_note
as_of: 2026-09-01
url: https://www.ocair.com/
title: LAX vs SNA — delay volume versus curfew constraint
---

Congestion compare, LAX vs SNA: **LAX** usually leads **absolute delay
volume**; **SNA** is **curfew-capped** and runs hot on utilization. The
useful answer names delay, utilization, and constraint type on each airport.
Terminal renovation at SNA does not buy hours after curfew. Terminal
renovation at LAX does not automatically add airfield slots. Prefer the
engine congestion payload (delay_pct, avg arrival delay, cancel_pct,
ops per runway, live FAA status, constraint type) over this note for
numbers; this note is the qualitative frame.
