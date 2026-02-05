# Part B — Bigtable Hot Storage (Real-Time Dashboard)

## Objective

Design a Bigtable schema optimized for the real-time dashboard query:

> **“Get all vitals for Patient/Monitor X for the last 1 hour.”**

We are assuming that each ICU monitor corresponds to a patient stream, so `sensor_id` is treated as the patient identifier.

The schema prioritizes:

- Low latency recent window reads  
- Efficient per monitor time-series access  

---

## Row Key Strategy

### Implemented Row Key


Bigtable stores rows lexicographically by row key. The structure is designed to align physical storage with the dominant dashboard access pattern.

#### Monitor grouping

Placing `sensor_id` first ensures all readings for a given patient/monitor are stored contiguously. This enables efficient prefix and range scans scoped to a single monitor without scanning unrelated rows.

#### Reverse time ordering

The timestamp is stored as:

`reverse_timestamp = MAX_TS - event_timestamp`



This causes newer events to sort before older ones within the monitor’s key range. Dashboard queries requesting the last hour therefore start at the newest readings.

---

## Column Family Design

the design is as the following:
 
### `v` — Vitals
- `hr` (heart rate)  
- `temp` (body temperature)  
- `spo2`(Oxygen Saturation)

Stores dashboard-critical physiological metrics.

### `d` — Device
- `battery`

Captures monitor state information.

### `m` — Metadata
- `sensor_id`  
- `event_timestamp`

---

## Read Path Optimization

The dashboard query:

> *“Get all vitals for Monitor X for the last 1 hour”*

is executed as a bounded range scan:

`sensor_id#rev(now) → sensor_id#rev(now - 1h)`

Because rows are ordered newest → oldest:

- the scan begins at recent data  
- stops once the one hour boundary is reached.

---

## Hotspotting

For the current dataset (~10 monitors), the implemented row key  
`sensor_id#reverse_timestamp` is appropriate. Write volume is low, and grouping rows by `sensor_id` enables fast single-sensor range scans without stressing Bigtable tablets. At this scale, hotspotting is unlikely because ingestion is small and naturally distributed.

This row key is also the best structure for the dashboard query (“Patient X last 1 hour”), since it keeps all readings for a sensor contiguous and ordered from newest to oldest. In many cases it will scale well because writes are spread across many sensors.

However, monitor IDs follow a patterned format (`icu-monitor-###`), and Bigtable stores rows lexicographically. Tablets own contiguous key ranges, so a burst of ~10,000 concurrent writes can still overload a subset of tablets if adjacent IDs receive traffic at the same time. This is a potential hotspot scenario under worst case ingestion bursts.

If hotspotting is observed or must be prevented at higher scale, the row key can be extended to:

```
salt#sensor_id#reverse_timestamp
```

where:

```
salt = hash(sensor_id) % N
```

This extension introduces a tradeoff: the dashboard query is no longer a single range scan. Instead, the system performs a small fan-out across salt buckets and merges results. This slightly increases read complexity, but it protects write performance during burst ingestion.








# BigQuery — Part C (Analytics & Warehousing)

This stwp stores the cleaned vitals data in BigQuery to enable analytical queries over time series sensor data. The cleaned dataset is loaded into a BigQuery Sandbox table via the Google Cloud Console and used to run the sustained-alert analytics query in `sql/analytical_query.sql`.

---


## Optimizing BigQuery at ~1 Petabyte

### Performance Objective at PB Scale
At petabyte scale, the dominant risk is over data scanning. Query cost and latency are driven by how much data BigQuery must read, not by compute complexity alone. The storage layout should therefore minimize unnecessary scans by enabling BigQuery to eliminate irrelevant data as early as possible in query execution.

This optimization relies on:

   - Partition = filter out irrelevant date ranges early
   - Cluster = reduce the amount of data read within the remaining partitions

Together, these mechanisms allow large analytical queries to operate efficiently even as the dataset grows.

### Time-Based Partitioning Strategy
Proposed solution: partition by date `event_timestamp`
The table is partitioned by event date derived from event_timestamp. Partitioning by event date aligns the physical storage layout with this dominant access pattern.
When a query specifies a time filter, BigQuery can immediately exclude partitions outside the requested window. This dramatically reduces the amount of data scanned.

Daily partitions for example, provide effective pruning without excessive overhead, while keeping retention, ingestion, and historical processing simple to manage.

### Clustering Strategy for Sensor-Level Access 
Proposed solution: `sensor_id + event_timestamp`

Sensor identifiers represent a high-cardinality dimension that appears frequently in filtering. Clustering gather rows belonging to the same sensor inside each partition. When a query targets specific sensors, BigQuery reads only the relevant clustered blocks instead of scanning the entire partition.

Including the `event_timestamp` as a secondary clustering key improves locality for time ordered scans. This is particularly beneficial for rolling window analytics and sequential processing, where queries read contiguous time slices for a given sensor.

#### Sensor-Based Partitioning
Partitioning directly on `sensor_id` would be inappropriate for this case example. Sensor identifiers have very high cardinality, which would create too many partitions, and introduce operational overhead without providing meaningful pruning benefits. Partitioning is better suited to time dimensions, while clustering is the correct mechanism for optimizing reads on high-cardinality identifiers like `sensor_id`.









