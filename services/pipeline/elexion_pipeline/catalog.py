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
    jurisdictions = []
    for item in vdem.jurisdictions:
        country = metadata.get(item.country_text_id)
        jurisdictions.append(
            {
                "id": item.country_text_id.lower(),
                "name": item.name,
                "iso3": item.country_text_id,
                "region": country.region if country else "Global",
                "eligibility": f"v-dem:{item.regime}",
                "is_exception": False,
                "forecast_enabled": False,
                "coverage_status": "mechanics_blocked",
                "blocking_reasons": [
                    "No sourced national calendar and validated electoral-system pack are onboarded"
                ],
                "flag": country.iso2 if country else item.country_text_id[:2],
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
