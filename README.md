# fct-fnri-api

A collection of food composition data from the Philippine Food Composition Table (PhilFCT) project by the [Food and Nutrition Research Institute](https://www.fnri.dost.gov.ph/) (FNRI) extracted into easy-to-consume JSON files.

## What is PhilFCT?

PhilFCT is a database of commonly consumed foods in the Philippines, along with their nutritional content. 

## Motivation

I was in the middle of creating my own internal workout app and was looking for data sources for my food search feature that's local to the Philippines with the closest one I could find was PhilFCT website. However like any government project, they are only accessible through a clunky web interface.

Unlike other websites though, this one literally almost killed my browser as this website tries to fit all of the 11MB-worth of data into a single page plus creating 1000+ instances of Bootstrap modals. The data is very valuable and something should be done to it.

## Usage

### JSON Files

Simply clone or download the repository and go to `data/` folder. There you will find the JSON files for each food, an index file with minimal information for search, and a taxonomy file with categories and nutrients metadata. You can use these files in your own projects or applications.

```
data/
├── foods/
│   ├── index.json
│   ├── A001.json
│   ├── ...
|── taxonomy.json
```

### Rest API

This repository also includes a simple REST API server built with FastAPI that serves the food data. You can run the server and access the endpoints to query for foods, nutrients, and categories. **It requires Python 3.10+**.

To use the API server, first set up a virtual environment and install the dependencies:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

and then run the server:

```bash
uvicorn server:app
```

#### API Endpoints (v1)

- `GET /v1/foods`
  - Query params: `q`, `category`, `nutrient`, `food_group_code`, `food_group`, `sort`, `order`, `limit`, `offset`
- `GET /v1/foods/{id}`
- `GET /v1/nutrients`
- `GET /v1/categories`

Responses use a consistent envelope:

```json
{
  "data": {},
  "meta": {}
}
```

#### Caching

For instant responses, the API server employs an sqlite-based in-memory cache that is populated on startup by reading the JSON files. This allows for fast querying without the overhead of parsing JSON files on each request. To update the cache with new data, simply restart the server after adding or modifying the JSON files in the `data/foods/` directory.

## Data Extraction

The `extract.py` script extracts the data from the FNRI search page using beautifulsoup4 and saves it as JSON files. You can simply `python extract.py` to run the default extraction process.

It can also accept command line arguments for the URL and cache directory:

```bash
python extract.py https://i.fnri.dost.gov.ph/fct/library/search_item data
```

Cache directory (default: `data/cache`):

```bash
python extract.py --cache-dir data/cache
```

Outputs:

- `data/foods/` one JSON file per food
- `data/foods/index.json` minimal index
- `data/taxonomy.json` categories and nutrients metadata

## Notes

- Nutrients are mass-based entries (g/mg/µg). Energy values (kcal/kJ) are stored separately under `measurements` in each food file.
- Category section headers (e.g., "Fat-Soluble Vitamins") are stored in `taxonomy.json` under `categories[].sections`.

## License
This project is licensed under Creative Commons Zero (CC0) License. See [LICENSE](LICENSE) for more details.
