# ingest.py: reads raw sensor events (JSONL)validates and cleans them at ingestion time, and writes only safe and normalized events.

import json
from datetime import datetime, timezone
from dateutil import parser as dtparser

INPUT_PATH = "data/vitals_raw.txt"
OUTPUT_PATH = "data/vitals_clean.jsonl"

MAX_TEMP_C = 45.0
MIN_TEMP_C = 25.0

time_now_utc = datetime.now(timezone.utc)
required_fields = ["event_timestamp", "sensor_id", "heart_rate", "body_temperature"]

with open(INPUT_PATH, "r", encoding="utf-8") as inp, open(OUTPUT_PATH, "w", encoding="utf-8") as outp:
    for raw_event in inp:
        raw_event = raw_event.strip()
        if not raw_event:
            continue

        try:
            record = json.loads(raw_event)
        except Exception:
            continue

        if not all(k in record for k in required_fields):
            continue

        try:
            dt = dtparser.isoparse(record["event_timestamp"])
            hr = record["heart_rate"]
            temp = record["body_temperature"]
        except Exception:
            continue

        if hr is None:
            continue
        try:
            hr = float(hr)
        except Exception:
            continue

        if temp is None:
            continue
        try:
            temp = float(temp)
        except Exception:
            continue

        if temp < MIN_TEMP_C or temp > MAX_TEMP_C:
            continue

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        if dt > time_now_utc:
            continue

        sensor_id = str(record["sensor_id"]).strip()
        if not sensor_id:
            continue

        normalized = {
            "event_timestamp": dt.isoformat().replace("+00:00", "Z"),
            "sensor_id": sensor_id,
            "heart_rate": hr,
            "body_temperature": temp,
            "spO2": record.get("spO2"),
            "battery_level": record.get("battery_level"),
        }

        outp.write(json.dumps(normalized) + "\n")


