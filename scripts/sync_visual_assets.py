from __future__ import annotations

import hashlib
import html
import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps" / "web" / "public"
USER_AGENT = "SDCofA-Election-Research/0.1 (https://github.com/SDCofA/election)"
RETRIEVED_AT = "2026-08-13"

FLAGS = ("ar", "au", "br", "ca", "cn", "fr", "de", "in", "id", "it", "jp", "mx", "ru", "sa", "za", "kr", "tr", "gb", "us")

# Wikimedia Commons filenames are pinned here; generated metadata retains credit and license.
COMMONS_ASSETS = {
    "portraits/anthony-albanese.jpg": "Anthony Albanese portrait (re-crop).jpg",
    "portraits/angus-taylor.jpg": "Angus Taylor 2018 portrait black.jpg",
    "portraits/lula.jpg": "Foto oficial de Luiz Inácio Lula da Silva (estreita).jpg",
    "portraits/flavio-bolsonaro.jpg": "Foto oficial do senador Flávio Bolsonaro (v. AgSen) (3x4).jpg",
    "portraits/prabowo-subianto.jpg": "Prabowo Subianto 2024 official portrait.jpg",
    "portraits/recep-tayyip-erdogan.jpg": "Portrait of Recep Tayyip Erdoğan, 2023 (cropped).jpg",
    "portraits/ozgur-ozel.jpg": "Özgür-Özel.jpg",
    "portraits/mansur-yavas.png": "Mansur Yavaş, 2019 (cropped).png",
    "portraits/ekrem-imamoglu.png": "Ekrem İmamoğlu 2024.png",
    "portraits/hakan-fidan.png": "GRM5406 (55240186269) (cropped).png",
    "portraits/javier-milei.jpg": "Javier Milei en el Salón Blanco 2 (cropped).jpg",
    "portraits/mark-carney.jpg": "2025-11-14 InaugurationREM Deux-Montagnes Mark Carney.jpg",
    "portraits/xi-jinping.jpg": "Xi Jinping meets Keir Starmer Jan 2026.jpg",
    "portraits/emmanuel-macron.jpg": "Emmanuel Macron 2025 (cropped).jpg",
    "portraits/narendra-modi.png": "Official Photograph of Prime Minister Narendra Modi Portrait.png",
    "portraits/giorgia-meloni.jpg": "Giorgia Meloni Official 2024 (cropped).jpg",
    "portraits/sanae-takaichi.jpg": "Official portrait of Sanae Takaichi, Prime Minister of Japan (HD).jpg",
    "portraits/claudia-sheinbaum.jpg": "Claudia Sheinbaum Argentina v Spain 19 July 2026-283.jpg",
    "portraits/lee-jae-myung.jpg": "President Lee Jae-myung 2025 (cropped).jpg",
    "portraits/vladimir-putin.jpg": "Vladimir Putin official photo 08.jpg",
    "portraits/mohammed-bin-salman.jpg": "الصورة الرسمية للأمير محمد بن سلمان بن عبدالعزيز آل سعود (مقصوصة).jpg",
    "portraits/cyril-ramaphosa.jpg": "21.11.2025 – Presidente da República da África do Sul, Cyril Ramaphosa (54938010569) (cropped).jpg",
    "portraits/andy-burnham.jpg": "Prime Minister Andy Burnham portrait (cropped).jpg",
    "logos/de-union.png": "Cdu-logo.svg",
    "logos/de-spd.png": "Sozialdemokratische Partei Deutschlands, Logo um 2000.svg",
    "logos/de-greens.png": "Bündnis 90 - Die Grünen Logo.svg",
    "logos/de-afd.png": "Alternative-fuer-Deutschland-Logo-2013.svg",
    "logos/de-left.png": "Logo Die Linke (2023).svg",
    "logos/gb-lab.png": "Labour Party Wordmark.svg",
    "logos/gb-con.png": "Conservative Party wordmark.svg",
    "logos/gb-ld.png": "Liberal Democrats logo (wordmark).svg",
    "logos/gb-ref.png": "Reform UK Party Ballot Logo.png",
    "logos/us-dem.png": "US Democratic Party 2025 logo (positive).svg",
    "logos/us-gop.png": "GOP logo.svg",
    "logos/au-labor.png": "Australian Labor Party Logo 2015.svg",
    "logos/au-liberal.png": "Liberal Party of Australia Logo 2015.png",
    "logos/tr-chp.png": "CHP logo (2024, vertical red).svg",
    "logos/id-gerindra.jpg": "Partai Gerindra logo.jpg",
}


def fetch(url: str) -> bytes:
    for attempt in range(5):
        request = Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=60) as response:
                return response.read()
        except HTTPError as error:
            if error.code != 429 or attempt == 4:
                raise
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"Could not download {url}")


def clean_credit(value: str | None) -> str:
    if not value:
        return "See source page"
    text = re.sub(r"<[^>]+>", " ", html.unescape(value))
    return re.sub(r"\s+", " ", text).strip()[:400]


def commons_info(filename: str) -> dict[str, str]:
    params = urlencode(
        {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "iiprop": "url|mime|extmetadata",
            "iiurlwidth": 520,
            "titles": f"File:{filename}",
        }
    )
    payload = json.loads(fetch(f"https://commons.wikimedia.org/w/api.php?{params}"))
    page = next(iter(payload["query"]["pages"].values()))
    if "missing" in page or not page.get("imageinfo"):
        raise RuntimeError(f"Commons asset missing: {filename}")
    image = page["imageinfo"][0]
    metadata = image.get("extmetadata", {})
    source = f"https://commons.wikimedia.org/wiki/File:{quote(filename.replace(' ', '_'))}"
    return {
        "download_url": image.get("thumburl") or image["url"],
        "source": source,
        "credit": clean_credit((metadata.get("Credit") or metadata.get("Artist") or {}).get("value")),
        "license": (metadata.get("LicenseShortName") or {}).get("value", "See source page"),
    }


def write_asset(relative_path: str, raw: bytes) -> str:
    path = PUBLIC / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    manifest: dict[str, dict[str, str]] = {}
    manifest_path = PUBLIC / "visual-assets.json"
    previous = (
        json.loads(manifest_path.read_text(encoding="utf-8")).get("assets", {})
        if manifest_path.exists()
        else {}
    )

    def cached(relative: str) -> dict[str, str] | None:
        path = PUBLIC / relative
        metadata = previous.get(relative)
        if not path.exists() or not metadata:
            return None
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return metadata if digest == metadata.get("sha256") else None

    for code in FLAGS:
        relative = f"flags/{code}.svg"
        if metadata := cached(relative):
            manifest[relative] = metadata
            continue
        source = f"https://flagcdn.com/{code}.svg"
        raw = fetch(source)
        manifest[relative] = {
            "source": source,
            "credit": "National flag; vector distributed by FlagCDN",
            "license": "Public-domain national symbol; verify local restrictions",
            "sha256": write_asset(relative, raw),
        }
    for relative, filename in COMMONS_ASSETS.items():
        if metadata := cached(relative):
            manifest[relative] = metadata
            continue
        time.sleep(0.8)
        info = commons_info(filename)
        time.sleep(0.8)
        raw = fetch(info.pop("download_url"))
        manifest[relative] = {**info, "sha256": write_asset(relative, raw)}
    output = {
        "retrieved_at": RETRIEVED_AT,
        "assets": dict(sorted(manifest.items())),
    }
    manifest_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
