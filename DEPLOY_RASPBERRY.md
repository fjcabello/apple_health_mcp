# Deploy Apple Health MCP Server → Raspberry Pi

## Qué es esto
Servidor MCP (Model Context Protocol) que expone datos de Apple Health para que
GitHub Copilot u otros agentes LLM puedan consultarlos en lenguaje natural.

Comunicación: **stdio** (no HTTP). VS Code lanza el proceso como subproceso.

---

## Ficheros a copiar al Raspberry (desde este directorio)

```
apple_health_mcp/
├── server.py          ← servidor MCP principal
├── preprocess.py      ← script para regenerar data/ desde un nuevo export.xml
├── requirements.txt   ← dependencias Python
└── data/              ← datos preprocesados en Parquet (copiar TODO el directorio)
    ├── steps.parquet
    ├── heart_rate.parquet
    ├── resting_hr.parquet
    ├── active_energy.parquet
    ├── basal_energy.parquet
    ├── distance_walk.parquet
    ├── distance_cycling.parquet
    ├── flights_climbed.parquet
    ├── sleep.parquet
    ├── body_mass.parquet
    ├── bmi.parquet
    ├── body_fat.parquet
    ├── lean_body_mass.parquet
    ├── walking_speed.parquet
    ├── walking_step_length.parquet
    ├── walking_double_support.parquet
    ├── walking_asymmetry.parquet
    ├── walking_steadiness.parquet
    ├── headphone_audio.parquet
    ├── dietary_energy.parquet
    ├── dietary_protein.parquet
    ├── dietary_carbs.parquet
    ├── dietary_fat.parquet
    ├── workouts.parquet
    └── me.parquet
```

**NO copiar:** `.venv/`, `__pycache__/`, `exportación.xml`

---

## Comando rsync desde el Mac

```bash
rsync -av --exclude='.venv' --exclude='__pycache__' \
  /Users/ESCabellFr/Personal/apple_health/apple_health_mcp/ \
  pi@<IP_RASPBERRY>:~/apple_health_mcp/
```

---

## Setup en el Raspberry (una sola vez)

```bash
cd ~/apple_health_mcp
python3 -m venv .venv
.venv/bin/pip install "mcp[cli]" pandas pyarrow lxml
```

---

## Configuración en VS Code (mcp.json del cliente que use la Raspberry)

```json
{
  "servers": {
    "apple-health": {
      "type": "stdio",
      "command": "/home/pi/apple_health_mcp/.venv/bin/python",
      "args": ["/home/pi/apple_health_mcp/server.py"],
      "env": {
        "APPLE_HEALTH_DATA_DIR": "/home/pi/apple_health_mcp/data"
      }
    }
  }
}
```

> Ajusta `/home/pi/` por el home real del usuario en el Raspberry.

---

## Herramientas MCP disponibles

| Herramienta | Descripción |
|---|---|
| `health_summary` | Resumen de todos los datos disponibles |
| `get_steps` | Pasos diarios |
| `get_heart_rate` | Frecuencia cardíaca (mean/min/max por día) |
| `get_resting_heart_rate` | FC en reposo |
| `get_sleep` | Análisis de sueño por fases (Core/Deep/REM) |
| `get_workouts` | Sesiones de ejercicio, filtrable por tipo |
| `get_body_metrics` | Peso, BMI, % grasa, masa magra |
| `get_activity_energy` | Energía activa/basal, distancia, pisos |
| `get_nutrition` | Calorías, proteína, carbos, grasa |
| `query_health_data` | Consulta genérica para cualquier métrica |

Todos los tools aceptan `start_date` / `end_date` en formato `YYYY-MM-DD`.

---

## Actualizar datos (cuando exportes nuevo XML de Apple Health)

1. En el **Mac**: coloca el nuevo `exportación.xml` en `apple_health_export/`
2. En el **Mac**: ejecuta el preprocesado (~44s)
   ```bash
   cd apple_health_mcp
   .venv/bin/python preprocess.py
   ```
3. Sincroniza solo la carpeta `data/` al Raspberry:
   ```bash
   rsync -av /Users/ESCabellFr/Personal/apple_health/apple_health_mcp/data/ \
     pi@<IP_RASPBERRY>:~/apple_health_mcp/data/
   ```
4. Reinicia el servidor MCP en VS Code: **MCP: Restart Server → apple-health**
