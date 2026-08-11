import time

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from app.repository import CatalogRepository, get_repository

client = TestClient(app)


def test_health_and_catalog():
    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["dependencies"]["telemetry"] == "disabled"
    jurisdictions = client.get("/v1/jurisdictions").json()
    assert len(jurisdictions) == 19
    assert {item["id"] for item in jurisdictions} == {
        "arg",
        "aus",
        "bra",
        "can",
        "chn",
        "deu",
        "fra",
        "gbr",
        "idn",
        "ind",
        "ita",
        "jpn",
        "kor",
        "mex",
        "rus",
        "sau",
        "tur",
        "usa",
        "zaf",
    }
    united_states = next(item for item in jurisdictions if item["id"] == "usa")
    assert united_states["eligibility"] == "v-dem:electoral-democracy"

    status = client.get("/v1/catalog/status").json()
    assert status["eligibility_version"] == 16
    assert status["eligibility_year"] == 2025
    assert status["eligible_jurisdictions"] == 12
    assert status["total_jurisdictions"] == 19
    assert status["eligibility_snapshot_sha256"]
    assert status["forecast_ready"] == 13
    assert status["calendar_only"] == 0
    assert status["mechanics_blocked"] == 6
    assert status["sourced_calendars"] == 13
    turkiye = next(item for item in jurisdictions if item["id"] == "tur")
    assert turkiye["name"] == "Türkiye"
    assert turkiye["flag"] == "TR"
    assert turkiye["forecast_enabled"] is True
    brazil = next(item for item in jurisdictions if item["id"] == "bra")
    assert brazil["coverage_status"] == "forecast"
    argentina = next(item for item in jurisdictions if item["id"] == "arg")
    assert argentina["coverage_status"] == "forecast"
    assert argentina["blocking_reasons"] == []
    china = next(item for item in jurisdictions if item["id"] == "chn")
    assert china["coverage_status"] == "mechanics_blocked"


def test_every_public_election_has_a_catalog_jurisdiction_and_source():
    jurisdictions = client.get("/v1/jurisdictions").json()
    elections = client.get("/v1/elections").json()
    assert len(jurisdictions) == 19
    assert len(elections) == 13
    assert {item["jurisdiction_id"] for item in elections} <= {item["id"] for item in jurisdictions}
    assert all(item["sources"] for item in elections)
    exploratory = [item for item in elections if item["system"] == "unresolved"]
    assert len(exploratory) == 8
    assert all(item["election_date"] is not None for item in exploratory)
    assert all(item["date_confidence"].startswith("three-year") for item in exploratory)
    assert all(item["potential_candidates"] for item in exploratory)
    argentina = client.get("/v1/elections/arg-next-national").json()
    assert argentina["forecast"]["simulation_count"] == 1_000_000
    assert len(argentina["election"]["potential_candidates"]) == 3
    assert argentina["election"]["sources"][0]["authority"] == "official reference"
    mechanics = client.get("/v1/elections/arg-next-national/mechanics").json()
    assert mechanics["rules"]["validation_status"] == "exploratory_proxy"
    assert mechanics["forecast_enabled"] is True

    repository = get_repository()
    assert all(
        repository.detail(election["id"]).forecast.simulation_count == 1_000_000
        for election in elections
    )


def test_public_cache_and_security_headers():
    latest = client.get("/v1/elections/us-2028-president/forecast").json()
    response = client.get(f"/v1/forecast-snapshots/{latest['id']}")
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-request-id"]
    assert int(response.headers["x-ratelimit-remaining"]) >= 0
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "elexion_http_requests_total" in metrics.text
    assert 'route="/v1/forecast-snapshots/{snapshot_id}"' in metrics.text
    assert "elexion_http_request_duration_seconds_bucket" in metrics.text
    assert 'le="0.3"' in metrics.text
    assert 'le="+Inf"' in metrics.text
    assert 'elexion_forecast_age_seconds{election_id="us-2028-president"}' in metrics.text
    assert "elexion_pipeline_telemetry_up 0" in metrics.text


def test_forecast_contract_and_exploratory_forecasts():
    response = client.get("/v1/elections/us-2028-president")
    assert response.status_code == 200
    detail = response.json()
    assert detail["forecast"]["simulation_count"] == 1_000_000
    assert detail["forecast"]["model_family"] == "baseline_ensemble"
    assert detail["forecast"]["data_quality"] == "D"
    assert detail["forecast"]["input_provenance"] == []
    assert detail["forecast"]["provenance"]
    assert detail["forecast"]["regional_forecast_supported"] is False
    assert detail["forecast"]["missing_drivers"]
    brazil = client.get("/v1/elections/br-2026-president")
    assert brazil.status_code == 200
    assert brazil.json()["forecast"]["simulation_count"] == 1_000_000
    assert brazil.json()["election"]["date_confidence"] == "official"
    assert brazil.json()["jurisdiction"]["coverage_status"] == "forecast"
    assert {item["name"] for item in brazil.json()["election"]["potential_candidates"]} >= {
        "Luiz Inácio Lula da Silva",
        "Flávio Bolsonaro",
    }
    brazil_mechanics = client.get("/v1/elections/br-2026-president/mechanics").json()
    assert brazil_mechanics["rules"]["second_round_date"] == "2026-10-25"
    assert brazil_mechanics["source_adapters"][0]["status"] == "approved"

    turkiye = client.get("/v1/elections/tr-next-president")
    assert turkiye.status_code == 200
    assert turkiye.json()["forecast"]["simulation_count"] == 1_000_000
    assert {item["name"] for item in turkiye.json()["election"]["potential_candidates"]} >= {
        "Recep Tayyip Erdoğan",
        "Mansur Yavaş",
        "Özgür Özel",
    }

    comparison = client.get("/v1/elections/tr-next-president/model-comparison").json()
    assert comparison["fold_count"] == 0
    assert comparison["winner"] is None
    assert comparison["status"] == "insufficient_historical_vintages"


def test_unknown_election_is_404():
    assert client.get("/v1/elections/not-real").status_code == 404


def test_internal_candidate_boundary_is_fail_closed(monkeypatch):
    endpoint = "/v1/internal/elections/us-2028-president/forecast-candidate"
    monkeypatch.setattr(main_module, "INTERNAL_TOKEN", None)
    assert client.get(endpoint, params={"model_family": "baseline_ensemble"}).status_code == 503

    monkeypatch.setattr(main_module, "INTERNAL_TOKEN", "fixture-secret")
    assert client.get(endpoint, params={"model_family": "baseline_ensemble"}).status_code == 403
    monkeypatch.setattr(
        CatalogRepository,
        "candidate",
        lambda self, election_id, model_family: self.forecasts[election_id],
    )
    response = client.get(
        endpoint,
        params={"model_family": "baseline_ensemble"},
        headers={"X-Elexion-Internal-Token": "fixture-secret"},
    )
    assert response.status_code == 200
    assert response.json()["simulation_count"] == 1_000_000


def test_model_comparison_reports_short_horizon_leader_without_promoting_it():
    comparison = client.get("/v1/elections/us-2028-president/model-comparison").json()
    assert comparison["winner"] is None
    assert comparison["status"] == "insufficient_evidence"
    assert comparison["historical_leader"] == "markov_momentum"
    assert comparison["leakage_check"] is True
    assert comparison["fold_count"] == 12
    assert comparison["held_out_election_count"] == 3
    assert comparison["simulation_count_per_model_fold"] == 1_000_000
    assert comparison["evaluated_horizon_min_days"] == 2
    assert comparison["evaluated_horizon_max_days"] == 14
    assert comparison["target_horizon_days"] == 821
    assert "outside the evaluated" in comparison["message"]
    assert len(comparison["dataset_sha256"]) == 64
    assert comparison["provenance"]


def test_gaussian_and_markov_are_distinct_million_run_challengers():
    base = "/v1/elections/us-2028-president/forecast/alternatives"
    gaussian = client.get(f"{base}/gaussian_monte_carlo").json()
    markov = client.get(f"{base}/markov_momentum").json()
    assert gaussian["simulation_count"] == markov["simulation_count"] == 1_000_000
    assert gaussian["id"] != markov["id"]
    assert gaussian["seed"] != markov["seed"]
    assert gaussian["outcomes"] != markov["outcomes"]
    assert client.get(f"{base}/markov_momentum").json() == markov


def test_immutable_snapshot_and_public_contract_surfaces():
    election_id = "us-2028-president"
    latest = client.get(f"/v1/elections/{election_id}/forecast").json()
    snapshot = client.get(f"/v1/forecast-snapshots/{latest['id']}")
    assert snapshot.status_code == 200
    assert snapshot.json() == latest
    assert client.get(f"/v1/elections/{election_id}/forecasts").json()[0]["id"] == latest["id"]

    simulations = client.get(f"/v1/elections/{election_id}/simulations").json()
    assert simulations["simulation_count"] == 1_000_000
    assert simulations["seed"] == latest["seed"]
    driver_report = client.get(f"/v1/elections/{election_id}/drivers").json()
    assert driver_report["drivers"]
    assert len(driver_report["sensitivity"]) == len(driver_report["drivers"])
    assert all(
        row["negative_incumbent_share_shift"]
        <= row["observed_incumbent_share_shift"]
        <= row["positive_incumbent_share_shift"]
        for row in driver_report["sensitivity"]
    )
    assert client.get(f"/v1/elections/{election_id}/sources").json()["sources"]

    map_layer = client.get(f"/v1/elections/{election_id}/map-layers").json()
    assert map_layer["supported"] is False
    results = client.get(f"/v1/elections/{election_id}/official-results").json()
    assert results["feed_available"] is False
    assert results["status"] == "results feed unavailable"
    assert client.get(f"/v1/elections/{election_id}/coalitions").status_code == 404
    coalitions = client.get("/v1/elections/de-next-bundestag/coalitions").json()
    assert coalitions["coalitions"]
    assert coalitions["majority"] == 316


def test_cached_forecast_p95_is_under_300ms():
    endpoint = "/v1/elections/us-2028-president/forecast"
    assert client.get(endpoint).status_code == 200
    durations = []
    for _ in range(25):
        started = time.perf_counter()
        assert client.get(endpoint).status_code == 200
        durations.append(time.perf_counter() - started)
    p95 = sorted(durations)[int(len(durations) * 0.95) - 1]
    assert p95 < 0.300
