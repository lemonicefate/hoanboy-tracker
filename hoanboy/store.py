from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
 id INTEGER PRIMARY KEY, mrn TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 phone TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS measurements (
 id INTEGER PRIMARY KEY, device TEXT NOT NULL, source_key TEXT NOT NULL,
 digest TEXT NOT NULL, raw TEXT NOT NULL, source_schema TEXT NOT NULL, source_row TEXT NOT NULL,
 captured_at TEXT NOT NULL, source_time TEXT, sort_time TEXT,
 source_timezone TEXT, clock_status TEXT NOT NULL, source_identifier TEXT,
 metrics TEXT NOT NULL, mapping_version TEXT NOT NULL, changed_from INTEGER REFERENCES measurements(id),
 patient_id INTEGER REFERENCES patients(id), ignored INTEGER NOT NULL DEFAULT 0,
 UNIQUE(device,source_key,digest)
);
CREATE INDEX IF NOT EXISTS patient_measurements ON measurements(patient_id,sort_time,id);
CREATE INDEX IF NOT EXISTS pending_measurements ON measurements(patient_id,ignored,id);
CREATE TABLE IF NOT EXISTS assignment_events (
 id INTEGER PRIMARY KEY, measurement_id INTEGER NOT NULL REFERENCES measurements(id),
 before_patient INTEGER REFERENCES patients(id), after_patient INTEGER REFERENCES patients(id),
 action TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_runs (
 id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
 status TEXT NOT NULL, added INTEGER NOT NULL DEFAULT 0, updated INTEGER NOT NULL DEFAULT 0,
 unchanged INTEGER NOT NULL DEFAULT 0, error TEXT
);
CREATE TABLE IF NOT EXISTS reports (
 id INTEGER PRIMARY KEY, measurement_id INTEGER NOT NULL REFERENCES measurements(id),
 patient_id INTEGER NOT NULL REFERENCES patients(id), created_at TEXT NOT NULL,
 template_version TEXT NOT NULL, mapping_version TEXT NOT NULL, status TEXT NOT NULL,
 snapshot TEXT NOT NULL, html TEXT NOT NULL, invalidated_at TEXT
);
CREATE TABLE IF NOT EXISTS report_measurements (
 report_id INTEGER NOT NULL REFERENCES reports(id), measurement_id INTEGER NOT NULL REFERENCES measurements(id),
 PRIMARY KEY(report_id,measurement_id)
);
PRAGMA application_id=1213153614;
PRAGMA user_version=1;
"""


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()
