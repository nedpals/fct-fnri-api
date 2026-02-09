import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query

app = FastAPI(title="FCT API", version="1.0.0")

DATA_DIR = Path("data")
FOODS_DIR = DATA_DIR / "foods"
TAXONOMY_PATH = DATA_DIR / "taxonomy.json"

DB: Optional[sqlite3.Connection] = None
CATEGORIES_CACHE: Optional[Dict[str, Any]] = None
NUTRIENTS_INDEX_CACHE: Optional[Dict[str, Any]] = None


def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def load_index():
    return load_json(FOODS_DIR / "index.json")


def error_response(code: str, message: str, status_code: int = 400):
    raise HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message}},
    )


def envelope(data: Any, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"data": data, "meta": meta or {}}


def get_db() -> sqlite3.Connection:
    if DB is None:
        raise RuntimeError("Cache not initialized")
    return DB


def init_cache() -> None:
    global DB, CATEGORIES_CACHE, NUTRIENTS_INDEX_CACHE

    DB = sqlite3.connect(":memory:", check_same_thread=False)
    DB.row_factory = sqlite3.Row

    DB.execute(
        """
        CREATE TABLE foods (
            id TEXT PRIMARY KEY,
            name TEXT,
            food_group_code TEXT,
            food_group TEXT,
            scientific_name TEXT,
            alternative_name TEXT,
            json TEXT
        )
        """
    )
    DB.execute(
        """
        CREATE TABLE nutrients (
            food_id TEXT,
            key TEXT,
            category TEXT
        )
        """
    )
    DB.execute("CREATE INDEX nutrients_food_id_idx ON nutrients(food_id)")
    DB.execute("CREATE INDEX nutrients_key_idx ON nutrients(key)")
    DB.execute("CREATE INDEX nutrients_category_idx ON nutrients(category)")

    index = load_index()
    foods = index.get("items", [])

    with DB:
        for item in foods:
            food_id = item.get("id")
            if not food_id:
                continue
            food_path = FOODS_DIR / f"{food_id}.json"
            if not food_path.exists():
                continue
            food = load_json(food_path)
            DB.execute(
                """
                INSERT OR REPLACE INTO foods (
                    id, name, food_group_code, food_group, scientific_name, alternative_name, json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    food_id,
                    item.get("name"),
                    item.get("food_group_code"),
                    item.get("food_group"),
                    item.get("scientific_name"),
                    item.get("alternative_name"),
                    json.dumps(food, ensure_ascii=True),
                ),
            )

            for entry in food.get("nutrients", []):
                DB.execute(
                    "INSERT INTO nutrients (food_id, key, category) VALUES (?, ?, ?)",
                    (food_id, entry.get("key"), entry.get("category")),
                )

    try:
        taxonomy = load_json(TAXONOMY_PATH)
        CATEGORIES_CACHE = taxonomy.get("categories")
        NUTRIENTS_INDEX_CACHE = taxonomy.get("nutrients")
    except FileNotFoundError:
        CATEGORIES_CACHE = None
        NUTRIENTS_INDEX_CACHE = None


@app.on_event("startup")
def on_startup() -> None:
    init_cache()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/foods")
def list_foods(
    q: Optional[str] = Query(default=None, min_length=1),
    category: Optional[str] = Query(default=None, min_length=1),
    nutrient: Optional[str] = Query(default=None, min_length=1),
    food_group_code: Optional[str] = Query(default=None, min_length=1, max_length=1),
    food_group: Optional[str] = Query(default=None, min_length=1),
    sort: str = Query(default="id"),
    order: str = Query(default="asc"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    db = get_db()

    where = []
    params: List[Any] = []

    if q:
        where.append("LOWER(name) LIKE ?")
        params.append(f"%{q.lower()}%")

    if category:
        where.append(
            "EXISTS (SELECT 1 FROM nutrients n WHERE n.food_id = foods.id AND n.category = ?)"
        )
        params.append(category)

    if nutrient:
        where.append(
            "EXISTS (SELECT 1 FROM nutrients n WHERE n.food_id = foods.id AND n.key = ?)"
        )
        params.append(nutrient)

    if food_group_code:
        where.append("foods.id LIKE ?")
        params.append(f"{food_group_code.upper()}%")

    if food_group:
        where.append("LOWER(foods.food_group) = ?")
        params.append(food_group.lower())

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sort_col = "id" if sort not in ("id", "name") else sort
    order_sql = "DESC" if order.lower() == "desc" else "ASC"

    count_sql = f"SELECT COUNT(*) as total FROM foods {where_sql}"
    total = db.execute(count_sql, params).fetchone()["total"]

    list_sql = (
        "SELECT id, name, food_group_code, food_group, scientific_name, alternative_name "
        f"FROM foods {where_sql} ORDER BY {sort_col} {order_sql} LIMIT ? OFFSET ?"
    )
    rows = db.execute(list_sql, params + [limit, offset]).fetchall()
    items = [dict(row) for row in rows]

    meta = {"total": total, "limit": limit, "offset": offset, "sort": sort_col, "order": order}
    return envelope(items, meta)


@app.get("/v1/foods/{food_id}")
def get_food(food_id: str):
    db = get_db()
    row = db.execute("SELECT json FROM foods WHERE id = ?", (food_id,)).fetchone()
    if not row:
        error_response("not_found", "Food not found", status_code=404)
    return envelope(json.loads(row["json"]))


@app.get("/v1/nutrients")
def list_nutrients():
    if NUTRIENTS_INDEX_CACHE is None:
        error_response("not_found", "Nutrient index not found", status_code=404)
    return envelope(NUTRIENTS_INDEX_CACHE)


@app.get("/v1/categories")
def list_categories():
    if CATEGORIES_CACHE is None:
        error_response("not_found", "Categories not found", status_code=404)
    return envelope(CATEGORIES_CACHE)
