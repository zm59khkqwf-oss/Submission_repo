# ARCHITECTURE — Pipeline Overview

## Overview

The goal is to design a robust backend pipeline for a critical ICU patient-monitoring system that ingests raw streaming vitals, validates and normalizes them, and supports two needs:

- **Real-time dashboarding** — low-latency lookups such as “last hour of vitals for Sensor X”
- **Long-term analytics & ML** — historical queries and a septic-shock risk workflow

This architecture document is organized into 3 main sections: a high level overview of the end-to-end pipeline, Part A ingestion and data cleaning logic, and Part D Vertex AI workflow. It also addresses the key documentation prompts from the assessment. The Bigtable and BigQuery components (Parts B and C) are documented separately in `design_docs/SCHEMA_DEFENSE.md`, as required.


## Pipeline Steps

1. **Ingest (validate → normalize → clean dataset)**  
2. **Bigtable (real-time “last hour per patient”)**  
3. **BigQuery (historical analytics + alerts)**  
4. **Vertex AI (pipeline compile: train + register + deploy)**

---
## End-to-End Architecture Diagram

```text
┌──────────────┐     ┌──────────────────────┐
│ Raw JSONL    │ --> │ ingest.py            │
│ sensor data  │     │ validate + clean     │
└──────────────┘     └───────────┬──────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 │                               │
        ┌────────v────────-┐             ┌────────v────────-┐
        │ Bigtable         │             │ BigQuery         │
        │ real-time lookup │             │ analytics        │
        └────────┬────────-┘             └────────┬────────-┘
                 │                               │
                 │                               v
                 │                 ┌──────────────────────────┐
                 │                 │ Vertex AI pipeline       │
                 │                 │ Train → Register → Deploy│
                 │                 └──────────────────────────┘
```

---

## Ingestion Steps

Each incoming event is treated as untrusted sensor data and passes through a deterministic validation pipeline:

1. Receive raw data JSON line  
2. Parse JSON structure  
3. Validate required schema fields  
4. Parse timestamps and numeric values  
5. Apply cleaning logic on vitals
6. Normalize formats (UTC timestamps, numeric casting)  
7. Emit trusted JSONL output

---

## Ingestion Flow Diagram

```text
Raw sensor event
        |
        v
Parse JSON?
  ├─ No  → DROP
  └─ Yes
        |
        v
Required fields present?
  ├─ No  → DROP
  └─ Yes
        |
        v
Timestamp valid & not future?
  ├─ No  → DROP
  └─ Yes
        |
        v
heart_rate null / invalid?
  ├─ Yes → DROP
  └─ No
        |
        v
temperature invalid or outside bounds?
  ├─ Yes → DROP
  └─ No
        |
        v
Normalize → EMIT clean JSONL
```

## Cleaning Logic for Vitals

The ingestion boundary applies strict validation to prevent corrupted data values from polluting downstream systems.

### Heart Rate (HR)

Rules:

- Missing (`null`) HR → drop record  
- Non-numeric HR → drop record  

Heart rate is a primary physiological signal. Allowing null or corrupted HR values could hide deterioration or introduce ambiguity into analytics. 

---

### Body Temperature
Temperature is treated as body temperature. Without additional metadata a conservative physiological envelope is enforced, and values outside this range are considered impossible and treated as invalid data.

- Missing (`null`) temperature → drop record  
- Non-numeric temperature → drop record  
- Physiologically impossible temperature → drop record  

Practical envelope enforced:

```
25 °C < temperature < 45 °C
```

Values outside this range are treated as sensor glitches or invalid data.

---


## Timestamp

Rules:

- Invalid ISO timestamp → drop record  
- Future timestamp → drop record  
- Valid timestamps normalized to UTC  

This ensures deterministic ordering and avoids temporal anomalies.

---

### Sensor Identifier

Sensor IDs must be present and non-empty after trimming whitespace. Invalid identifiers result in record rejection.

---

### Optional Fields

SpO₂ and battery level are forwarded without strict validation. These fields are non-critical to ingestion safety and may require context-specific interpretation later.

---


**"If a heart rate is null, why did you choose to drop the row versus
impute it? What are the clinical risks of your choice?"**

Null heart rate values are dropped at ingestion rather than imputed. Heart rate is a primary clinical signal used in alerting and clinical monitoring, and synthesizing a value without temporal or clinical context would introduce false certainty into later monitoring and analytics. This could mask sensor failures or true patient deterioration, creating misleading trends or alerts.
The ingestion layer prioritizes data integrity over completeness, ensuring that only confirmed physiological measurements enter the system. Any imputation is intentionally deferred to workflows where uncertainty can be modeled explicitly.

---


## Vertex AI — ML Pipeline (Part D)

### Purpose
   
This pipeline automates the path from cleaned data stored in BigQuery to a deployed model endpoint that predicts **Septic Shock Risk**. The goal is to demonstrate an end-to-end ML workflow using the Vertex AI SDK, focusing on pipeline structure rather than model complexity. The implementation is a dry run: a simple Logistic Regression (sklearn) model is used to illustrate orchestration, artifact registration,m and deployment.

### Pipeline Architecture

BigQuery → Extract → Train → Register → Deploy

- **BigQuery**: source of cleaned vitals data (`icu_analytics.vitals_clean`)  
- **Extract**: reads the table and materializes a `Dataset` artifact  
- **Train**: trains a logistic regression (sklearn) model and outputs a `Model` artifact  
- **Register**: uploads the model artifact to Vertex AI Model Registry (versioned)  
- **Deploy**: deploys the registered model to a Vertex Endpoint for online serving

The dataset has no septic-shock label, so risk column is synthetic and used only to demonstrate the pipeline wiring

## Drift Feedback Loop 

**If model drift detection triggers an alert in production, what automated steps should follow?**

In production, the deployed model is continuously monitored for drift, meaning changes in incoming data or prediction behavior that cause the model to perform differently than expected. Such drift indicates that the model may no longer reflect current operating conditions and should be reevaluated.
When drift is detected, the pipeline automatically captures diagnostic evidence, including drift metrics and recent prediction samples, and raises an alert.

A retraining job is then triggered using the most recent dataset from BigQuery. The resulting candidate model is evaluated against predefined validation gates to ensure it meets performance and stability requirements.
Only models that pass validation are rolled out using a controlled deployment strategy. 

After deployment, monitoring resumes on the updated model, completing the feedback loop. This architecture allows the system to adapt to changing data conditions while preventing unsafe or unvalidated models from replacing the production version.

```text
BigQuery → Train → Register → Deploy → Serve → Monitor
                                ▲                │
                                │                │
                                └──── Retrain ◄── Drift detected

```
In more details: 

```text
BigQuery (clean vitals/features)
          → Train (sklearn model)
          → Register (Model Registry)
          → Deploy (Endpoint)
          → Serve (predictions)
          → Monitor (drift metrics)
                        │
                        ▼
                 Drift detected?
                  │          │
                 no          yes
                  │           ▼
                  │   Capture evidence + alert
                  │           ↓
                  │   Retrain (fresh BQ window)
                  │           ↓
                  │   Validate (quality gates)
                  │           ↓
                  └──── Continue ─── Rollout ─→ Deploy

```










