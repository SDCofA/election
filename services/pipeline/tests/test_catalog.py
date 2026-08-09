from types import SimpleNamespace

from elexion_pipeline.adapters.world_bank import WorldBankCountry
from elexion_pipeline.catalog import build_api_catalog


def test_catalog_lists_ineligible_countries_without_enabling_forecasts():
    snapshot = SimpleNamespace(sha256="vdem-sha", license_id="CC-BY-4.0")
    eligible = SimpleNamespace(
        country_text_id="USA",
        name="United States of America",
        regime="liberal-democracy",
        year=2025,
    )
    vdem = SimpleNamespace(version=16, snapshot=snapshot, jurisdictions=(eligible,))
    countries = (
        WorldBankCountry("USA", "US", "United States", "North America"),
        WorldBankCountry("TUR", "TR", "Turkiye", "Europe & Central Asia"),
    )

    payload = build_api_catalog(vdem, "world-bank-sha", countries)
    rows = {item["iso3"]: item for item in payload["jurisdictions"]}

    assert rows["USA"]["eligibility"] == "v-dem:liberal-democracy"
    assert rows["TUR"]["name"] == "Türkiye"
    assert rows["TUR"]["eligibility"].startswith("catalog-only:")
    assert rows["TUR"]["forecast_enabled"] is False
