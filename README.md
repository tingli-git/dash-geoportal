
# Geo Portal Starter (Python-first)

A beginner-friendly template to build a local-first geospatial portal with:
- **Dash** (Python web app)
- **dash-leaflet** (maps + OSM basemap)
- **Plotly** (interactive charts)
- Local CSVs for time series
- Local XYZ raster tiles per year (e.g., classification maps)

## 0) Install
```bash
cd /datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/dash-geoportal/
#python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
#pip install -r requirements.txt
python -m pip install -e . 
```

## 0.5) Run the Geoportal v9 stack (legacy)
You need two dedicated servers before the Solara app:

1. **Vector tile/CORS server (port 8766)**  
   Serve `/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server` so both the raster subfolders and `datepalms_tiles` are reachable with `Access-Control-Allow-Origin`. From the repo root run:
   ```bash
   cd /datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/dash-geoportal
   source .venv/bin/activate
   python scripts/start_tile_server.py \
     --directory /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server \
     --host 0.0.0.0 \
     --port 8766
   ```
   The script uses a threaded HTTP server, so consult `Access-Control-Allow-*` headers while developing. Leave this process running while you work with the dashboard.

2. **Solara dashboard (port 8765)**  
   In another terminal:
   ```bash
   cd /datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/dash-geoportal/
   source .venv/bin/activate
   python -m pip install -e .
  solara run --production functions/geoportal/v9/app.py
   ```
   If `solara` isn’t found, run `hash -r` or reinstall within the active virtualenv. The dashboard will start at `http://localhost:8765`.

3. **Optional: share the app**  
   If you need a public URL, start `cloudflared tunnel --url http://localhost:8765` in a third terminal and copy the auto-generated address to share with stakeholders.

## 0.6) Run the Geoportal v10 stack
The v10 stack builds on the same infrastructure but points to the new code in `functions/geoportal/v10`. Use the identical tile/CORS server above, then run:
```bash
cd /datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/dash-geoportal/
source .venv/bin/activate
python -m pip install -e .
solara run --production functions/geoportal/v10/app.py
```
The v10 app loads its configuration from `functions/geoportal/v10/config.py` (a copy of the v9 config) and shares the same helpers under `functions/geoportal/v10/*`. You can still expose it with Cloudflare as before if you need a shareable URL.

## 0.75) Prebuild simplified Date Palm Fields (optional)

Before launching v9, cache the simplified per-province GeoJSONs so the dashboard can load them instantly when zoomed out:

```bash
source .venv/bin/activate
python scripts/build_date_palm_simple.py --force
```

The script reads each `.gpkg` inside `/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/datepalms_per_province`, applies the tolerance in `functions/geoportal/v9/config.py`, and writes the simplified outputs to the directory configured as `datepalms_per_province_simple`. The dashboard automatically reuses these files when you select the "Date Palm Fields" product.

## 0.8) Generate Tippecanoe tiles (required for zoom ≤16)

Before you start the hybrid map (tiles + polygons), prebuild vector tiles for every province and host them with your HTTP server (e.g., the same `python -m http.server 8766` process can serve the cache directory).

```bash
cd /datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/dash-geoportal/
source .venv/bin/activate
python scripts/build_province_tiles.py --force
python scripts/export_province_tiles.py --force
```

This runs the `tippecanoe` binary located at `/datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/tippecanoe/tippecanoe`, iterates through every `.gpkg` in `/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/datepalms_per_province`, and writes `*.mbtiles` files with the same province name into `datepalms_tile_cache`. Make sure your tile server exposes `/{z}/{x}/{y}.pbf` for that directory before launching the dashboard so it can switch to the tile view when zoomed out.

### (Optional) Normalize province GeoPackages
If you want globally unique IDs for each field plus a province ID lookup, normalize the source GeoPackages before vectorizing:
```bash
source .venv/bin/activate
python scripts/normalize_provinces.py \
  --dir /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/datepalms_per_province \
  --mapping datepalms_province_ids.json
```
Each rewritten `.gpkg` now contains `field_id`, `province_id`, and `esti_tree_number`, and you can reference `datepalms_province_ids.json` (which maps each `province_id` to the province name) elsewhere in the dashboard.


## 2) Add your sensors
- Put your points in `data/sensors.geojson` (GeoJSON Point features).
- For each sensor, create `data/sensors/<sensor_id>.csv` with columns: `timestamp,soil_moisture,soil_temp`.
- Timestamps in ISO8601, ideally UTC (e.g., `2025-01-01T00:00:00Z`).

## 3) Add your rasters (per year)
If you have a classification GeoTIFF per year, use `gdal2tiles.py` to generate XYZ tiles.

Example (zoom 0–14; adjust to your scale):
```bash
gdal2tiles.py -z 0-14 -r near -w none classmap_2024.tif data/rasters/tiles_2024
gdal2tiles.py -z 0-14 -r near -w none classmap_2021.tif data/rasters/tiles_2021
```
Then edit `YEARS = [2021, 2024]` in `app.py` to include your years.

The app serves tiles at `/tiles/<year>/{z}/{x}/{y}.png`.

> Tip: If you prefer Cloud-Optimized GeoTIFFs (COG) and on-the-fly tiling later, add a tiny TiTiler service and point the `dl.TileLayer(url=...)` to your TiTiler URL.

## 4) Year slider
The slider switches the raster layer by setting the tile URL to the chosen year.

## 5) Charting sensor data
Click a sensor to select it, choose variable and time range, then click **Load series**.

## 6) Basemap
Default is **OSM** (allowed with attribution). Do **not** use Google Satellite tiles directly here unless you use Google Maps JS API per its terms.

## 7) Deploy (later)
- Static + tiles on S3/Cloudflare R2, app on a small VM or container.
- Or host everything on a single VM. Reverse-proxy with Nginx if needed.

## Troubleshooting
- Missing tile? Ensure the folder exists, e.g., `data/rasters/tiles_2024/…/z/x/y.png`.
- CSV not found? Place it at `data/sensors/<sensor_id>.csv` matching the GeoJSON property.
- Time zone: the inputs are treated as UTC in this starter; adapt if you store local time.
