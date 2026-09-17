# Navaid qualitative notes

Hand-authored, airport-keyed corpus for DuckDB FTS. These notes explain
**why** a metric looks the way it does (leakage, curfew, cargo mix, landside
vs airside). Retrieval returns text and sources only. Numeric traffic facts
come from T-100 / FAA tables; if a note and T-100 disagree, T-100 wins.

Chunks use YAML-like front matter. `airport` may be a comma-separated IATA list
(the loader writes one `doc_chunks` row per code).

---
id: sfo-unmet-airside
airport: SFO
doc_type: qualitative_note
as_of: 2026-09-01
url: https://www.flysfo.com/
title: SFO unmet demand is mostly airside and policy, not a missing concourse
---

San Francisco International (SFO) often shows **high load factors**, peak-period
**delay**, and passenger **leakage** to Oakland (OAK) and San Jose (SJC). That
combination looks like unmet demand, but much of the gap is **airside and
policy**, not a missing terminal concourse.

SFO is noise-sensitive and, at busy hours, **slot**-coordinated. Marine-layer
weather and a constrained airfield/airspace mix add delay that extra holdrooms
do not remove. A **curfew**/noise overlay further limits when operations can
grow. Building gates does not create new slots, does not lift the curfew, and
does not move the marine layer.

Investment reading: treat SFO as **airside-bound** (slots, noise, weather,
airfield) unless a specific project is clearly landside-only (security,
baggage, curb). Unmet demand in the engines is `max(0, implied − served)`;
do not narrate a concourse as the cure for a slot or curfew bottleneck.

---
id: sfo-leakage-oak-sjc
airport: SFO
doc_type: qualitative_note
as_of: 2026-09-01
url: https://www.flysfo.com/
title: SFO leakage to OAK and SJC
---

Bay Area origin-destination passengers routinely **leak** from SFO to **OAK**
and **SJC**. Fare, schedule reliability, and Silicon Valley access all pull
traffic: Oakland often takes price-sensitive and some cargo-adjacent itineraries;
San Jose sits on the South Bay catchment.

Leakage is a demand signal and a scoping warning. If OAK or SJC are adding
seats while SFO load factors stay high, the metro still wants to fly — but
the extra boardings may already be served nearby. Terminal expansion at SFO
does not recapture OAK/SJC unless airside/policy capacity at SFO actually
grows. Same-CBSA airports growing faster while origin load factor is high is
the leakage term in unmet demand; quote T-100 for the quantities.

---
id: oak-bay-area-leakage
airport: OAK
doc_type: qualitative_note
as_of: 2026-09-01
url: https://www.oaklandairport.com/
title: OAK as a Bay Area leakage destination from SFO
---

Oakland International (OAK) is the East Bay alternative in the SFO leakage
set. When SFO is slot-, delay-, or fare-constrained, OAK absorbs metro
passengers rather than leaving them unserved. Cargo and low-cost carrier
mixes are part of OAK's role; do not treat OAK growth as proof that SFO
needs another concourse. Pair with SJC when discussing Bay Area leakage.

---
id: sjc-bay-area-leakage
airport: SJC
doc_type: qualitative_note
as_of: 2026-09-01
url: https://www.flysanjose.com/
title: SJC as Silicon Valley leakage from SFO
---

Norman Y. Mineta San Jose International (SJC) captures Silicon Valley and
South Bay passengers who would otherwise use SFO. Leakage here is catchment
and reliability as much as price. SJC and OAK together are the Bay Area
overflow set for SFO unmet-demand writeups. Segment traffic at SJC is not
unmet demand at SFO; it is demand already served in the same metro.
