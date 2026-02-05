
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

from google.cloud import bigtable
from google.cloud.bigtable import column_family

MAX_TS_MICROS = (2**63) - 1


def iso_to_micros(ts: str) -> int:
    if not ts:
        raise ValueError("empty event_timestamp")
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000)


def make_row_key(sensor_id: str, event_micros: int) -> bytes:
    rev = MAX_TS_MICROS - event_micros
    return f"{sensor_id}#{rev:019d}".encode("utf-8")


def require_emulator():
    if not os.environ.get("BIGTABLE_EMULATOR_HOST"):
        raise EnvironmentError(
            "BIGTABLE_EMULATOR_HOST is not set.\n"
            "Start the emulator and export BIGTABLE_EMULATOR_HOST (e.g., localhost:8086)."
        )


def ensure_table(instance, table_id: str):
    table = instance.table(table_id)
    if table.exists():
        return table, False

    families = {
        "v": column_family.MaxVersionsGCRule(1),  # vitals: hr/temp/spo2
        "d": column_family.MaxVersionsGCRule(1),  # device: battery
        "m": column_family.MaxVersionsGCRule(1),  # metadata: ts/sensor_id
    }
    table.create(column_families=families)
    return table, True


def b(x) -> bytes:
    return str(x).encode("utf-8")


def load_jsonl(table, path: str, limit: int | None = None):
    written = skipped = 0
    t0 = time.time()
    batch = table.mutations_batcher(flush_count=1000)

    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            if limit is not None and written >= limit:
                break

            line = line.strip()
            if not line:
                continue

            try:
                rec = json.loads(line)

                sensor_id = rec["sensor_id"]
                ts = rec["event_timestamp"]
                event_micros = iso_to_micros(ts)

                rk = make_row_key(sensor_id, event_micros)
                row = table.direct_row(rk)

                # vitals
                if rec.get("heart_rate") is not None:
                    row.set_cell("v", "hr", b(rec["heart_rate"]))
                if rec.get("body_temperature") is not None:
                    row.set_cell("v", "temp", b(rec["body_temperature"]))
                spo2 = rec.get("spO2", rec.get("spo2"))
                if spo2 is not None:
                    row.set_cell("v", "spo2", b(spo2))

                # device
                if rec.get("battery_level") is not None:
                    row.set_cell("d", "battery", b(rec["battery_level"]))

                # metadata
                row.set_cell("m", "sensor_id", b(sensor_id))
                row.set_cell("m", "event_timestamp", b(ts))

                batch.mutate(row)
                written += 1

            except Exception as e:
                skipped += 1
                print(f"[skip] line={i} error={e}", file=sys.stderr)

    batch.flush()
    print(f"[done] written={written} skipped={skipped} elapsed={time.time()-t0:.1f}s")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "demo-project"))
    p.add_argument("--instance", default=os.getenv("BIGTABLE_INSTANCE", "test-instance"))
    p.add_argument("--table", default=os.getenv("BIGTABLE_TABLE", "icu_vitals_hot"))
    p.add_argument("--input", default=os.getenv("CLEANED_PATH", "data/vitals_clean.jsonl"))
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    require_emulator()

    client = bigtable.Client(project=args.project, admin=True)
    instance = client.instance(args.instance)

    table, created = ensure_table(instance, args.table)
    print(f"[info] table={args.table} created={created}")

    load_jsonl(table, args.input, args.limit)


if __name__ == "__main__":
    main()

