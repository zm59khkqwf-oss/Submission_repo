# Medical IoT Data Pipeline | End-to-End Execution Flow

The assessment is organized into modular components that define a real data pipeline. Each part can run independently, but together they represent the flow from raw ingestion to model lifecycle automation.


1. **Run ingestion (Part A)**
   

2. **Load cleaned data (Part B)**

3. **Run analytics query (Part C)**

4. **Compile ML pipeline (Part D)**

Sequence: **ingest → store → analyze → operationalize**.




## Part A — Ingestion & Cleaning (`code/ingest.py`)

### What it does

`ingest.py` reads raw ICU sensor events (JSONL), validates and cleans each record, and writes a clean dataset.

**Input:** `data/vitals_raw.txt`
**Output:** `data/vitals_clean.jsonl`

### How to run

```bash
pip install python-dateutil
python code/ingest.py
```

Verify output:

```bash
head -n 3 data/vitals_clean.jsonl
```

### Output

JSONL file with one cleaned event per line:

```json
{"event_timestamp":"2026-01-27T13:50:50.771629Z","sensor_id":"icu-monitor-004","heart_rate":70.5,"body_temperature":37.07,"spO2":97,"battery_level":41}
```


## Part B — Bigtable Loader (Local Emulator)

This loads the cleaned vitals dataset into a local Bigtable emulator using the schema defined for the real time dashboard.

### Start emulator

```bash
gcloud beta emulators bigtable start --host-port=localhost:8086
```

Leave this terminal running.

### Configure environment

Open a new terminal:

```bash
export BIGTABLE_EMULATOR_HOST=localhost:8086
export GOOGLE_CLOUD_PROJECT=demo-project
```

### Install dependency

```bash
python -m pip install google-cloud-bigtable
```

### Run loader

From the repository root:

```bash
python code/bigtable_load.py
```

### Expected output

```
[info] table=icu_vitals_hot created=True/False
[done] written=XXXX skipped=0 elapsed=XX.Xs
```

This confirms emulator connection, schema creation, and successful data ingestion.




## Part C — BigQuery Analytics (`sql/analytical_query.sql`)

This stage loads the cleaned vitals dataset into BigQuery to support historical analytics. 
Keeping analytics in BigQuery allows large-scale queries and model preparation without affecting dashboard reads, ensuring that operational performance remains stable.


The cleaned dataset (`data/vitals_clean.jsonl`) was uploaded into a BigQuery Sandbox table using the Google Cloud Console. The SQL query in `sql/analytical_query.sql` was executed and validated directly in the BigQuery editor to confirm correct behavior and results.



## Part D — Vertex AI MLOps Pipeline (`code/vertex_pipeline.py`)

### What it does

`vertex_pipeline.py` defines a Vertex AI / Kubeflow pipeline (dry run) that automates:

**BigQuery → Train → Register → Deploy**

It extracts cleaned vitals from BigQuery, trains a simple sklearn modell (synthetic label for this assessment), registers the model, and defines deployment to a Vertex endpoint.

---

### Configuration

Verify identifiers inside the script:

* `Project_id` — GCP project
* `region` — Vertex AI region
* `Bucket_name` — artifact bucket placeholder
* `BQ_SOURCE_TABLE` — cleaned vitals table

---

### How to run (dry run)

Install dependency:

```bash
pip install kfp
```

Compile the pipeline:

```bash
python code/vertex_pipeline.py
```

This produces:

```
septic_shock_pipeline.json
```

The JSON file is the compiled pipeline specification required for submission.

---

### Pipeline flow

```text
BigQuery → Extract → Train → Register → Deploy
```












