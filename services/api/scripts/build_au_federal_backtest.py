from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

RETRIEVED_AT = "2026-08-11"
LICENSE = "CC-BY-SA-4.0"
LICENSE_URL = "https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use"
USER_AGENT = "SDCofA-Election-Research/0.1 (https://github.com/SDCofA/election)"

# The first revision precedes the earliest forecast origin. Each later revision is the latest
# revision available before the 28-, 14-, and 7-day forecast cutoffs respectively.
POLL_REVISIONS = {
    2010: (
        (374484320, "2010-07-20"),
        (375109966, "2010-07-23"),
        (376717083, "2010-08-02"),
        (378767505, "2010-08-13"),
    ),
    2013: (
        (565513005, "2013-07-23"),
        (567883303, "2013-08-09"),
        (569664282, "2013-08-22"),
        (570800582, "2013-08-30"),
    ),
    2016: (
        (721303567, "2016-05-20"),
        (723493196, "2016-06-03"),
        (725795327, "2016-06-17"),
        (726856383, "2016-06-24"),
    ),
    2019: (
        (891145190, "2019-04-05"),
        (892519389, "2019-04-15"),
        (895309174, "2019-05-03"),
        (896103726, "2019-05-08"),
    ),
    2022: (
        (1081228001, "2022-04-06"),
        (1084044612, "2022-04-22"),
        (1086510163, "2022-05-06"),
        (1087667079, "2022-05-13"),
    ),
    2025: (
        (1281604863, "2025-03-21"),
        (1283877183, "2025-04-04"),
        (1286292521, "2025-04-18"),
        (1287350103, "2025-04-25"),
    ),
}

# National two-party-preferred truth is from the Australian Electoral Commission. The result
# revisions below are immutable contemporaneous pages retained as source-vintage proof.
ELECTIONS = {
    2010: {
        "election_date": "2010-08-21",
        "actual": (0.5012, 0.4988),
        "fundamentals": (0.5270, 0.4730),
        "fundamentals_year": 2007,
    },
    2013: {
        "election_date": "2013-09-07",
        "actual": (0.4651, 0.5349),
        "fundamentals": (0.5012, 0.4988),
        "fundamentals_year": 2010,
    },
    2016: {
        "election_date": "2016-07-02",
        "actual": (0.4964, 0.5036),
        "fundamentals": (0.4651, 0.5349),
        "fundamentals_year": 2013,
    },
    2019: {
        "election_date": "2019-05-18",
        "actual": (0.4847, 0.5153),
        "fundamentals": (0.4964, 0.5036),
        "fundamentals_year": 2016,
    },
    2022: {
        "election_date": "2022-05-21",
        "actual": (0.5213, 0.4787),
        "fundamentals": (0.4847, 0.5153),
        "fundamentals_year": 2019,
    },
    2025: {
        "election_date": "2025-05-03",
        "actual": (0.5522, 0.4478),
        "fundamentals": (0.5213, 0.4787),
        "fundamentals_year": 2022,
    },
}

RESULT_REVISIONS = {
    2007: (176468074, "2007-12-07"),
    2010: (382773376, "2010-09-03"),
    2013: (573694311, "2013-09-19"),
    2016: (729898993, "2016-07-15"),
    2019: (899719697, "2019-05-31"),
    2022: (1091352420, "2022-06-03"),
    2025: (1290689757, "2025-05-16"),
}

PINNED_SHA256 = {
    176468074: "0099b99b8186823669ee93547632e18eba7c2b6d171fa20839cac7f1bc8ee55c",
    374484320: "76db5a98a1b5c4580409eafd6c2bea31c89f8e2b8f74a594549071d8f5d16da5",
    375109966: "9d615621ced4e7513e836c0f234b8e7539415e1d1ac8c856032be0896cd7330d",
    376717083: "6760c1e3fc543d7427fee22d24d643c5e021c206275293ad6640484c0e1ee6a6",
    378767505: "1bb0e6fb146170b617f84cb6bbcfae5048c2ac7ca30f8bc0e6813410c22aba41",
    382773376: "7e39104a226ebcffb556597ffbda1a94489145af15b97218140ebae80be59c74",
    565513005: "cc7d2b02968d5c6ceef8faec271bb64c5e95a27e5877c0f76d79571824d4e23f",
    567883303: "c516199d3614a10491494b110026c5276097d89c175f0bb0ebf81bc1e274d749",
    569664282: "8216bb45a08aabe6f1535eb213a200e58c7be858696bc6bcd6ffe1b663312e92",
    570800582: "8fd2aff081d164aa77fc67d50acf01c65b9d7f297aef9d5b5b7889d81a746c96",
    573694311: "81c634f6c668e63b4d87d890bf038d387f4b3b93da535bac55275da509c6fa97",
    721303567: "765f040d0a31f28450f7af1c370b7f62a606995de3148e4d7cf548e9ee95ec0a",
    723493196: "5c67630a85ce4273ccf6c1e282284202203a2526a2943e66fc3ba6828857252d",
    725795327: "ffb74c58fed98da6c891ebb52b72796d1d579d3ed93bb0eb9840acc01f5eb6c0",
    726856383: "0d9b2cb6b820369a1a42612129e8427a567a711e0938aad0e804550a6f5a987e",
    729898993: "f813ca2240f8b142f4de1f53be9432015ac640dc32abab31363f99cdd1f6ba11",
    891145190: "76885a3a506640ed2e9bccce172ef95a77393b8d370ebcae45864ee6fdbb5b37",
    892519389: "150f0cba9183d07e34c9b8e6d7561d7abe98d6f6ac57727719335a07614a96b0",
    895309174: "71dcd74e536324aec35dea3826c58a905d2a6cc0c0fc1b29984a13fa533cb661",
    896103726: "4e23f649f307c1c4f26a2d70dfdc7dc7857026be5215de64448bb2da1ec00914",
    899719697: "414b03fce0b3a0d0f49627ccba2e7e17d4d933f418fbc9ef7db71be493f36a48",
    1081228001: "df196acf3b7f3f17fa564d54eb7f35d9961ef6c204055ce2ac917fabc22a29d6",
    1084044612: "4b6c655ca339a39726846d6f92c9a2abc31c1f8dc0aa9882d6b0d4394c61fff8",
    1086510163: "8acafb04032c534c025b7a23924707fa9e2e062932ee4b15f663a61995a6f0a4",
    1087667079: "75074efb844033d9a18905999fc257afdf70a022b52b52bb5c8d150d9bfcce16",
    1091352420: "5cbeadfc7526483dec9932648c427688285979e413ea664d08b76fe5350b7473",
    1281604863: "3c3b08badbcfff25dfc4854d32ede78e954bc9db28ef1defdd2b556783adeede",
    1283877183: "41eaaeeee118776c38851bb1aa42aede27b34d72c4569e6d0c880986751bc05f",
    1286292521: "334f7092e3e5aa7fb885e1af1236fb8bdb4ea72833b7da52e9182e87b78572c9",
    1287350103: "0970a952d2c3312fe60d8f86cd88da0d8e4fe801061a91e809f1041a9fd1a243",
    1290689757: "cca78d00c1abf82db0dcee3a2cd5fb07a55bd49aaf1cc0d38e26ba3aa103bffa",
}

EXPECTED_POLL_VECTORS = {
    2010: ((0.522, 0.478), (0.522, 0.478), (0.524, 0.476), (0.524, 0.476)),
    2013: ((0.497, 0.503), (0.493, 0.507), (0.484, 0.516), (0.475, 0.525)),
    2016: ((0.505, 0.495), (0.506, 0.494), (0.488, 0.512), (0.488, 0.512)),
    2019: ((0.528, 0.472), (0.523, 0.477), (0.514, 0.486), (0.514, 0.486)),
    2022: ((0.561, 0.439), (0.550, 0.450), (0.549, 0.451), (0.550, 0.450)),
    2025: ((0.489, 0.511), (0.512, 0.488), (0.512, 0.488), (0.512, 0.488)),
}


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _tables(raw: str) -> list[str]:
    tables: list[str] = []
    start: int | None = None
    depth = 0
    offset = 0
    for line in raw.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("{|"):
            if depth == 0:
                start = offset + len(line) - len(stripped)
            depth += 1
        if stripped.startswith("|}") and depth:
            depth -= 1
            if depth == 0 and start is not None:
                tables.append(raw[start : offset + len(line)])
                start = None
        offset += len(line)
    return tables


def _row_cells(block: str) -> list[str]:
    cells: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("!"):
            cells.extend(part.strip() for part in stripped[1:].split("!!"))
        elif stripped.startswith("|") and not stripped.startswith(("|-", "|}")):
            cells.extend(part.strip() for part in stripped[1:].split("||"))
    return cells


def _cell_number(cell: str) -> float | None:
    value = cell.rsplit("|", 1)[-1]
    value = re.sub(r"<!--.*?-->|<ref\b.*?</ref>|<ref\b[^>]*/>", "", value, flags=re.DOTALL)
    percentages = re.findall(r"(?<!\d)(\d{1,2}(?:\.\d+)?)\s*%", value)
    if percentages:
        return float(percentages[0])
    plain = re.sub(r"\{\{.*?\}\}|'{2,}", "", value)
    numbers = re.findall(r"(?<![\d.])(\d{1,2}(?:\.\d+)?)(?![\d.])", plain)
    return float(numbers[0]) if numbers else None


def _party_order(header: str) -> bool:
    labor = list(re.finditer(r"\b(?:ALP|Labor)\b", header, flags=re.IGNORECASE))
    coalition = list(
        re.finditer(
            r"(?:L\s*/\s*NP|Lib\s*/\s*Nat|Coalition|\bCoa\b)",
            header,
            flags=re.IGNORECASE,
        )
    )
    if not labor or not coalition:
        raise ValueError("Polling table does not identify Labor and Coalition TPP columns")
    return labor[-1].start() < coalition[-1].start()


def _table_poll_rows(table: str) -> list[list[float]]:
    data_match = re.search(r"(?m)^!{1,2}.*(?:19|20)\d{2}", table)
    if data_match is None:
        return []
    header = table[: data_match.start()]
    labor_first = _party_order(header)
    tpp_header = next(
        (
            line
            for line in header.splitlines()
            if re.search(r"Two[ -]party[ -]preferred|TPP vote|2pp vote", line, flags=re.IGNORECASE)
        ),
        "",
    )
    colspan = re.search(r"colspan\s*=\s*[\"']?(\d+)", tpp_header, flags=re.IGNORECASE)
    tpp_columns = int(colspan.group(1)) if colspan else 2
    if tpp_columns < 2:
        return []
    rows: list[list[float]] = []
    for block in re.split(r"(?m)^\|-[^\n]*$", table):
        cells = _row_cells(block)
        if len(cells) < tpp_columns + 1:
            continue
        tpp_cells = cells[-tpp_columns:]
        first = _cell_number(tpp_cells[0])
        second = _cell_number(tpp_cells[1])
        if first is None or second is None or not 98 <= first + second <= 102:
            continue
        labor, coalition = (first, second) if labor_first else (second, first)
        if 25 <= labor <= 75 and 25 <= coalition <= 75:
            rows.append([labor, coalition])
    return rows


def poll_vector_from_wikitext(raw: str) -> list[float]:
    candidates: list[list[list[float]]] = []
    for table in _tables(raw):
        if not re.search(
            r"Two[ -]party[ -]preferred|TPP vote|2pp vote", table, flags=re.IGNORECASE
        ):
            continue
        try:
            rows = _table_poll_rows(table)
        except ValueError:
            continue
        if rows:
            candidates.append(rows)
    if not candidates:
        raise ValueError("No complete national two-party-preferred polling table found")
    rows = candidates[0][:5]
    averages = [sum(row[index] for row in rows) / len(rows) for index in range(2)]
    total = sum(averages)
    return [value / total for value in averages]


def raw_url(title: str, oldid: int) -> str:
    return (
        "https://en.wikipedia.org/w/index.php?title="
        f"{quote(title.replace(' ', '_'))}&oldid={oldid}&action=raw"
    )


def source_url(oldid: int) -> str:
    return f"https://en.wikipedia.org/w/index.php?oldid={oldid}"


def fetch_revision(title: str, oldid: int) -> bytes:
    request = Request(raw_url(title, oldid), headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=45) as response:
        raw = response.read()
    if len(raw) < 1_000:
        raise RuntimeError(f"Wikipedia oldid {oldid} returned only {len(raw)} bytes")
    digest = hashlib.sha256(raw).hexdigest()
    expected = PINNED_SHA256.get(oldid)
    if expected is not None and digest != expected:
        raise RuntimeError(f"Pinned Wikipedia oldid {oldid} digest changed: {digest}")
    return raw


def write_raw(root: Path, title: str, oldid: int) -> tuple[str, str]:
    raw = fetch_revision(title, oldid)
    relative_path = f"raw/au/wikipedia-oldid-{oldid}.wikitext"
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return relative_path, hashlib.sha256(raw).hexdigest()


def revision(
    revision_id: str,
    role: str,
    oldid: int,
    available_at: str,
    digest: str,
    raw_path: str,
) -> dict[str, str]:
    return {
        "id": revision_id,
        "source_url": source_url(oldid),
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "authority": "Wikipedia immutable revision; TPP truth cross-checked against AEC",
        "role": role,
        "observed_at": available_at,
        "released_at": available_at,
        "available_at": available_at,
        "retrieved_at": RETRIEVED_AT,
        "sha256": digest,
        "raw_path": raw_path,
        "vintage_proof": "contemporaneous_archive",
    }


def build() -> tuple[Path, dict[int, str], dict[int, tuple[tuple[float, float], ...]]]:
    root = Path(__file__).resolve().parents[1] / "app" / "backtests"
    revisions: list[dict[str, str]] = []
    records: list[dict[str, object]] = []
    digests: dict[int, str] = {}
    vectors: dict[int, tuple[tuple[float, float], ...]] = {}
    raw_metadata: dict[int, tuple[str, str]] = {}

    def materialize(title: str, oldid: int) -> tuple[str, str]:
        if oldid not in raw_metadata:
            raw_metadata[oldid] = write_raw(root, title, oldid)
            digests[oldid] = raw_metadata[oldid][1]
        return raw_metadata[oldid]

    for year, election in ELECTIONS.items():
        poll_title = f"Opinion polling for the {year} Australian federal election"
        year_vectors: list[tuple[float, float]] = []
        for oldid, available_at in POLL_REVISIONS[year]:
            raw_path, digest = materialize(poll_title, oldid)
            computed = tuple(
                poll_vector_from_wikitext((root / raw_path).read_text(encoding="utf-8"))
            )
            if not math.isclose(sum(computed), 1.0, abs_tol=1e-12):
                raise ValueError(f"{year} poll vector {oldid} is not normalized")
            expected = EXPECTED_POLL_VECTORS.get(year, ())
            if expected and any(
                abs(actual - pinned) > 0.000002
                for actual, pinned in zip(computed, expected[len(year_vectors)], strict=True)
            ):
                raise ValueError(
                    f"{year} archive aggregate {oldid} diverged: {computed} != "
                    f"{expected[len(year_vectors)]}"
                )
            year_vectors.append(computed)
            revisions.append(
                revision(f"au-poll-{oldid}", "poll", oldid, available_at, digest, raw_path)
            )
        vectors[year] = tuple(year_vectors)

        result_oldid, result_available = RESULT_REVISIONS[year]
        result_path, result_digest = materialize(
            f"{year} Australian federal election", result_oldid
        )
        revisions.append(
            revision(
                f"au-result-{year}",
                "result",
                result_oldid,
                result_available,
                result_digest,
                result_path,
            )
        )

        fundamentals_year = int(election["fundamentals_year"])
        fundamentals_oldid, fundamentals_available = RESULT_REVISIONS[fundamentals_year]
        fundamentals_path, fundamentals_digest = materialize(
            f"{fundamentals_year} Australian federal election", fundamentals_oldid
        )
        revisions.append(
            revision(
                f"au-fundamentals-{year}",
                "fundamentals",
                fundamentals_oldid,
                fundamentals_available,
                fundamentals_digest,
                fundamentals_path,
            )
        )

        election_day = date.fromisoformat(str(election["election_date"]))
        for index, horizon_days in enumerate((28, 14, 7), start=1):
            selected_revisions = POLL_REVISIONS[year][: index + 1]
            selected_vectors = year_vectors[: index + 1]
            forecast_as_of = election_day - timedelta(days=horizon_days)
            if date.fromisoformat(selected_revisions[-1][1]) > forecast_as_of:
                raise ValueError(f"{year} poll revision exceeds the {horizon_days}-day cutoff")
            records.append(
                {
                    "election_id": f"au-house-tpp-{year}",
                    "election_date": election_day.isoformat(),
                    "actual_shares": election["actual"],
                    "fundamentals_shares": election["fundamentals"],
                    "polling_snapshots": selected_vectors,
                    "forecast_as_of": forecast_as_of.isoformat(),
                    "fundamentals_available_at": fundamentals_available,
                    "polling_snapshot_dates": [item[1] for item in selected_revisions],
                    "result_available_at": result_available,
                    "fundamentals_revision_id": f"au-fundamentals-{year}",
                    "polling_revision_ids": [f"au-poll-{item[0]}" for item in selected_revisions],
                    "result_revision_id": f"au-result-{year}",
                    "aggregation": (
                        "Mean of five most recent complete national TPP polls visible in the "
                        "pinned archive revision; vector ordered Labor / Coalition"
                    ),
                }
            )

    payload = {
        "schema_version": 4,
        "description": (
            "Australian House TPP diagnostic using contemporaneously archived Wikipedia "
            "revisions and AEC-verified national results. Eighteen multi-origin records cover "
            "six elections from 2010 through 2025."
        ),
        "minimum_train_elections": 3,
        "source_revisions": revisions,
        "records": records,
    }
    output = root / "au-federal-tpp-2010-2025-v1.json"
    output.write_bytes(canonical_bytes(payload))
    return output, digests, vectors


if __name__ == "__main__":
    path, source_digests, computed_vectors = build()
    print(path)
    for revision_oldid, digest in sorted(source_digests.items()):
        print(f"{revision_oldid}={digest}")
    for year, values in computed_vectors.items():
        print(f"{year}={values}")
