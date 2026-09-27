"""Provision a large synthetic archive, then time only public API requests."""

import json
from pathlib import Path
import time
from werkzeug.security import generate_password_hash
from hoanboy.app import create_app
from hoanboy.mapping import normalize
from test_api import measurement


def test_search_and_patient_page_under_two_seconds_at_target_volume(tmp_path):
    app = create_app(tmp_path, generate_password_hash("synthetic-password"))
    # Fixture provisioning is deliberately outside the timed seam. No production
    # bulk-patient import or test-only endpoint is added to the application.
    store = app.extensions["store"]
    raw = measurement(age="30", height="170")
    metrics = json.dumps(normalize(raw, {}))
    with store.connect() as db:
        db.executemany(
            "INSERT INTO patients(id,mrn,name,phone,updated_at) VALUES(?,?,?,?,?)",
            [
                (i, f"{i:06}", f"Synthetic {i}", f"test-{i}", "2026-09-27")
                for i in range(1, 1001)
            ],
        )
        db.executemany(
            """INSERT INTO measurements(device,source_key,digest,raw,source_schema,source_row,captured_at,
                       source_time,sort_time,clock_status,metrics,mapping_version,patient_id)
                       VALUES('synthetic',?,?,?,'[]','[]','2026-09-27',?,?,'unverified',?,'candidate-1',?)""",
            [
                (
                    str(i),
                    str(i),
                    json.dumps(raw),
                    f"2026-09-{i % 20 + 1:02} 10:00:00",
                    f"2026-09-{i % 20 + 1:02}T10:00:00",
                    metrics,
                    (i // 20) + 1,
                )
                for i in range(20000)
            ],
        )
    client = app.test_client()
    client.post("/api/login", json={"password": "synthetic-password"})
    measurements = {}
    for route in ("/api/patients?q=000500", "/api/patients/500"):
        assert client.get(route).status_code == 200
        samples = []
        for _ in range(5):
            start = time.perf_counter()
            response = client.get(route)
            samples.append(time.perf_counter() - start)
            assert response.status_code == 200
        assert max(samples) < 2
        measurements[route] = dict(max_seconds=max(samples), samples_seconds=samples)
    assert len(client.get("/api/patients/500").json["measurements"]) == 20
    Path("test-results").mkdir(exist_ok=True)
    Path("test-results/performance.json").write_text(
        json.dumps(
            dict(patients=1000, measurements=20000, results=measurements), indent=2
        )
    )
