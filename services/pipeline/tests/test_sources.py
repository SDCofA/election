import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
import pytest

from elexion_pipeline.adapters.dawum import parse_dawum
from elexion_pipeline.adapters.eurostat import EurostatAdapter
from elexion_pipeline.adapters.geoboundaries import GeoBoundariesAdapter, validate_geojson
from elexion_pipeline.adapters.http import HttpSnapshotFetcher, SourceResponseError
from elexion_pipeline.adapters.oecd import OecdAdapter
from elexion_pipeline.adapters.official import (
    CalendarParserConfig,
    OfficialElectionAdapter,
    parse_calendar,
)
from elexion_pipeline.adapters.official_results import (
    OfficialResultAdapter,
    ResultParserConfig,
)
from elexion_pipeline.adapters.retired_event import aggregate_security_events, parse_last_update
from elexion_pipeline.adapters.vdem import VDemAdapter
from elexion_pipeline.adapters.world_bank import WorldBankAdapter
from elexion_pipeline.checkpoint import MemoryCheckpointStore
from elexion_pipeline.definitions import _publication_is_durable, _validate_forecast_payload
from elexion_pipeline.domain import RawSnapshot, SourceDefinition
from elexion_pipeline.registry import SourceNotApprovedError, SourceRegistry
from elexion_pipeline.storage import LocalObjectStore, SnapshotWriter


def _source(**overrides) -> SourceDefinition:
    values = {
        "id": "test",
        "name": "Test",
        "base_url": "https://data.example.test/v1/",
        "allowed_hosts": ["data.example.test"],
        "authority": "official",
        "license_id": "CC-BY-4.0",
        "license_name": "CC BY 4.0",
        "license_url": "https://example.test/license",
        "attribution": "Test source",
        "approved": True,
        "max_bytes": 1024,
        "freshness_hours": 24,
        "content_types": ["application/json"],
    }
    values.update(overrides)
    return SourceDefinition.model_validate(values)


def _snapshot(content_type: str) -> RawSnapshot:
    return RawSnapshot(
        source_id="test",
        source_url="https://data.example.test/calendar",
        retrieved_at=datetime(2026, 8, 9, tzinfo=UTC),
        sha256="a" * 64,
        byte_count=1,
        content_type=content_type,
        object_key="raw/test/a.bin",
        object_uri="file:///tmp/a.bin",
        license_id="CC-BY-4.0",
        attribution="Test source",
        usage_scope="Fixture calendar only",
    )


def test_registry_rejects_source_before_network(tmp_path):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    source = _source(approved=False, license_id="PENDING")
    fetcher = HttpSnapshotFetcher(
        SourceRegistry([source]),
        SnapshotWriter(LocalObjectStore(tmp_path)),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(SourceNotApprovedError):
        fetcher.fetch("test", "payload")
    assert calls == 0


def test_packaged_registry_records_authority_license_decisions():
    registry = SourceRegistry.from_path()
    assert {item.id for item in registry.approved()} >= {
        "world_bank_wdi",
        "vdem_github",
        "eurostat_sdmx",
        "oecd_sdmx",
        "dawum_polls",
        "uk_electoral_commission",
        "germany_federal_returning_officer",
        "eu_parliament_elections",
        "us_fec_calendar",
        "fivethirtyeight_historical_polls",
        "latvia_cvk_open_data",
    }
    assert {item.id for item in registry.blocked()} >= {
        "RetiredEvent_events",
        "imf_sdmx",
        "egypt_nea",
        "african_union_calendar",
        "international_idea_esd",
        "latvia_cvk_web",
        "israel_election_authorities_web",
        "new_zealand_electoral_commission_web",
    }


def test_pack_citations_exactly_match_source_license_registry():
    registry = SourceRegistry.from_path()
    packs = Path(__file__).parents[2] / "api" / "app" / "packs"
    for path in packs.rglob("*.json"):
        pack = json.loads(path.read_text(encoding="utf-8"))
        adapters = {item["source_id"]: item for item in pack["source_adapters"]}
        for citation in pack["election"]["sources"]:
            assert citation["source_id"] in adapters
            if adapters[citation["source_id"]]["status"] == "reference_only_no_ingestion":
                assert citation["license"] == "LINK-ONLY-NO-INGESTION"
                assert citation["url"].startswith("https://")
                continue
            source = registry.get(citation["source_id"])
            assert citation["license"] == source.license_id
            assert citation["license_url"] == source.license_url


def test_dawum_parser_normalizes_parties_and_uses_conservative_daily_vintage():
    payload = {
        "Database": {
            "License": {
                "Shortcut": "ODC-ODbL",
                "Link": "https://opendatacommons.org/licenses/odbl/1-0/",
            },
            "Last_Update": "2026-08-09T09:59:34+02:00",
        },
        "Institutes": {"5": {"Name": "INSA"}},
        "Taskers": {"3": {"Name": "Publisher"}},
        "Methods": {"4": {"Name": "Telefon & Online"}},
        "Surveys": {
            "4265": {
                "Date": "2026-08-08",
                "Survey_Period": {
                    "Date_Start": "2026-08-03",
                    "Date_End": "2026-08-07",
                },
                "Surveyed_Persons": "1205",
                "Parliament_ID": "0",
                "Institute_ID": "5",
                "Tasker_ID": "3",
                "Method_ID": "4",
                "Results": {"1": 30, "7": 25, "2": 20, "4": 15, "0": 10},
            }
        },
    }
    snapshot = _snapshot("application/json").model_copy(
        update={
            "source_id": "dawum_polls",
            "source_url": "https://api.dawum.de/",
            "license_id": "ODC-ODbL-1.0",
        }
    )
    batch = parse_dawum(
        json.dumps(payload).encode(),
        snapshot,
        election_id="de-next-bundestag",
        parliament_id="0",
        party_mapping={"1": "union", "7": "afd", "2": "spd", "4": "greens"},
        unmapped_contestant_id="other",
        parser_version="fixture-v1",
    )
    poll = batch.polls[0]
    assert poll.poll_key == "dawum:4265"
    assert poll.mode == "mixed"
    assert poll.sample_size == 1205
    assert poll.shares == {
        "afd": 0.25,
        "greens": 0.15,
        "other": 0.1,
        "spd": 0.2,
        "union": 0.3,
    }
    assert poll.available_at.isoformat() == "2026-08-09T00:00:00+02:00"
    assert poll.available_at > poll.released_at


def test_fetcher_persists_content_addressed_snapshot(tmp_path):
    def handler(request):
        return httpx.Response(
            200,
            json={"ok": True},
            headers={"ETag": '"v1"', "Content-Type": "application/json"},
            request=request,
        )

    store = LocalObjectStore(tmp_path)
    fetcher = HttpSnapshotFetcher(
        SourceRegistry([_source()]),
        SnapshotWriter(store),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    first = fetcher.fetch("test", "payload")
    second = fetcher.fetch("test", "payload")
    assert first is not None and second is not None
    assert first.snapshot.sha256 == second.snapshot.sha256
    assert store.read(first.snapshot.object_key) == first.content
    assert first.snapshot.etag == '"v1"'


def test_fetcher_rejects_host_and_oversized_payload(tmp_path):
    source = _source(max_bytes=3)
    fetcher = HttpSnapshotFetcher(
        SourceRegistry([source]),
        SnapshotWriter(LocalObjectStore(tmp_path)),
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    content=b"1234",
                    headers={"content-type": "application/json"},
                    request=request,
                )
            )
        ),
    )
    with pytest.raises(ValueError, match="allowlisted"):
        fetcher.fetch("test", "https://attacker.invalid/payload")
    with pytest.raises(SourceResponseError, match="exceeds"):
        fetcher.fetch("test", "payload")


def test_world_bank_adapter_preserves_retrieval_vintage(tmp_path):
    payload = [
        {"page": 1, "pages": 1, "total": 1},
        [
            {
                "country": {"value": "Türkiye"},
                "countryiso3code": "TUR",
                "indicator": {"id": "FP.CPI.TOTL.ZG", "value": "Inflation"},
                "date": "2025",
                "value": 34.2,
                "decimal": 1,
            }
        ],
    ]

    def handler(request):
        return httpx.Response(
            200, json=payload, headers={"content-type": "application/json"}, request=request
        )

    source = _source(
        id="world_bank_wdi",
        base_url="https://api.worldbank.org/v2/",
        allowed_hosts=["api.worldbank.org"],
        max_bytes=10000,
    )
    fetcher = HttpSnapshotFetcher(
        SourceRegistry([source]),
        SnapshotWriter(LocalObjectStore(tmp_path)),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    batch = WorldBankAdapter(fetcher).fetch_indicators(["TUR"], ["FP.CPI.TOTL.ZG"], 2025, 2025)
    observation = batch.observations[0]
    assert observation.jurisdiction_id == "tur"
    assert observation.observed_at == datetime(2025, 12, 31, tzinfo=UTC)
    assert observation.available_at == batch.snapshots[0].retrieved_at
    assert observation.dimensions["vintage_limit"] == "retrieval-time-only"


def test_eurostat_sdmx_adapter_preserves_retrieval_vintage(tmp_path):
    payload = (
        b"STRUCTURE,STRUCTURE_ID,freq,age,unit,sex,geo,TIME_PERIOD,OBS_VALUE,OBS_FLAG,CONF_STATUS\n"
        b"dataflow,ESTAT:UNE_RT_A(1.0),A,Y15-74,PC_ACT,T,DE,2025,3.8,,\n"
    )

    def handler(request):
        return httpx.Response(
            200,
            content=payload,
            headers={"content-type": "application/vnd.sdmx.data+csv;version=2.0.0"},
            request=request,
        )

    source = _source(
        id="eurostat_sdmx",
        base_url="https://ec.europa.eu/eurostat/api/dissemination/sdmx/3.0/",
        allowed_hosts=["ec.europa.eu"],
        max_bytes=10000,
        content_types=["application/vnd.sdmx.data+csv"],
    )
    fetcher = HttpSnapshotFetcher(
        SourceRegistry([source]),
        SnapshotWriter(LocalObjectStore(tmp_path)),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    batch = EurostatAdapter(fetcher).fetch_unemployment({"deu": "DE"}, 2023)
    observation = batch.observations[0]
    assert observation.jurisdiction_id == "deu"
    assert observation.value == 3.8
    assert observation.observed_at == datetime(2025, 12, 31, tzinfo=UTC)
    assert observation.available_at == batch.snapshots[0].retrieved_at
    assert observation.dimensions["vintage_limit"] == "retrieval-time-only"


def test_oecd_sdmx_adapter_preserves_retrieval_vintage(tmp_path):
    payload = (
        b"DATAFLOW,REF_AREA,FREQ,METHODOLOGY,MEASURE,UNIT_MEASURE,EXPENDITURE,"
        b"ADJUSTMENT,TRANSFORMATION,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
        b"OECD.SDD.TPS:DSD_PRICES@DF_PRICES_ALL(1.0),DEU,A,N,CPI,PA,_T,N,GY,"
        b"2025,2.2,A\n"
    )

    def handler(request):
        assert "DEU.A.N.CPI.PA._T.N.GY" in str(request.url)
        return httpx.Response(
            200,
            content=payload,
            headers={"content-type": "application/vnd.sdmx.data+csv"},
            request=request,
        )

    source = _source(
        id="oecd_sdmx",
        base_url="https://sdmx.oecd.org/public/rest/",
        allowed_hosts=["sdmx.oecd.org"],
        max_bytes=10000,
        content_types=["application/vnd.sdmx.data+csv"],
    )
    fetcher = HttpSnapshotFetcher(
        SourceRegistry([source]),
        SnapshotWriter(LocalObjectStore(tmp_path)),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    batch = OecdAdapter(fetcher).fetch_annual_cpi({"deu": "DEU"}, 2023)
    observation = batch.observations[0]
    assert observation.jurisdiction_id == "deu"
    assert observation.value == 2.2
    assert observation.observed_at == datetime(2025, 12, 31, tzinfo=UTC)
    assert observation.available_at == batch.snapshots[0].retrieved_at
    assert observation.dimensions["vintage_limit"] == "retrieval-time-only"


def test_RetiredEvent_inventory_and_security_aggregation():
    inventory = b"123 abc https://news.google.com/rss/a.export.CSV.zip\n"
    files = parse_last_update(inventory)
    assert files[0].table == "events"
    assert files[0].byte_count == 123

    row = [""] * 61
    row[29] = "4"
    row[30] = "-7.0"
    row[31] = "12"
    row[34] = "-3.5"
    row[53] = "TU"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("events.export.CSV", "\t".join(row) + "\n")
    aggregate = aggregate_security_events(stream.getvalue())[0]
    assert aggregate.country_code == "TU"
    assert aggregate.conflict_event_count == 1
    assert aggregate.mention_count == 12


def test_vdem_extracts_only_current_democracies(monkeypatch):
    frame = pd.DataFrame(
        [
            {"year": 2024, "country_text_id": "OLD", "country_name": "Old", "v2x_regime": 3},
            {"year": 2025, "country_text_id": "LIB", "country_name": "Liberal", "v2x_regime": 3},
            {"year": 2025, "country_text_id": "ELE", "country_name": "Electoral", "v2x_regime": 2},
            {"year": 2025, "country_text_id": "AUT", "country_name": "Autocracy", "v2x_regime": 1},
        ]
    )
    monkeypatch.setattr(
        "elexion_pipeline.adapters.vdem.pyreadr.read_r", lambda path: {"vdem": frame}
    )
    result = VDemAdapter._extract(b"test-rdata")
    assert [item.country_text_id for item in result] == ["ELE", "LIB"]
    assert {item.regime for item in result} == {"electoral-democracy", "liberal-democracy"}


def test_publication_gate_retains_baseline_without_champion():
    payload = {
        "id": "snapshot-1",
        "election_id": "election-1",
        "as_of": "2026-01-01T00:00:00Z",
        "published_at": "2026-01-01T00:00:00Z",
        "model_version": "v1",
        "model_family": "baseline_ensemble",
        "selection_status": "baseline retained",
        "simulation_count": 1_000_000,
        "seed": 1,
        "data_quality": "D",
        "freshness": "current",
        "missing_drivers": [],
        "regional_forecast_supported": False,
        "input_revision_ids": [],
        "input_provenance": [],
        "outcomes": [
            {"win_probability": 0.6, "projected_share": 0.52},
            {"win_probability": 0.4, "projected_share": 0.48},
        ],
        "coalition_outcomes": [],
        "provenance": [{"url": "https://example.test"}],
    }
    _validate_forecast_payload(payload, {"winner": None})
    payload["model_family"] = "markov_momentum"
    with pytest.raises(ValueError, match="unpromoted challenger"):
        _validate_forecast_payload(payload, {"winner": None})

    comparison = {
        "winner": "markov_momentum",
        "simulation_count_per_model_fold": 10_000,
        "fold_count": 20,
        "held_out_election_count": 5,
        "vintage_verified": True,
        "dataset_sha256": "a" * 64,
    }
    with pytest.raises(ValueError, match="production-grade evidence"):
        _validate_forecast_payload(payload, comparison)
    comparison["simulation_count_per_model_fold"] = 1_000_000
    _validate_forecast_payload(payload, comparison)


def test_publication_gate_rejects_quality_claim_without_exact_input_revisions():
    payload = {
        "id": "snapshot-1",
        "election_id": "election-1",
        "as_of": "2026-01-01T00:00:00Z",
        "published_at": "2026-01-01T00:00:00Z",
        "model_version": "v1",
        "model_family": "baseline_ensemble",
        "selection_status": "baseline retained",
        "simulation_count": 1_000_000,
        "seed": 1,
        "data_quality": "C",
        "freshness": "current",
        "missing_drivers": [],
        "regional_forecast_supported": False,
        "input_revision_ids": [],
        "input_provenance": [],
        "outcomes": [{"win_probability": 1, "projected_share": 1}],
        "coalition_outcomes": [],
        "provenance": [{"url": "https://example.test"}],
    }
    with pytest.raises(ValueError, match="Quality A-C"):
        _validate_forecast_payload(payload, {"winner": None})


def test_publication_gate_requires_canonical_feature_revision_subset():
    revision_id = "00000000-0000-0000-0000-000000000001"
    payload = {
        "id": "snapshot-1",
        "election_id": "election-1",
        "as_of": "2026-01-01T00:00:00Z",
        "published_at": "2026-01-01T00:00:00Z",
        "model_version": "v1",
        "model_family": "baseline_ensemble",
        "selection_status": "baseline retained",
        "simulation_count": 1_000_000,
        "seed": 1,
        "data_quality": "C",
        "freshness": "current",
        "missing_drivers": [],
        "regional_forecast_supported": False,
        "input_revision_ids": ["00000000-0000-0000-0000-000000000002"],
        "input_provenance": [{"source_id": "polls"}],
        "outcomes": [{"win_probability": 1, "projected_share": 1}],
        "coalition_outcomes": [],
        "provenance": [{"url": "https://example.test"}],
    }
    evidence = {
        "source_revision_ids": [revision_id],
        "values": {
            "missing_features": [],
            "provenance": [{"source_id": "official-statistics"}],
        },
    }
    with pytest.raises(ValueError, match="omits canonical source-vintage"):
        _validate_forecast_payload(payload, {"winner": None}, evidence)
    payload["input_revision_ids"].append(revision_id)
    payload["input_provenance"].append({"source_id": "official-statistics"})
    _validate_forecast_payload(payload, {"winner": None}, evidence)


def test_publication_fails_closed_without_durable_database_record():
    assert _publication_is_durable({"status": "persisted"}) is True
    assert _publication_is_durable({"status": "disabled"}) is False
    assert _publication_is_durable({}) is False


@pytest.mark.parametrize(
    ("format_name", "content", "content_type"),
    [
        (
            "json",
            b'{"elections":[{"id":"x-1","name":"National vote","date":"2027-05-02","status":"scheduled"}]}',
            "application/json",
        ),
        (
            "csv",
            b"id,name,date,status\nx-1,National vote,2027-05-02,scheduled\n",
            "text/csv",
        ),
        (
            "ics",
            b"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x-1\nSUMMARY:National vote\nDTSTART;VALUE=DATE:20270502\nSTATUS:CONFIRMED\nEND:VEVENT\nEND:VCALENDAR\n",
            "text/calendar",
        ),
        (
            "html",
            b"<table><tr><th>id</th><th>name</th><th>date</th><th>status</th></tr><tr><td>x-1</td><td>National vote</td><td>2027-05-02</td><td>scheduled</td></tr></table>",
            "text/html",
        ),
    ],
)
def test_official_calendar_contract_parsers(format_name, content, content_type):
    records, confidence = parse_calendar(
        content,
        _snapshot(content_type),
        CalendarParserConfig(
            format=format_name,
            parser_version="fixture-v1",
            jurisdiction_id="x",
        ),
    )
    assert confidence == 1
    assert records[0].election_id == "x-1"
    assert records[0].election_date.isoformat() == "2027-05-02"
    assert records[0].source_snapshot_sha256 == "a" * 64


def test_official_adapter_uses_last_known_good_on_parser_drift(tmp_path):
    responses = iter(
        [
            b'{"elections":[{"id":"x-1","name":"Vote","date":"2027-05-02","status":"scheduled"}]}',
            b'{"unexpected":true}',
        ]
    )

    def handler(request):
        return httpx.Response(
            200,
            content=next(responses),
            headers={"content-type": "application/json"},
            request=request,
        )

    fetcher = HttpSnapshotFetcher(
        SourceRegistry([_source(max_bytes=10000)]),
        SnapshotWriter(LocalObjectStore(tmp_path)),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    checkpoints = MemoryCheckpointStore()
    adapter = OfficialElectionAdapter(fetcher, checkpoints)
    config = CalendarParserConfig(format="json", parser_version="fixture-v1", jurisdiction_id="x")
    assert adapter.fetch_calendar("test", "calendar", config)[0].fallback_used is False
    fallback = OfficialElectionAdapter(fetcher, checkpoints).fetch_calendar(
        "test", "calendar", config
    )[0]
    assert fallback.fallback_used is True
    assert "No election records" in fallback.freshness_warning
    assert [event.status for event in checkpoints.events] == ["success", "failure"]
    assert checkpoints.events[-1].failure_kind == "parser_drift"


def test_pdf_parser_requires_named_groups(monkeypatch):
    class Page:
        def extract_text(self):
            return "x-1 | National vote | 2027-05-02 | scheduled"

    class Reader:
        def __init__(self):
            self.pages = [Page()]

    monkeypatch.setattr("elexion_pipeline.adapters.official.PdfReader", lambda _: Reader())
    records, confidence = parse_calendar(
        b"pdf-fixture",
        _snapshot("application/pdf"),
        CalendarParserConfig(
            format="pdf",
            parser_version="fixture-v1",
            jurisdiction_id="x",
            pdf_row_pattern=(
                r"(?P<id>[^|]+) \| (?P<name>[^|]+) \| (?P<date>\d{4}-\d{2}-\d{2}) "
                r"\| (?P<status>[^\n]+)"
            ),
        ),
    )
    assert confidence == 1
    assert records[0].name == "National vote"


def test_geoboundaries_adapter_validates_downloaded_geometry(tmp_path):
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"shapeName": "Region"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                },
            }
        ],
    }

    def handler(request):
        if request.url.path.endswith("/TST/ADM1/"):
            payload = {
                "boundaryType": "ADM1",
                "gjDownloadURL": "https://raw.githubusercontent.com/test/layer.geojson",
            }
        else:
            payload = geojson
        return httpx.Response(
            200,
            json=payload,
            headers={"content-type": "application/json"},
            request=request,
        )

    source = _source(
        id="geoboundaries",
        base_url="https://www.geoboundaries.org/api/current/gbOpen/",
        allowed_hosts=["www.geoboundaries.org", "raw.githubusercontent.com"],
        max_bytes=10000,
    )
    fetcher = HttpSnapshotFetcher(
        SourceRegistry([source]),
        SnapshotWriter(LocalObjectStore(tmp_path)),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    layer = GeoBoundariesAdapter(fetcher).fetch("TST", 1)
    assert layer.feature_count == 1
    assert layer.level == "ADM1"
    assert layer.source_snapshot.sha256 != layer.metadata_snapshot.sha256

    invalid = {"type": "FeatureCollection", "features": []}
    with pytest.raises(ValueError, match="no features"):
        validate_geojson(invalid)


def test_live_results_fail_to_last_known_good_on_non_monotonic_totals(tmp_path):
    responses = iter(
        [
            b'{"results":[{"reporting_unit_id":"u1","contestant_id":"a","votes":100,"reporting_fraction":0.5,"reported_at":"2028-11-07T22:00:00Z"}]}',
            b'{"results":[{"reporting_unit_id":"u1","contestant_id":"a","votes":90,"reporting_fraction":0.6,"reported_at":"2028-11-07T22:01:00Z"}]}',
        ]
    )

    def handler(request):
        return httpx.Response(
            200,
            content=next(responses),
            headers={"content-type": "application/json"},
            request=request,
        )

    fetcher = HttpSnapshotFetcher(
        SourceRegistry([_source(max_bytes=10000)]),
        SnapshotWriter(LocalObjectStore(tmp_path)),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    checkpoints = MemoryCheckpointStore()
    adapter = OfficialResultAdapter(fetcher, checkpoints)
    config = ResultParserConfig(
        format="json", parser_version="fixture-v1", election_id="x-election"
    )
    first = adapter.fetch_results("test", "results", config)
    assert first.fallback_used is False
    fallback = OfficialResultAdapter(fetcher, checkpoints).fetch_results("test", "results", config)
    assert fallback.fallback_used is True
    assert fallback.records[0].votes == 100
    assert "decreased" in fallback.freshness_warning
    assert [event.status for event in checkpoints.events] == ["success", "failure"]
    assert checkpoints.events[-1].failure_kind == "source_drift"


def test_live_results_use_last_known_good_on_source_outage(tmp_path):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise httpx.ConnectError("authority unavailable", request=request)
        return httpx.Response(
            200,
            content=b'{"results":[{"reporting_unit_id":"u1","contestant_id":"a","votes":100,"reporting_fraction":0.5,"reported_at":"2028-11-07T22:00:00Z"}]}',
            headers={"content-type": "application/json"},
            request=request,
        )

    fetcher = HttpSnapshotFetcher(
        SourceRegistry([_source(max_bytes=10000)]),
        SnapshotWriter(LocalObjectStore(tmp_path)),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    checkpoints = MemoryCheckpointStore()
    config = ResultParserConfig(
        format="json", parser_version="fixture-v1", election_id="x-election"
    )
    OfficialResultAdapter(fetcher, checkpoints).fetch_results("test", "results", config)
    fallback = OfficialResultAdapter(fetcher, checkpoints).fetch_results("test", "results", config)
    assert fallback.fallback_used is True
    assert fallback.records[0].votes == 100
    assert checkpoints.events[-1].failure_kind == "source_unavailable"
