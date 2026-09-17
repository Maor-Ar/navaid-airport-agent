from __future__ import annotations

from datetime import date
from navaid.config import DEEP_SLICE_IATA, PROJECT_ROOT
from navaid.ingest.bts import parse_delay_cause, parse_t100_segments
from navaid.ingest.curated import load_catchment, load_constraints, load_gates
from navaid.ingest.faa import parse_enplanements, parse_npias, parse_taf
from navaid.ingest.ourairports import parse_airports, parse_runways
from navaid.ingest.util import MILES_TO_KM

FIXTURES = PROJECT_ROOT / "data" / "fixtures"
AS_OF = date(2024, 12, 31)


def test_parse_ourairports_fixture_us_scheduled_with_iata() -> None:
    airports = parse_airports(FIXTURES / "ourairports_airports.csv", as_of=AS_OF)
    iatas = set(airports["iata"])
    assert "BOS" in iatas
    assert "ANC" in iatas
    assert "LHR" not in iatas  # not US
    assert "SAT" in iatas
    assert airports["icao"].str.startswith("K").any() or (airports["icao"] == "PANC").any()
    runways = parse_runways(
        FIXTURES / "ourairports_runways.csv",
        airport_icaos=set(airports["icao"]),
    )
    assert not runways.empty
    assert set(runways["icao"]).issubset(set(airports["icao"]))


def test_parse_enplanements_csv_and_xlsx() -> None:
    csv_df = parse_enplanements(FIXTURES / "faa_enplanements.csv", as_of=AS_OF, year=2024)
    bos = csv_df.loc[csv_df["iata"] == "BOS"].iloc[0]
    assert int(bos["enplanements"]) == 21_090_721
    assert bos["hub_size"] == "Large"
    assert bos["yoy"] > 0

    sna = csv_df.loc[csv_df["iata"] == "SNA"].iloc[0]
    assert sna["hub_size"] == "Medium"
    assert sna["yoy"] < 0

    xlsx = parse_enplanements(FIXTURES / "faa_enplanements.xlsx", as_of=AS_OF, year=2024)
    assert set(xlsx["iata"]) >= {"BOS", "BDL", "LAX", "SNA"}
    assert int(xlsx.loc[xlsx["iata"] == "BDL", "enplanements"].iloc[0]) == 3_285_194


def test_parse_t100_fixture_not_full_zip() -> None:
    df = parse_t100_segments(FIXTURES / "t100_segments.csv", as_of=AS_OF)
    anc_jfk = df[(df["origin"] == "ANC") & (df["dest"] == "JFK")]
    assert not anc_jfk.empty
    km = float(anc_jfk["distance_km"].iloc[0])
    assert abs(km - 3370 * MILES_TO_KM) < 1.0  # ~5423 km
    # Cargo class G with zero pax/seats is dropped.
    assert int(anc_jfk["passengers"].sum()) == 18500 + 14200
    intl = df[(df["origin"] == "ANC") & (df["dest"] == "NRT")]
    assert bool(intl["international"].iloc[0]) is True
    bos_lax = df[(df["origin"] == "BOS") & (df["dest"] == "LAX")]
    assert int(bos_lax["passengers"].iloc[0]) == 64000


def test_parse_delay_cause_airport_month() -> None:
    df = parse_delay_cause(FIXTURES / "delay_cause.csv", as_of=AS_OF, universe_iata={"SFO", "SNA"})
    assert set(df["iata"]) == {"SFO", "SNA"}
    assert set(df["month"].astype(int)) == set(range(1, 13))
    sfo = df.loc[df["iata"] == "SFO"].iloc[0]
    assert 0 < float(sfo["delay_pct"]) < 1
    assert 0 < float(sfo["cancel_pct"]) < 1
    assert sfo["operations"] > 0


def test_parse_taf_and_npias_fixtures() -> None:
    taf = parse_taf(FIXTURES / "taf.csv", as_of=date(2025, 3, 1))
    assert set(taf["iata"]) >= {"BOS", "SFO", "ANC"}
    assert 2035 in set(taf["forecast_year"].astype(int))
    npias = parse_npias(FIXTURES / "npias.csv", as_of=date(2024, 10, 28))
    sna = npias.loc[npias["iata"] == "SNA"].iloc[0]
    assert "airside" in str(sna["development_need"]).lower() or "constrained" in str(sna["development_need"]).lower()


def test_curated_gates_catchment_constraints() -> None:
    gates = load_gates()
    assert set(DEEP_SLICE_IATA).issubset(set(gates["iata"]))
    assert int(gates.loc[gates["iata"] == "SNA", "gate_count"].iloc[0]) == 20

    catchment = load_catchment()
    bay = catchment.loc[catchment["iata"].isin(["SFO", "OAK", "SJC"]), "cbsa_code"]
    assert set(bay) == {"SFBAY"}
    la = catchment.loc[catchment["iata"].isin(["LAX", "SNA"]), "cbsa_code"]
    assert set(la) == {"31080"}

    constraints = load_constraints()
    sna = constraints.loc[constraints["iata"] == "SNA"].iloc[0]
    assert sna["constraint_type"] == "airside"
    assert "22:00" in str(sna["curfew"])
    sfo = constraints.loc[constraints["iata"] == "SFO"].iloc[0]
    assert sfo["constraint_type"] == "airside"
    assert "slot" in str(sfo["notes"]).lower() or "gdp" in str(sfo["notes"]).lower()
