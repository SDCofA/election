from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

POLL_COMMIT = "749840062b6fdb38652e09bfb90791283e2afa76"
POLL_URL = (
    "https://raw.githubusercontent.com/fivethirtyeight/data/"
    f"{POLL_COMMIT}/pollster-ratings/raw-polls.csv"
)
POLL_SHA256 = "f637423f4b17ad7f4506c5fc3884056e6b32fcbc97e67291c4b078cd6a2d5283"
POLL_LICENSE = "CC-BY-4.0"
POLL_LICENSE_URL = "https://github.com/fivethirtyeight/data/blob/master/LICENSE"
FEC_LICENSE = "US-GOVERNMENT-WORK-17-USC-105"
FEC_LICENSE_URL = (
    "https://uscode.house.gov/view.xhtml?req=(title:17%20section:105%20edition:prelim)"
)
RETRIEVED_AT = "2026-08-09"
HORIZONS = (14, 10, 6, 2)

ELECTIONS = {
    1996: {
        "date": "1996-11-05",
        "dem": 47_402_357,
        "rep": 39_198_755,
        "other": 9_676_522,
        "available": "1997-10-01",
        "url": (
            "https://www.fec.gov/resources/cms-content/documents/"
            "FederalElections96_1996ElectoralandPopularVoteSummary.pdf"
        ),
    },
    2000: {
        "date": "2000-11-07",
        "dem": 50_992_335,
        "rep": 50_455_156,
        "other": 3_949_150,
        "available": "2001-08-16",
        "url": "https://www.fec.gov/documents/1556/federalelections00.pdf",
    },
    2004: {
        "date": "2004-11-02",
        "dem": 59_028_444,
        "rep": 62_040_610,
        "other": 1_226_291,
        "available": "2005-09-01",
        "url": "https://www.fec.gov/resources/cms-content/documents/federalelections2004.pdf",
    },
    2008: {
        "date": "2008-11-04",
        "dem": 69_498_516,
        "rep": 59_948_323,
        "other": 1_866_981,
        "available": "2009-08-06",
        "url": "https://www.fec.gov/resources/cms-content/documents/federalelections2008.pdf",
    },
    2012: {
        "date": "2012-11-06",
        "dem": 65_915_795,
        "rep": 60_933_504,
        "other": 2_236_111,
        "available": "2013-08-21",
        "url": "https://www.fec.gov/documents/1694/tables2012.pdf",
    },
    2016: {
        "date": "2016-11-08",
        "dem": 65_853_514,
        "rep": 62_984_828,
        "other": 7_830_934,
        "available": "2018-01-09",
        "url": "https://www.fec.gov/resources/cms-content/documents/federalelections2016.pdf",
    },
    2020: {
        "date": "2020-11-03",
        "dem": 81_283_501,
        "rep": 74_223_975,
        "other": 2_922_155,
        "available": "2023-10-13",
        "url": "https://www.fec.gov/resources/cms-content/documents/federalelections2020.pdf",
    },
}


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def normalized_result(year: int) -> list[float]:
    item = ELECTIONS[year]
    votes = [int(item["dem"]), int(item["rep"]), int(item["other"])]
    total = sum(votes)
    return [value / total for value in votes]


def fetch_poll_rows() -> list[dict[str, str]]:
    request = Request(POLL_URL, headers={"User-Agent": "ElexionForecast/1.0"})
    with urlopen(request, timeout=45) as response:
        raw = response.read()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != POLL_SHA256:
        raise RuntimeError(f"Pinned poll source digest changed: {digest}")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    return [
        row
        for row in reader
        if row["type_simple"] == "Pres-G"
        and row["location"] == "US"
        and int(row["year"]) in range(2000, 2021, 4)
    ]


def poll_vector(row: dict[str, str]) -> list[float]:
    shares = {"DEM": 0.0, "REP": 0.0}
    for index in (1, 2):
        party = row[f"cand{index}_party"]
        if party in shares:
            shares[party] += float(row[f"cand{index}_pct"] or 0)
    values = [shares["DEM"], shares["REP"], float(row["cand3_pct"] or 0)]
    total = sum(values)
    if total <= 0:
        raise ValueError(f"Poll {row['poll_id']} has no usable vote shares")
    return [value / total for value in values]


def poll_date(row: dict[str, str]) -> date:
    month, day, year = (int(value) for value in row["polldate"].split("/"))
    return date(year, month, day)


def aggregate_snapshot(
    rows: list[dict[str, str]], year: int, snapshot_date: date
) -> tuple[list[float], list[dict[str, object]]]:
    window_start = snapshot_date - timedelta(days=3)
    selected = [
        row
        for row in rows
        if int(row["year"]) == year and window_start <= poll_date(row) <= snapshot_date
    ]
    if not selected:
        raise ValueError(f"No {year} polls in {window_start}..{snapshot_date}")
    vectors = [poll_vector(row) for row in selected]
    average = [sum(vector[index] for vector in vectors) / len(vectors) for index in range(3)]
    total = sum(average)
    aggregate = [value / total for value in average]
    evidence = [
        {
            "poll_id": row["poll_id"],
            "question_id": row["question_id"],
            "pollster": row["pollster"],
            "polldate": row["polldate"],
            "samplesize": row["samplesize"],
            "methodology": row["methodology"],
            "partisan": row["partisan"],
            "dem_rep_other": poll_vector(row),
        }
        for row in sorted(selected, key=lambda item: (item["polldate"], item["poll_id"]))
    ]
    return aggregate, evidence


def write_snapshot(root: Path, relative_path: str, payload: object) -> str:
    raw = canonical_bytes(payload)
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def revision(
    revision_id: str,
    role: str,
    source_url: str,
    license_id: str,
    license_url: str,
    authority: str,
    observed_at: str,
    available_at: str,
    digest: str,
    raw_path: str,
) -> dict[str, str]:
    return {
        "id": revision_id,
        "source_url": source_url,
        "license": license_id,
        "license_url": license_url,
        "authority": authority,
        "role": role,
        "observed_at": observed_at,
        "released_at": available_at,
        "available_at": available_at,
        "retrieved_at": RETRIEVED_AT,
        "sha256": digest,
        "raw_path": raw_path,
    }


def build() -> Path:
    backtest_root = Path(__file__).resolve().parents[1] / "app" / "backtests"
    rows = fetch_poll_rows()
    revisions: list[dict[str, str]] = []
    records: list[dict[str, object]] = []

    result_revision_ids: dict[int, str] = {}
    fundamentals_revision_ids: dict[int, str] = {}
    for year, item in ELECTIONS.items():
        result_payload = {
            "election_year": year,
            "vote_order": ["DEM", "REP", "OTHER"],
            "votes": [item["dem"], item["rep"], item["other"]],
            "total": int(item["dem"]) + int(item["rep"]) + int(item["other"]),
            "source_url": item["url"],
        }
        if year >= 2000:
            result_id = f"fec-us-president-{year}-result"
            result_path = f"raw/us-presidential/{result_id}.json"
            digest = write_snapshot(backtest_root, result_path, result_payload)
            revisions.append(
                revision(
                    result_id,
                    "result",
                    str(item["url"]),
                    FEC_LICENSE,
                    FEC_LICENSE_URL,
                    "official",
                    str(item["date"]),
                    str(item["available"]),
                    digest,
                    result_path,
                )
            )
            result_revision_ids[year] = result_id

        if year <= 2016:
            fundamentals_id = f"fec-us-president-{year}-fundamentals"
            fundamentals_path = f"raw/us-presidential/{fundamentals_id}.json"
            fundamentals_payload = {
                **result_payload,
                "usage": f"previous-election fundamentals for {year + 4}",
            }
            digest = write_snapshot(backtest_root, fundamentals_path, fundamentals_payload)
            revisions.append(
                revision(
                    fundamentals_id,
                    "fundamentals",
                    str(item["url"]),
                    FEC_LICENSE,
                    FEC_LICENSE_URL,
                    "official",
                    str(item["date"]),
                    str(item["available"]),
                    digest,
                    fundamentals_path,
                )
            )
            fundamentals_revision_ids[year] = fundamentals_id

    for year in range(2000, 2021, 4):
        election_day = date.fromisoformat(str(ELECTIONS[year]["date"]))
        for horizon in HORIZONS:
            forecast_as_of = election_day - timedelta(days=horizon)
            snapshot_dates = (forecast_as_of - timedelta(days=3), forecast_as_of)
            snapshots: list[list[float]] = []
            poll_revision_ids: list[str] = []
            for snapshot_date in snapshot_dates:
                aggregate, evidence = aggregate_snapshot(rows, year, snapshot_date)
                revision_id = f"538-us-president-{year}-{snapshot_date.isoformat()}"
                raw_path = f"raw/us-presidential/{revision_id}.json"
                digest = write_snapshot(
                    backtest_root,
                    raw_path,
                    {
                        "source_commit": POLL_COMMIT,
                        "source_sha256": POLL_SHA256,
                        "filters": {
                            "type_simple": "Pres-G",
                            "location": "US",
                            "window_start": (snapshot_date - timedelta(days=3)).isoformat(),
                            "window_end": snapshot_date.isoformat(),
                        },
                        "polls": evidence,
                        "aggregate_dem_rep_other": aggregate,
                    },
                )
                revisions.append(
                    revision(
                        revision_id,
                        "poll",
                        POLL_URL,
                        POLL_LICENSE,
                        POLL_LICENSE_URL,
                        "poll_aggregator",
                        min(poll_date(item) for item in evidence).isoformat(),
                        snapshot_date.isoformat(),
                        digest,
                        raw_path,
                    )
                )
                snapshots.append(aggregate)
                poll_revision_ids.append(revision_id)

            prior = year - 4
            records.append(
                {
                    "election_id": f"us-president-{year}",
                    "election_date": election_day.isoformat(),
                    "actual_shares": normalized_result(year),
                    "fundamentals_shares": normalized_result(prior),
                    "polling_snapshots": snapshots,
                    "forecast_as_of": forecast_as_of.isoformat(),
                    "fundamentals_available_at": ELECTIONS[prior]["available"],
                    "polling_snapshot_dates": [item.isoformat() for item in snapshot_dates],
                    "result_available_at": ELECTIONS[year]["available"],
                    "fundamentals_revision_id": fundamentals_revision_ids[prior],
                    "polling_revision_ids": poll_revision_ids,
                    "result_revision_id": result_revision_ids[year],
                }
            )

    payload = {
        "schema_version": 3,
        "description": (
            "Strict U.S. presidential national-popular-vote walk-forward benchmark using "
            "pinned FiveThirtyEight poll records and FEC official results."
        ),
        "minimum_train_elections": 3,
        "source_revisions": revisions,
        "records": records,
    }
    output = backtest_root / "us-presidential-2000-2020-v3.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_bytes(payload))
    return output


if __name__ == "__main__":
    print(build())
