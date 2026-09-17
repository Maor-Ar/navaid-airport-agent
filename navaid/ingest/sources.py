"""Public-file URLs and fixture fallbacks for warehouse ingest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from navaid.config import (
    BTS_PREZIP_URL,
    FAA_ENPLANEMENTS_PAGE_URL,
    FAA_TAF_URL,
    OURAIRPORTS_AIRPORTS_URL,
    OURAIRPORTS_RUNWAYS_URL,
)
from navaid.ingest.util import FIXTURES_DIR


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    urls: tuple[str, ...]
    fixture_name: str | None = None
    as_of: date = date(2024, 12, 31)
    notes: str = ""

    @property
    def fixture_path(self):
        if not self.fixture_name:
            return None
        return FIXTURES_DIR / self.fixture_name


OURAIRPORTS_AIRPORTS = SourceSpec(
    source_id="ourairports_airports",
    urls=(OURAIRPORTS_AIRPORTS_URL,),
    fixture_name="ourairports_airports.csv",
    as_of=date(2024, 12, 31),
    notes="OurAirports airports.csv; filter to US scheduled with IATA.",
)

OURAIRPORTS_RUNWAYS = SourceSpec(
    source_id="ourairports_runways",
    urls=(OURAIRPORTS_RUNWAYS_URL,),
    fixture_name="ourairports_runways.csv",
    as_of=date(2024, 12, 31),
    notes="OurAirports runways.csv.",
)

FAA_ENPLANEMENTS = SourceSpec(
    source_id="faa_enplanements",
    urls=(
        # CY 2024 commercial-service Excel (hrefs rotate; try several).
        "https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger/arp-cy2024-commercial-service-enplanements.xlsx",
        "https://www.faa.gov/sites/faa.gov/files/2025-09/cy24-commercial-service-enplanements.xlsx",
        "https://www.faa.gov/sites/faa.gov/files/airports/planning_capacity/passenger_allcargo_stats/passenger/cy24-commercial-service-enplanements.xlsx",
        "https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger/cy23-commercial-service-enplanements.xlsx",
        FAA_ENPLANEMENTS_PAGE_URL,
    ),
    fixture_name="faa_enplanements.csv",
    as_of=date(2024, 12, 31),
    notes="FAA CY commercial-service enplanements (Excel). Fixture is a CY2024 extract.",
)

# Full CY2024 commercial-service extract used when the tiny fixture is too small
# for a demo warehouse. Still a checked-in file so offline builds work.
FAA_ENPLANEMENTS_FULL = SourceSpec(
    source_id="faa_enplanements_full",
    urls=(),
    fixture_name="faa_enplanements_cy2024.csv",
    as_of=date(2024, 12, 31),
    notes="Checked-in CY2024 commercial-service table extracted from the FAA PDF.",
)

BTS_T100_SEGMENT = SourceSpec(
    source_id="bts_t100_segment",
    urls=(
        # TranStats prezip names rotate; snapshot builder also scrapes PREZIP.
        "https://transtats.bts.gov/PREZIP/T_T100_SEGMENT_ALL_CARRIER.zip",
        f"{BTS_PREZIP_URL}T_T100_SEGMENT_ALL_CARRIER.zip",
        "https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FIM&QO_fu146_anzr=Nv4%20Pn44vr45",
    ),
    fixture_name="t100_segments.csv",
    as_of=date(2024, 12, 31),
    notes="BTS T-100 Segment (All Carriers). Stream/filter; never keep the raw ZIP.",
)

BTS_DELAY_CAUSE = SourceSpec(
    source_id="bts_delay_cause",
    urls=(
        # Airport-month delay-cause (not flight-level OTP). Socrata IDs rotate.
        "https://data.bts.gov/resource/6a7x-jbn2.csv?$limit=50000",
        "https://www.transtats.bts.gov/ot_delay/OT_DelayCause1.asp",
        "https://data.bts.gov/api/views/6a7x-jbn2/rows.csv?accessType=DOWNLOAD",
    ),
    fixture_name="delay_cause.csv",
    as_of=date(2024, 12, 31),
    notes="BTS airline delay-cause airport-month aggregates.",
)

FAA_TAF = SourceSpec(
    source_id="faa_taf",
    urls=(
        "https://taf.faa.gov/Downloads/TAF2025.xlsx",
        "https://taf.faa.gov/Downloads/TAF_database.xlsx",
        FAA_TAF_URL,
    ),
    fixture_name="taf.csv",
    as_of=date(2025, 3, 1),
    notes="FAA Terminal Area Forecast. UI is awkward; fixture/curated deep-slice if bulk file missing.",
)

NPIAS_APPENDIX_A = SourceSpec(
    source_id="npias_appendix_a",
    urls=(
        "https://www.faa.gov/sites/faa.gov/files/airports/planning_capacity/npias/current/ARP-NPIAS-2025-2029-Appendix-A.xlsx",
        "https://www.faa.gov/sites/faa.gov/files/airports/planning_capacity/npias/current/NPIAS-2025-2029-Appendix-A.xlsx",
    ),
    fixture_name="npias.csv",
    as_of=date(2024, 10, 28),
    notes="NPIAS 2025-2029 Appendix A. Feasibility only; missing → drop-and-renormalize later.",
)

ALL_SPECS: tuple[SourceSpec, ...] = (
    OURAIRPORTS_AIRPORTS,
    OURAIRPORTS_RUNWAYS,
    FAA_ENPLANEMENTS,
    BTS_T100_SEGMENT,
    BTS_DELAY_CAUSE,
    FAA_TAF,
    NPIAS_APPENDIX_A,
)
