from __future__ import annotations

from datetime import UTC, datetime

from .adapters.vdem import VDemCatalog
from .adapters.world_bank import WorldBankCountry


def build_api_catalog(
    vdem: VDemCatalog,
    world_bank_snapshot_sha256: str,
    countries: tuple[WorldBankCountry, ...],
) -> dict:
    metadata = {country.iso3: country for country in countries}
    eligible = {item.country_text_id: item for item in vdem.jurisdictions}
    country_names = {"PSE": "State of Palestine", "TUR": "Türkiye"}
    jurisdictions = []
    for iso3 in sorted(metadata.keys() | eligible.keys()):
        country = metadata.get(iso3)
        item = eligible.get(iso3)
        jurisdictions.append(
            {
                "id": iso3.lower(),
                "name": country_names.get(
                    iso3, country.name if country else item.name
                ),
                "iso3": iso3,
                "region": country.region if country else "Global",
                "eligibility": (
                    f"v-dem:{item.regime}"
                    if item
                    else "catalog-only:outside-v-dem-forecast-rule"
                ),
                "is_exception": False,
                "forecast_enabled": False,
                "coverage_status": "mechanics_blocked",
                "blocking_reasons": [
                    "No sourced national calendar and validated electoral-system pack are onboarded"
                    if item
                    else "Jurisdiction is listed globally but is outside the current V-Dem forecast-eligibility rule"
                ],
                "flag": country.iso2 if country else iso3[:2],
            }
        )

    return {
        "schema_version": 2,
        "generated_at": datetime.now(UTC).isoformat(),
        "eligibility": {
            "source": "V-Dem Country-Year Dataset",
            "version": vdem.version,
            "year": vdem.jurisdictions[0].year if vdem.jurisdictions else None,
            "rule": "v2x_regime in {2,3}",
            "snapshot_sha256": vdem.snapshot.sha256,
            "license": vdem.snapshot.license_id,
        },
        "enrichment": {
            "source": "World Bank country catalog",
            "snapshot_sha256": world_bank_snapshot_sha256,
        },
        "jurisdictions": sorted(jurisdictions, key=lambda item: item["name"]),
    }
