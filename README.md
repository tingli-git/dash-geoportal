
# Geo Portal Starter (Python-first)

A beginner-friendly template to build a local-first geospatial portal with:
- **Dash** (Python web app)
- **dash-leaflet** (maps + OSM basemap)
- **Plotly** (interactive charts)
- Local CSVs for time series
- Local XYZ raster tiles per year (e.g., classification maps)

## 0) Install
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 0.5) Run the Geoportal v9 Solara stack
```bash
# functions/geoportal/v9/app.py
# cd /datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/dash-geoportal/
# source .venv/bin/activate
# cd /datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server
# python scripts/app_server_index.py
#-----------------------------------
# in another terminal:
# cd /datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/dash-geoportal/
# source .venv/bin/activate
# python -m pip install -e .
# solara run --production /datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/dash-geoportal/functions/geoportal/v9/app.py 
## if solara not founded, run $ hash -r 
# solara application will be running at localhost:8765
# ------------------------------------
# in the third terminal 
# cloudflared tunnel --url http://localhost:8765
# copy the url that can be shared to others
```

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
source .venv/bin/activate
python scripts/build_province_tiles.py --force
python scripts/export_province_tiles.py --force
```

This runs the `tippecanoe` binary located at `/datawaha/esom/Ting/Projects/DatePlamMapping/gitrepo/tippecanoe/tippecanoe`, iterates through every `.gpkg` in `/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server/datepalms_per_province`, and writes `*.mbtiles` files with the same province name into `datepalms_tile_cache`. Make sure your tile server exposes `/{z}/{x}/{y}.pbf` for that directory before launching the dashboard so it can switch to the tile view when zoomed out.

## 1) Run
```bash
python app.py
```
Open http://127.0.0.1:8050

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
