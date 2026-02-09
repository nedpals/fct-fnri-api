#!/usr/bin/env python3
import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


def slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "unknown"


def parse_percent(text: str) -> Optional[float]:
    if not text:
        return None
    text = text.strip().replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_number(text: str) -> Optional[float]:
    if text is None:
        return None
    raw = text.strip()
    if raw == "" or raw == "-":
        return None
    if raw.lower() == "tr":
        return None
    raw = raw.replace(",", "")
    raw = raw.replace("\u00a0", " ").strip()
    # Handle < or > values by stripping the symbol
    raw = raw.lstrip("<>")
    try:
        return float(raw)
    except ValueError:
        return None


def parse_label(raw_label: str) -> (str, Optional[str]):
    raw_label = raw_label.strip()
    match = re.match(r"^(.*)\s*\(([^()]*)\)\s*$", raw_label)
    if match:
        name = match.group(1).strip()
        unit = match.group(2).strip() or None
        return name, unit
    return raw_label, None


def parse_id_from_onclick(onclick: Optional[str]) -> Optional[str]:
    if not onclick:
        return None
    match = re.search(r"less_load\((\d+)\)", onclick)
    return match.group(1) if match else None


def text_content(node) -> str:
    if not node:
        return ""
    return node.get_text(" ", strip=True)


def extract_category_label(modal, tab_id: str) -> Optional[str]:
    if not tab_id:
        return None
    nav = modal.select_one(".nav-tabs")
    if nav:
        link = nav.select_one(f"a[href='#{tab_id}']")
        if link:
            return text_content(link)
    return None


def extract_amount_basis(header_node) -> Optional[str]:
    if not header_node:
        return None
    span = header_node.find("span")
    if span:
        return text_content(span)
    # Fallback: try to split text
    text = text_content(header_node)
    match = re.search(r"Amount per\s+.*", text)
    return match.group(0) if match else None


def fetch_with_cache(url: str, cache_path: Path, retries: int = 3, pause_s: float = 1.5) -> str:
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")

    last_error = None
    for _ in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "fct-scraper/1.0"})
            with urlopen(req, timeout=30) as resp:
                chunks = []
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                data = b"".join(chunks)
            tmp_path.write_bytes(data)
            tmp_path.replace(cache_path)
            return cache_path.read_text(encoding="utf-8")
        except Exception as exc:
            last_error = exc
            time.sleep(pause_s)

    raise RuntimeError(f"Failed to fetch after {retries} attempts: {last_error}")


def load_html(source: str, cache_dir: Path) -> str:
    if source.startswith("http://") or source.startswith("https://"):
        cache_path = cache_dir / "search_item.html"
        return fetch_with_cache(source, cache_path)

    html_path = Path(source)
    return html_path.read_text(encoding="utf-8")


def extract_fct(source: str, out_dir: Path, cache_dir: Path) -> None:
    html = load_html(source, cache_dir)
    soup = BeautifulSoup(html, "html.parser")

    out_foods = out_dir / "foods"
    out_foods.mkdir(parents=True, exist_ok=True)

    tbody = soup.select_one("table tbody")
    if not tbody:
        raise RuntimeError("No table body found in HTML")

    catalog: List[Dict[str, str]] = []
    nutrient_catalog: Dict[str, Dict[str, Optional[str]]] = {}
    category_catalog: Dict[str, Dict[str, object]] = {}

    for row in tbody.select("tr"):
        cols = row.find_all("td")
        if len(cols) < 6:
            continue

        food_id = text_content(cols[0])
        if not food_id:
            continue
        food_group_code = food_id[0].upper()
        food_group = {
            "A": "Cereals and Products",
            "B": "Starchy Roots, Tubers and Products",
            "C": "Nuts, Dried Beans, Seeds and Products",
            "D": "Vegetables and Products",
            "E": "Fruits and Products",
            "F": "Meat and Other Animals and Products",
            "G": "Finfish, Shellfish and Other Aquatic Animals and Products",
            "H": "Eggs and Products",
            "J": "Milk and Products",
            "K": "Fats and Oils",
            "M": "Sugar, Syrup and Confectionery",
            "N": "Condiments and Spices",
            "P": "Alcoholic Beverages",
            "Q": "Non-Alcoholic Beverages",
            "R": "Combination Foods/Mixed Dishe",
            "S": "Baby Foods",
            "T": "Miscellaneous",
        }.get(food_group_code)

        name = text_content(cols[1])
        scientific_name = text_content(cols[2]) or None
        alternative_name = text_content(cols[3]) or None
        edible_portion_pct = parse_percent(text_content(cols[4]))

        data_btn = row.select_one("button[data-target]")
        if not data_btn:
            continue
        modal_id = data_btn.get("data-target", "").lstrip("#")
        modal = soup.find("div", {"id": modal_id})
        if not modal:
            continue

        image_btn = row.select_one("button[onclick^='less_load']")
        image_id = parse_id_from_onclick(image_btn.get("onclick") if image_btn else None)
        image_url = (
            f"https://i.fnri.dost.gov.ph/fct/library/load_image_fct/{image_id}"
            if image_id
            else None
        )

        report_link = modal.select_one("a[href*='/fct/library/report/']")
        report_url = report_link.get("href") if report_link else None
        report_id = report_url.split("/")[-1] if report_url else None

        categories_seen = set()
        nutrients: List[Dict[str, object]] = []
        measurements: List[Dict[str, object]] = []

        for tab in modal.select(".tab-pane"):
            tab_id = tab.get("id", "")
            category_label = extract_category_label(modal, tab_id) or text_content(
                tab.select_one(".list-group-item.active")
            )
            if not category_label:
                category_label = tab_id

            category_key = slug(category_label)
            header = tab.select_one(".list-group-item.active")
            amount_basis = extract_amount_basis(header)
            if category_key not in category_catalog:
                category_catalog[category_key] = {
                    "key": category_key,
                    "label": category_label,
                    "amount_basis": amount_basis,
                    "count": 0,
                    "sections": set(),
                }
            elif category_catalog[category_key].get("amount_basis") in (None, "") and amount_basis:
                category_catalog[category_key]["amount_basis"] = amount_basis
            categories_seen.add(category_key)

            for li in tab.select(".list-group-item"):
                if "active" in li.get("class", []):
                    continue
                label_node = li.select_one(".col-md-9")
                value_node = li.select_one(".col-md-3")
                if not label_node or not value_node:
                    section_label = text_content(li)
                    if section_label:
                        category_catalog[category_key]["sections"].add(section_label)
                    continue
                raw_label = text_content(label_node)
                raw_value = text_content(value_node)
                if not raw_label:
                    continue

                name_label, unit = parse_label(raw_label)
                key = slug(raw_label)
                value = parse_number(raw_value)

                entry = {
                    "key": key,
                    "name": name_label,
                    "value": value,
                    "unit": unit,
                    "raw_label": raw_label,
                    "raw_value": raw_value,
                    "category": category_key,
                }
                if unit and unit.lower() in ("kcal", "kj", "kilocalorie", "kilojoule"):
                    measurements.append(entry)
                else:
                    nutrients.append(entry)

                if key not in nutrient_catalog:
                    nutrient_catalog[key] = {
                        "key": key,
                        "name": name_label,
                        "unit": unit,
                        "raw_label": raw_label,
                    }

        food_item = {
            "id": food_id,
            "name": name,
            "food_group_code": food_group_code,
            "food_group": food_group,
            "scientific_name": scientific_name,
            "alternative_name": alternative_name,
            "edible_portion_pct": edible_portion_pct,
            "report_id": report_id,
            "report_url": report_url,
            "image_id": image_id,
            "image_url": image_url,
            "nutrients": nutrients,
            "measurements": measurements,
        }

        (out_foods / f"{food_id}.json").write_text(
            json.dumps(food_item, ensure_ascii=True, indent=2), encoding="utf-8"
        )

        catalog.append(
            {
                "id": food_id,
                "name": name,
                "food_group_code": food_group_code,
                "food_group": food_group,
                "scientific_name": scientific_name,
                "alternative_name": alternative_name,
            }
        )

        for category_key in categories_seen:
            category_catalog[category_key]["count"] += 1

    catalog.sort(key=lambda item: item["id"])
    nutrient_items = sorted(nutrient_catalog.values(), key=lambda item: item["key"])

    index_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_items": len(catalog),
            "total_nutrients": len(nutrient_items),
        },
        "items": catalog,
    }

    (out_foods / "index.json").write_text(
        json.dumps(index_payload, ensure_ascii=True, indent=2), encoding="utf-8"
    )

    nutrient_items = sorted(nutrient_catalog.values(), key=lambda item: item["key"])
    category_items = []
    for item in category_catalog.values():
        item = dict(item)
        item["sections"] = sorted(item["sections"])
        category_items.append(item)
    category_items.sort(key=lambda item: item["key"])

    taxonomy = {
        "generated_at": index_payload["generated_at"],
        "summary": {
            "total_nutrients": len(nutrient_items),
            "total_categories": len(category_items),
        },
        "nutrients": nutrient_items,
        "categories": category_items,
    }
    (out_dir / "taxonomy.json").write_text(
        json.dumps(taxonomy, ensure_ascii=True, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract FCT data from HTML into JSON")
    parser.add_argument(
        "source",
        type=str,
        nargs="?",
        default="https://i.fnri.dost.gov.ph/fct/library/search_item",
        help="Path to fct.html or URL (default: search_item endpoint)",
    )
    parser.add_argument(
        "out_dir",
        type=Path,
        nargs="?",
        default=Path("data"),
        help="Output directory (default: data)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache"),
        help="Cache directory for fetched HTML (default: data/cache)",
    )
    args = parser.parse_args()

    extract_fct(args.source, args.out_dir, args.cache_dir)


if __name__ == "__main__":
    main()
