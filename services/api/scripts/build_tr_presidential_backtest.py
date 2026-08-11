from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

RETRIEVED_AT = "2026-08-11"
LICENSE = "CC-BY-SA-4.0"
LICENSE_URL = "https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use"
USER_AGENT = "SDCofA-Election-Research/0.1 (https://github.com/SDCofA/election)"

# Exact revision timestamps prove what the archive showed before each cutoff. Poll vectors are
# normalized means of the five most recent complete first-round rows (all available rows when
# fewer than five existed), consolidated as governing candidate / leading opposition / other.
POLL_SNAPSHOTS = {
    2014: (
        (616697875, "2014-07-12", (0.546000, 0.370000, 0.084000)),
        (618663618, "2014-07-27", (0.547200, 0.364200, 0.088600)),
        (619730280, "2014-08-03", (0.546351, 0.372361, 0.081288)),
        (620427821, "2014-08-08", (0.555130, 0.354204, 0.090666)),
    ),
    2018: (
        (842957147, "2018-05-25", (0.462600, 0.236200, 0.301200)),
        (845086654, "2018-06-09", (0.463693, 0.266253, 0.270054)),
        (846277271, "2018-06-17", (0.454818, 0.298880, 0.246301)),
        (847026267, "2018-06-22", (0.485600, 0.288400, 0.226000)),
    ),
    2023: (
        (1149804105, "2023-04-14", (0.440112, 0.484103, 0.075785)),
        (1152538172, "2023-04-30", (0.464214, 0.476809, 0.058976)),
        (1153703556, "2023-05-07", (0.458600, 0.476000, 0.065400)),
        (1154485389, "2023-05-12", (0.472167, 0.485583, 0.042251)),
    ),
}

ELECTIONS = {
    2014: {
        "title": "2014 Turkish presidential election",
        "election_date": "2014-08-10",
        "actual": (0.5179, 0.3844, 0.0976),
        "fundamentals": (0.4983, 0.3899, 0.1118),
        "fundamentals_title": "2011 Turkish general election",
        "fundamentals_oldid": 604591433,
        "fundamentals_available": "2014-04-17",
        "result_oldid": 620910423,
        "result_available": "2014-08-12",
    },
    2018: {
        "title": "Opinion polling for the 2018 Turkish general election",
        "result_title": "2018 Turkish presidential election",
        "election_date": "2018-06-24",
        "actual": (0.5259, 0.3064, 0.1677),
        "fundamentals": (0.5179, 0.3844, 0.0976),
        "fundamentals_title": "2014 Turkish presidential election",
        "fundamentals_oldid": 841341444,
        "fundamentals_available": "2018-05-15",
        "result_oldid": 847809926,
        "result_available": "2018-06-27",
    },
    2023: {
        "title": "Opinion polling for the 2023 Turkish presidential election",
        "result_title": "2023 Turkish presidential election",
        "election_date": "2023-05-14",
        "actual": (0.4952, 0.4488, 0.0560),
        "fundamentals": (0.5259, 0.3064, 0.1677),
        "fundamentals_title": "2018 Turkish presidential election",
        "fundamentals_oldid": 1149374737,
        "fundamentals_available": "2023-04-11",
        "result_oldid": 1156027684,
        "result_available": "2023-05-20",
    },
}

PINNED_SHA256 = {
    604591433: "293fe683f69636d7b3197d07d88983ead6b15a037290673dda1480dd659cc313",
    616697875: "bf86c8a201fad808c6fd6c468dee56031519aaf6580cbef45b196913d35113ae",
    618663618: "5ce973952783980ef446db20696650fc6747890ffca37a6529f25923f4204267",
    619730280: "69cd4c4cd6c4deb6e4477c1d77b7cba09136f80ba2f44f6123ed1c3f68eff00b",
    620427821: "0c70a21f63e3ee6228fabeed0b088c6c11a7682d4cfbbddaddb653ebe4a38b48",
    620910423: "7ec7013caddb93ec3c648168199dcc8acf9dfbff8ac6e783c2c0537106b28105",
    841341444: "2035bd8212f87d27191d6b465185ac8c5caad9f8711a2669a2d0648694a551fb",
    842957147: "63398fbef3e982a009a53b2876ba27d62018add81f2f2993c499a34ca9ace289",
    845086654: "34809dcf7a4a5ae0564fd13725691d6f948a2a6f380281db72088f14b7f625c8",
    846277271: "f14f23f13fff155462ab54f644826052da6996e69e3b224189b27c12345aeb62",
    847026267: "ff6bddaf4b69b66eb759538b9fd8a786e703f353c72eca81fbe7155337eadf97",
    847809926: "18aaa021f638813f5639e3d632e0ad355614ca393fd48c2df853aec9ffd813fe",
    1149374737: "fa2dc5b00c2fe1ab1d2a4b93286f94d3a3705208ee23c62a1ae99d244cdda978",
    1149804105: "719c20ec804bc79cd39d9742dbbab392b9e3820b12bc08726b27f85cacdbe344",
    1152538172: "004f0ba0d3faf760a495fc5e998351db021cc3a01d2b899670cb1f882a318f43",
    1153703556: "150250a336d6f15812bdfc253f0a106383cda14ab776e543cf44a319af2806fe",
    1154485389: "77b5581d57ea56c25776f69223f7a242a64a97e7d7112ad240b3fd5f7be1ef8e",
    1156027684: "5d5da5e410ed73602fe108461a514eaf29f9723d34c3dbeebd980bc6374f3e70",
}


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def normalized(values: tuple[float, ...]) -> list[float]:
    total = sum(values)
    return [value / total for value in values]


def _table_after(raw: str, marker: str) -> str:
    match = re.search(marker, raw, flags=re.IGNORECASE | re.MULTILINE)
    if match is None:
        raise ValueError(f"Missing polling table marker: {marker}")
    marker_start = match.end()
    table_start = raw.find("{|", marker_start)
    table_end = raw.find("|}", table_start)
    if table_start < 0 or table_end < 0:
        raise ValueError(f"Incomplete polling table after: {marker}")
    return raw[table_start : table_end + 2]


def _row_cells(block: str) -> list[str]:
    cells: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("!"):
            cells.extend(part.strip() for part in stripped[1:].split("!!"))
            continue
        if not stripped.startswith("|") or stripped.startswith(("|-", "|}")):
            continue
        cells.extend(part.strip() for part in stripped[1:].split("||"))
    return cells


def _cell_number(cell: str) -> float | None:
    matches = re.findall(r"(?<![\d,])(\d{1,2}(?:\.\d+)?)(?![\d,])", cell)
    return float(matches[-1]) if matches else None


def poll_vector_from_wikitext(raw: str, year: int) -> list[float]:
    marker = {
        2014: r"^==\s*Opinion polls\s*==\s*$",
        2018: r"^=+\s*Following candidate selection\s*=+\s*$",
        2023: r"^=+\s*Official campaign polling\s*=+\s*$",
    }[year]
    table = _table_after(raw, marker)
    has_other_column = "Others" in table[:3_000]
    rows: list[list[float]] = []
    for block in re.split(r"(?m)^\|-[^\n]*$", table):
        cells = _row_cells(block)
        if year == 2014 and len(cells) >= 6:
            candidates = [_cell_number(cell) for cell in cells[2:5]]
        elif year == 2018 and len(cells) >= 11:
            raw_candidates = [_cell_number(cell) for cell in cells[3:9]]
            candidates = (
                None
                if any(value is None for value in raw_candidates)
                else [
                    raw_candidates[0],
                    raw_candidates[1],
                    sum(value for value in raw_candidates[2:] if value is not None),
                ]
            )
        elif year == 2023:
            tail = 6 if has_other_column else 5
            if len(cells) < tail:
                continue
            raw_candidates = [_cell_number(cell) or 0.0 for cell in cells[-tail:-1]]
            candidates = [raw_candidates[0], raw_candidates[1], sum(raw_candidates[2:])]
        else:
            continue
        if (
            candidates is not None
            and all(value is not None for value in candidates)
            and 95 <= sum(float(value) for value in candidates) <= 105
        ):
            rows.append([float(value) for value in candidates])
    selected = rows[-5:] if year == 2014 else rows[:5]
    if not selected:
        raise ValueError(f"No complete {year} first-round polling rows found")
    averages = tuple(sum(row[index] for row in selected) / len(selected) for index in range(3))
    return normalized(averages)


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
    relative_path = f"raw/tr/wikipedia-oldid-{oldid}.wikitext"
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return relative_path, hashlib.sha256(raw).hexdigest()


def revision(
    revision_id: str,
    role: str,
    oldid: int,
    observed_at: str,
    available_at: str,
    digest: str,
    raw_path: str,
) -> dict[str, str]:
    return {
        "id": revision_id,
        "source_url": source_url(oldid),
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "authority": "Wikipedia immutable revision; results cross-checked against YSK",
        "role": role,
        "observed_at": observed_at,
        "released_at": available_at,
        "available_at": available_at,
        "retrieved_at": RETRIEVED_AT,
        "sha256": digest,
        "raw_path": raw_path,
        "vintage_proof": "contemporaneous_archive",
    }


def build() -> tuple[Path, dict[int, str]]:
    root = Path(__file__).resolve().parents[1] / "app" / "backtests"
    revisions: list[dict[str, str]] = []
    records: list[dict[str, object]] = []
    digests: dict[int, str] = {}
    raw_metadata: dict[int, tuple[str, str]] = {}

    def materialize(title: str, oldid: int) -> tuple[str, str]:
        if oldid not in raw_metadata:
            raw_metadata[oldid] = write_raw(root, title, oldid)
            digests[oldid] = raw_metadata[oldid][1]
        return raw_metadata[oldid]

    for year, election in ELECTIONS.items():
        poll_title = str(election["title"])
        for oldid, available_at, vector in POLL_SNAPSHOTS[year]:
            if abs(sum(vector) - 1.0) > 0.002:
                raise ValueError(f"{year} poll vector {oldid} is not normalized")
            raw_path, digest = materialize(poll_title, oldid)
            computed = poll_vector_from_wikitext(
                (root / raw_path).read_text(encoding="utf-8"), year
            )
            if any(abs(actual - expected) > 0.000002 for actual, expected in zip(computed, vector)):
                raise ValueError(
                    f"{year} archive aggregate {oldid} diverged: {computed} != {vector}"
                )
            revisions.append(
                revision(
                    f"tr-poll-{oldid}",
                    "poll",
                    oldid,
                    available_at,
                    available_at,
                    digest,
                    raw_path,
                )
            )

        fundamentals_oldid = int(election["fundamentals_oldid"])
        raw_path, digest = materialize(str(election["fundamentals_title"]), fundamentals_oldid)
        revisions.append(
            revision(
                f"tr-fundamentals-{year}",
                "fundamentals",
                fundamentals_oldid,
                str(election["fundamentals_available"]),
                str(election["fundamentals_available"]),
                digest,
                raw_path,
            )
        )

        result_oldid = int(election["result_oldid"])
        raw_path, digest = materialize(
            str(election.get("result_title", election["title"])), result_oldid
        )
        revisions.append(
            revision(
                f"tr-result-{year}",
                "result",
                result_oldid,
                str(election["election_date"]),
                str(election["result_available"]),
                digest,
                raw_path,
            )
        )

        election_date = date.fromisoformat(str(election["election_date"]))
        snapshots = POLL_SNAPSHOTS[year]
        for index in range(1, len(snapshots)):
            selected = snapshots[: index + 1]
            forecast_as_of = date.fromisoformat(selected[-1][1])
            if forecast_as_of >= election_date:
                raise ValueError(f"{year} forecast cutoff must precede the election")
            records.append(
                {
                    "election_id": f"tr-president-{year}",
                    "election_date": election_date.isoformat(),
                    "actual_shares": normalized(tuple(election["actual"])),
                    "fundamentals_shares": normalized(tuple(election["fundamentals"])),
                    "polling_snapshots": [normalized(item[2]) for item in selected],
                    "forecast_as_of": forecast_as_of.isoformat(),
                    "fundamentals_available_at": election["fundamentals_available"],
                    "polling_snapshot_dates": [item[1] for item in selected],
                    "result_available_at": election["result_available"],
                    "fundamentals_revision_id": f"tr-fundamentals-{year}",
                    "polling_revision_ids": [f"tr-poll-{item[0]}" for item in selected],
                    "result_revision_id": f"tr-result-{year}",
                    "aggregation": (
                        "Mean of five most recent complete first-round polls visible in the "
                        "pinned archive revision; remaining candidates consolidated as other"
                    ),
                }
            )

    payload = {
        "schema_version": 4,
        "description": (
            "Türkiye presidential diagnostic using contemporaneously archived Wikipedia "
            "revision snapshots. Nine multi-origin records cover three direct elections; "
            "the evidence cannot satisfy the three-held-out-election promotion gate."
        ),
        "minimum_train_elections": 2,
        "source_revisions": revisions,
        "records": records,
    }
    output = root / "tr-presidential-2014-2023-v1.json"
    output.write_bytes(canonical_bytes(payload))
    return output, digests


if __name__ == "__main__":
    path, source_digests = build()
    print(path)
    for revision_oldid, digest in sorted(source_digests.items()):
        print(f"{revision_oldid}={digest}")
