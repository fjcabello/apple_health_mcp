# Apple Health MCP Server

An [MCP](https://modelcontextprotocol.io/) server that exposes Apple Health data as tools queryable by LLMs (Claude, Copilot, etc.).

## Architecture

```
exportación.xml (Apple Health)
        │
        ▼
  preprocess.py  ──►  data/*.parquet   (run once on Mac)
                              │
                              ▼  (rsync to Pi)
                        server.py (FastMCP, port 8001)
                              │
                              ▼
            Cloudflare Tunnel → <your-apple-health-tunnel-hostname>
                              │
                              ▼
              apple-health-worker (Cloudflare Worker OAuth)
                              │
                    https://<your-worker>.workers.dev
```

The server loads Parquet files at startup (~1-2 s). If they are not found, it falls back to parsing the XML directly.

---

## Requirements

- Python 3.11+
- `pyarrow` (for Parquet support)

```bash
pip install -r requirements.txt
pip install pyarrow
```

### `requirements.txt`
```
mcp[cli]>=1.0.0
lxml>=5.0.0
pandas>=2.0.0
pyarrow>=15.0.0
uvicorn>=0.30.0
```

---

## Data update workflow

There are two ways to keep data up to date: a manual export/preprocess flow, and
an automated push via the [Health Auto Export](https://healthyapps.dev) app.

### 1. Export from iPhone

`Health → profile → Export All Health Data` → produces a ZIP containing `exportación.xml`.

### 2. Preprocess on Mac

```bash
cd ~/Personal/apple_health/apple_health_mcp

# XML is expected at ../apple_health_export/exportación.xml (default)
python preprocess.py

# Or with a custom path:
python preprocess.py --export /path/to/exportación.xml
```

Produces `data/*.parquet` (~20 files, one per metric type).

### 3. Sync data to Raspberry Pi

```bash
rsync -avz \
  ~/path/to/apple_health_mcp/data/ \
  <user>@<raspberry-pi-ip>:/home/<user>/applehealth/apple_health_mcp/data/
```

### 4. Restart the service on the Pi

```bash
ssh <user>@<raspberry-pi-ip> "sudo systemctl restart apple-health-mcp"
```

---

## Running locally (development)

```bash
python server.py
# Listens on http://0.0.0.0:8001/mcp
```

Optional environment variables:

| Variable | Default | Description |
|---|---|---|
| `APPLE_HEALTH_DATA_DIR` | `./data` | Directory containing `.parquet` files |
| `APPLE_HEALTH_EXPORT` | `../apple_health_export/exportación.xml` | XML fallback path |

---

## Raspberry Pi deployment

### Systemd service

File: `/etc/systemd/system/apple-health-mcp.service`

```ini
[Unit]
Description=Apple Health MCP Server
After=network.target

[Service]
User=<user>
WorkingDirectory=/home/<user>/applehealth
Environment=APPLE_HEALTH_DATA_DIR=/home/<user>/applehealth/apple_health_mcp/data
ExecStart=/home/<user>/applehealth/apple_health_mcp/.venv/bin/python \
          /home/<user>/applehealth/apple_health_mcp/server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable apple-health-mcp
sudo systemctl start apple-health-mcp
sudo systemctl status apple-health-mcp
```

### Cloudflare Tunnel

Both Apple Health and Garmin MCP services share the **same tunnel**, remotely managed via the [Cloudflare Zero Trust dashboard](https://one.dash.cloudflare.com/).

- **Tunnel name:** `<your-tunnel-name>`
- **Tunnel ID:** `<your-tunnel-id>`

| Public hostname | Local service |
|---|---|
| `<your-apple-health-hostname>` | `http://127.0.0.1:8001` (Apple Health MCP) |
| `<your-garmin-hostname>` | `http://127.0.0.1:8000` (Garmin MCP) |

The `cloudflared` service on the Pi connects to Cloudflare and picks up the routing rules from the dashboard automatically.

```bash
# Check tunnel status on the Pi
sudo systemctl status cloudflared

# Add/edit public hostnames:
# Cloudflare Zero Trust → Networks → Tunnels → <your-tunnel-name> → Public Hostnames
```

**Public MCP endpoint:**
```
https://<your-apple-health-hostname>/mcp
```

---

## Available MCP tools

| Tool | Description |
|---|---|
| `health_summary` | Overview of all available data types, record counts and date ranges |
| `get_steps` | Daily step counts |
| `get_heart_rate` | Heart rate per day (mean / min / max) |
| `get_resting_heart_rate` | Daily resting heart rate |
| `get_sleep` | Sleep analysis by stage (Core, Deep, REM, Awake) |
| `get_workouts` | Workout sessions, filterable by type and date |
| `get_body_metrics` | Weight (kg), BMI, body fat %, lean body mass |
| `get_activity_energy` | Active/basal energy burned, distance, flights climbed |
| `get_nutrition` | Nutritional intake (calories, protein, carbs, fat) |
| `query_health_data` | Generic query for any available metric |

All tools accept optional `start_date` and `end_date` parameters in `YYYY-MM-DD` format.

### Available metrics for `query_health_data`

`steps`, `heart_rate`, `resting_hr`, `active_energy`, `basal_energy`, `distance_walk`, `distance_cycling`, `flights_climbed`, `sleep`, `body_mass`, `bmi`, `body_fat`, `lean_body_mass`, `walking_speed`, `walking_steadiness`, `dietary_energy`, `dietary_protein`, `dietary_carbs`, `dietary_fat`

---

## Cloud access (OAuth)

The Cloudflare Worker adds OAuth 2.0 authentication for remote access from Claude.ai or VS Code.

**Public URL:** `https://<your-worker>.workers.dev/mcp`

### VS Code configuration

```json
// .vscode/mcp.json
{
  "servers": {
    "apple-health-cloud": {
      "type": "http",
      "url": "https://<your-worker>.workers.dev/mcp"
    }
  }
}
```

### Worker source

See `../apple-health-worker/` in the workspace.

---

## Automated sync via Health Auto Export

Instead of manually exporting the Apple Health ZIP, the [Health Auto Export](https://healthyapps.dev)
iOS app can push data automatically to the server via a `POST /ingest` endpoint,
which upserts directly into the Parquet files (no XML/preprocess step needed).

### Endpoint

```
POST /ingest
GET  /ingest/inspect   (returns the last received payload, for debugging)
```

Authentication: header `X-API-Key: <secret>` (preferred) or query param `?api_key=<secret>`.
The secret is read from the `INTERNAL_SECRET` environment variable on the server
(separate from any Cloudflare Worker OAuth secret — this one guards the raw `/ingest` route).

### Recommended app configuration

Create **one automation per data type** in Health Auto Export (the app only allows
one data type per automation):

| Automation | Data type | Notes |
|---|---|---|
| Health Metrics | `Métricas de salud` | Select the metrics listed in `config.py` → `HK_TYPE_MAP` |
| Workouts | `Entrenamientos` | Enable "Include workout metrics" for HR/energy per workout |
| Heart rate notifications | `Frecuencia cardiaca` | High/low HR alert events (not yet parsed server-side) |

For all automations:

- **Format:** JSON, **Export version:** v2
- **Date range:** "Desde última sincronización" (incremental)
- **Header:** `X-API-Key` → your `INTERNAL_SECRET` value
- **Batch requests:** enable if you select many metrics or long date ranges —
  some metrics (e.g. headphone audio exposure) can produce per-minute samples
  across many hours in a single request, which risks timeouts
- **Units:** make sure energy metrics are configured to send `kcal` (not `kJ`)
  to stay consistent with the historical XML-derived data
- **Cadence:** hourly or daily is plenty — very short intervals (minutes) mostly
  get self-throttled by the app anyway (min. 60s between real executions)

### How ingestion works

- Each `/ingest` call upserts only the metrics/workouts present in that payload
  (dedup by `startDate`, or `startDate` + `activityType` for workouts) — it does
  **not** overwrite unrelated data, so partial/batched requests are safe.
- The in-memory cache is invalidated after each successful ingest, so the next
  MCP tool call reloads fresh data from Parquet.
- `GET /ingest/inspect` (same auth) returns the last raw payload received, useful
  for verifying the exact JSON shape the app sends before adding support for a
  new data type (e.g. heart rate notifications, symptoms, ECG).
