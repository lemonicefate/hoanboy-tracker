from hoanboy.app import create_app
from werkzeug.security import generate_password_hash
import pytest


def snapshot(*records):
    columns = list(dict.fromkeys(k for r in records for k in r))
    return {
        "isSuccessful": True,
        "isSelectQuery": True,
        "tableInfos": [{"title": k, "isPrimary": k == "uid"} for k in columns],
        "rows": [
            [{"value": r.get(k), "dataType": "text"} for k in columns] for r in records
        ],
    }


def measurement(uid="1", time="2026-09-27 10:00:00", weight="70", **extra):
    return dict(
        uid=uid,
        time=time,
        username="synthetic-source",
        bhWeightKg=weight,
        bhBMI="22",
        bhBodyFatRate="20",
        **extra,
    )


@pytest.fixture
def api(tmp_path):
    state = {"snapshot": snapshot(measurement())}

    def reader():
        if isinstance(state["snapshot"], Exception):
            raise state["snapshot"]
        return state["snapshot"]

    app = create_app(
        data_dir=tmp_path,
        password_hash=generate_password_hash("synthetic-password"),
        reader=reader,
    )
    client = app.test_client()
    result = client.post("/api/login", json={"password": "synthetic-password"})
    client.environ_base["HTTP_X_CSRF_TOKEN"] = result.json["csrf"]
    return client, state, tmp_path


def test_login_and_patient_identity_survive_restart(tmp_path):
    options = dict(
        data_dir=tmp_path, password_hash=generate_password_hash("synthetic-password")
    )
    app = create_app(**options)
    client = app.test_client()
    assert client.get("/api/patients").status_code == 401
    assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
    login = client.post("/api/login", json={"password": "synthetic-password"})
    headers = {"X-CSRF-Token": login.json["csrf"]}
    patient = client.post(
        "/api/patients",
        json={"mrn": "001", "name": "虛構甲", "phone": "shared"},
        headers=headers,
    )
    assert patient.status_code == 201
    assert (
        client.post(
            "/api/patients", json={"mrn": "001", "name": "duplicate"}, headers=headers
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/patients",
            json={"mrn": "002", "name": "虛構乙", "phone": "shared"},
            headers=headers,
        ).status_code
        == 201
    )
    restarted = create_app(**options).test_client()
    restarted.post("/api/login", json={"password": "synthetic-password"})
    found = restarted.get("/api/patients?q=shared").json
    assert [p["mrn"] for p in found] == ["001", "002"]
    assert (
        client.post("/api/patients", json={"mrn": "003", "name": "no csrf"}).status_code
        == 403
    )


def test_sync_is_idempotent_preserves_versions_and_never_assigns_changed_keys(api):
    client, state, _ = api
    first = client.post("/api/sync").json
    assert first["added"] == 1
    original = client.get("/api/measurements").json[0]
    assert original["metrics"]["weight"]["value"] == 70
    assert original["metrics"]["weight"]["status"] == "unverified"
    assert original["source_timezone"] is None
    assert client.post("/api/sync").json["unchanged"] == 1
    patient = client.post("/api/patients", json={"mrn": "0001", "name": "虛構甲"}).json
    assert (
        client.post(
            f"/api/measurements/{original['id']}/assignment",
            json={"patient_id": patient["id"]},
        ).status_code
        == 200
    )
    state["snapshot"] = snapshot(measurement(weight="71"))
    assert client.post("/api/sync").json["updated"] == 1
    changed = client.get("/api/measurements").json[0]
    assert changed["id"] != original["id"]
    assert changed["patient_id"] is None
    assert changed["changed_from"] == original["id"]
    assert (
        client.get(f"/api/measurements/{original['id']}").json["metrics"]["weight"][
            "value"
        ]
        == 70
    )
    assert (
        client.get(f"/api/patients/{patient['id']}").json["measurements"][0]["id"]
        == original["id"]
    )
    assert client.get("/api/sync").json["last_success"]


def test_failed_sync_leaves_archive_intact_and_reports_failure(api):
    client, state, _ = api
    client.post("/api/sync")
    good_time = client.get("/api/sync").json["last_success"]
    broken = snapshot(measurement("2"))
    broken["rows"][0].pop()
    state["snapshot"] = broken
    assert client.post("/api/sync").status_code == 502
    assert len(client.get("/api/measurements").json) == 1
    state["snapshot"] = TimeoutError("secret device details")
    result = client.post("/api/sync")
    assert result.status_code == 502
    assert "secret" not in result.text
    assert client.get("/api/sync").json["last_success"] == good_time


def test_filing_corrections_ignore_and_candidate_phone_never_merge_patients(api):
    client, _, _ = api
    patients = [
        client.post(
            "/api/patients",
            json={"mrn": str(i), "name": f"虛構{i}", "phone": "synthetic-source"},
        ).json
        for i in range(2)
    ]
    client.post("/api/sync")
    mid = client.get("/api/measurements").json[0]["id"]
    assert len(client.get(f"/api/measurements/{mid}").json["candidates"]) == 2
    client.post(f"/api/measurements/{mid}/ignore")
    assert client.get("/api/measurements").json == []
    assert len(client.get("/api/measurements?state=ignored").json) == 1
    client.post(f"/api/measurements/{mid}/restore")
    for patient in patients:
        assert (
            client.post(
                f"/api/measurements/{mid}/assignment",
                json={"patient_id": patient["id"]},
            ).status_code
            == 200
        )
    assert client.get(f"/api/patients/{patients[0]['id']}").json["measurements"] == []
    assert (
        len(client.get(f"/api/patients/{patients[1]['id']}").json["measurements"]) == 1
    )
    assert client.post(f"/api/measurements/{mid}/ignore").status_code == 400
    client.post(f"/api/measurements/{mid}/assignment", json={"patient_id": None})
    events = client.get(f"/api/measurements/{mid}").json["events"]
    assert events[-2]["before_patient"] == patients[0]["id"]
    assert events[-2]["after_patient"] == patients[1]["id"]
    assert events[-1]["after_patient"] is None
    assert all(e["actor"] and e["at"] for e in events)


def test_verified_trends_preserve_same_day_retests_and_missing_points(tmp_path):
    records = [
        measurement("1", "2026-09-27 09:00:00", "70"),
        measurement("2", "2026-09-27 10:00:00", ""),
        measurement("3", "2026-09-27 11:00:00", "68"),
    ]
    client = create_app(
        tmp_path,
        generate_password_hash("synthetic-password"),
        reader=lambda: snapshot(*records),
        verified={
            "bhWeightKg": "synthetic fixture contract",
            "bhBodyFatRate": "synthetic fixture contract",
        },
    ).test_client()
    client.environ_base["HTTP_X_CSRF_TOKEN"] = client.post(
        "/api/login", json={"password": "synthetic-password"}
    ).json["csrf"]
    pid = client.post("/api/patients", json={"mrn": "001", "name": "虛構"}).json["id"]
    client.post("/api/sync")
    for m in client.get("/api/measurements").json:
        client.post(f"/api/measurements/{m['id']}/assignment", json={"patient_id": pid})
    result = client.get(f"/api/patients/{pid}").json
    assert [m["source_key"] for m in result["measurements"]] == ["3", "2", "1"]
    assert [p["value"] for p in result["trends"]["weight"]] == [70, None, 68]
    assert result["differences"]["weight"] == {"first": -2, "previous": None}
    assert result["trends"]["weight"][1]["status"] == "missing"


def test_unverified_values_do_not_become_formal_trends(api):
    client, _, _ = api
    pid = client.post("/api/patients", json={"mrn": "001", "name": "虛構"}).json["id"]
    client.post("/api/sync")
    mid = client.get("/api/measurements").json[0]["id"]
    client.post(f"/api/measurements/{mid}/assignment", json={"patient_id": pid})
    assert (
        client.get(f"/api/patients/{pid}").json["trends"]["weight"][0]["value"] is None
    )


def test_reports_are_offline_immutable_and_invalidated_when_history_is_refiled(api):
    client, state, _ = api
    pid = client.post("/api/patients", json={"mrn": "001", "name": "虛構甲"}).json["id"]
    state["snapshot"] = snapshot(
        measurement("1", "2026-09-26 10:00:00", bhWHR="0.85", bhSkeletalMuscleKg="25"),
        measurement("2", "2026-09-27 10:00:00", "69"),
    )
    client.post("/api/sync")
    for mid in (1, 2):
        client.post(f"/api/measurements/{mid}/assignment", json={"patient_id": pid})
    report = client.post("/api/measurements/2/reports").json
    assert report["status"] == "draft"
    html = client.get(f"/api/reports/{report['id']}/html").text
    assert "虛構甲" in html and "001" in html
    assert all(f'data-section="{i}"' in html for i in range(1, 11))
    assert "未驗證" in html
    assert "https://" not in html and "http://" not in html
    client.put(f"/api/patients/{pid}", json={"mrn": "001", "name": "改名"})
    state["snapshot"] = snapshot(measurement("3", "2026-09-28 10:00:00", "68"))
    client.post("/api/sync")
    client.post("/api/measurements/3/assignment", json={"patient_id": pid})
    assert client.get(f"/api/reports/{report['id']}/html").text == html
    # Refiling any history included in the report invalidates that saved report.
    client.post("/api/measurements/1/assignment", json={"patient_id": None})
    assert client.get(f"/api/reports/{report['id']}/html").status_code == 409
    replacement = client.post("/api/measurements/2/reports").json
    assert replacement["id"] != report["id"]
    assert "改名" in client.get(f"/api/reports/{replacement['id']}/html").text
    assert client.get(f"/api/reports/{report['id']}").json["invalidated_at"]


def test_backup_restores_patients_raw_data_assignments_and_saved_report(api):
    client, _, path = api
    pid = client.post("/api/patients", json={"mrn": "001", "name": "虛構"}).json["id"]
    client.post("/api/sync")
    client.post("/api/measurements/1/assignment", json={"patient_id": pid})
    rid = client.post("/api/measurements/1/reports").json["id"]
    report_html = client.get(f"/api/reports/{rid}/html").text
    backup = client.post("/api/backups").json
    assert backup["name"].endswith(".sqlite3")
    isolated = client.post(f"/api/backups/{backup['name']}/restore").json
    assert isolated["counts"] == {
        "patients": 1,
        "measurements": 1,
        "assignment_events": 1,
        "reports": 1,
    }
    restored = create_app(
        path / "restores" / isolated["id"], generate_password_hash("restored-password")
    ).test_client()
    restored.post("/api/login", json={"password": "restored-password"})
    assert restored.get(f"/api/patients/{pid}").json["patient"]["mrn"] == "001"
    assert (
        restored.get("/api/measurements/1").json["raw"]["username"]
        == "synthetic-source"
    )
    assert restored.get(f"/api/reports/{rid}/html").text == report_html
    assert client.get("/api/backups").json["automatic"]
    # A corrupt backup must not be reported as successfully restored.
    (path / "backups" / backup["name"]).write_bytes(b"broken")
    assert client.post(f"/api/backups/{backup['name']}/restore").status_code == 400


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate-column",
        "duplicate-key",
        "missing-column",
        "not-select",
        "invalid-cell",
    ],
)
def test_malformed_snapshots_are_rejected_atomically(api, mutation):
    client, state, _ = api
    client.post("/api/sync")
    payload = snapshot(measurement("2"), measurement("3"))
    if mutation == "duplicate-column":
        payload["tableInfos"][1]["title"] = "uid"
    elif mutation == "duplicate-key":
        payload["rows"][1][0]["value"] = "2"
    elif mutation == "missing-column":
        payload["tableInfos"][0]["title"] = "not_uid"
    elif mutation == "not-select":
        payload["isSelectQuery"] = False
    else:
        payload["rows"][1][2] = {"invalid": True}
    state["snapshot"] = payload
    assert client.post("/api/sync").status_code == 502
    assert len(client.get("/api/measurements").json) == 1


def test_reordered_schema_unknown_values_and_invalid_numbers_survive(api):
    client, state, _ = api
    raw = measurement(weight="NaN", unknown="original", bhWHR="0.85")
    state["snapshot"] = snapshot(dict(reversed(list(raw.items()))))
    client.post("/api/sync")
    m = client.get("/api/measurements/1").json
    assert m["metrics"]["weight"]["value"] is None
    assert m["metrics"]["weight"]["status"] == "invalid"
    assert m["metrics"]["whr"]["value"] == 0.85
    assert m["raw"]["unknown"] == "original"
    assert m["source_row"][0] == {"value": "0.85", "dataType": "text"}


def test_sync_rejects_overlap_and_exposes_running_state(tmp_path):
    import threading

    started, release = threading.Event(), threading.Event()

    def reader():
        started.set()
        assert release.wait(5)
        return snapshot(measurement())

    app = create_app(
        tmp_path, generate_password_hash("synthetic-password"), reader=reader
    )
    clients = [app.test_client(), app.test_client()]
    for client in clients:
        client.environ_base["HTTP_X_CSRF_TOKEN"] = client.post(
            "/api/login", json={"password": "synthetic-password"}
        ).json["csrf"]
    results = []
    thread = threading.Thread(
        target=lambda: results.append(clients[0].post("/api/sync"))
    )
    thread.start()
    try:
        assert started.wait(3)
        assert clients[1].get("/api/sync").json["running"]
        assert clients[1].post("/api/sync").status_code == 409
    finally:
        release.set()
        thread.join(5)
    assert results[0].status_code == 200


def test_backup_failure_is_visible_without_undoing_saved_patient(api):
    client, _, path = api
    (path / "backups").write_text("not a directory")
    result = client.post("/api/patients", json={"mrn": "001", "name": "虛構"})
    assert result.status_code == 201
    assert result.headers["X-Backup-Failed"] == "1"
    assert client.get("/api/backups").json["error"]
    assert client.get("/api/patients").json[0]["mrn"] == "001"
    assert client.post("/api/backups").status_code == 503


def test_host_origin_and_unauthenticated_report_access_are_denied(api):
    client, _, _ = api
    assert (
        client.get("/api/patients", headers={"Host": "attacker.example"}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/sync", headers={"Origin": "https://attacker.example"}
        ).status_code
        == 403
    )
    client.post("/api/logout")
    assert client.get("/api/reports/1/html").status_code == 401


def test_automatic_backup_keeps_latest_thirty_days_and_preserves_manual(api):
    from datetime import date, timedelta

    client, _, path = api
    manual = client.post("/api/backups").json["name"]
    directory = path / "backups"
    for i in range(1, 35):
        name = "auto-" + (date.today() - timedelta(days=i)).isoformat()
        (directory / (name + ".sqlite3")).write_bytes((directory / manual).read_bytes())
        (directory / (name + ".json")).write_bytes(
            (directory / manual).with_suffix(".json").read_bytes()
        )
    client.post("/api/patients", json={"mrn": "001", "name": "Synthetic"})
    files = client.get("/api/backups").json["files"]
    assert len([f for f in files if f["name"].startswith("auto-")]) == 30
    assert any(f["name"] == manual for f in files)


def test_explicit_revalidation_updates_history_without_rewriting_source_or_saved_reports(
    api,
):
    client, _, path = api
    client.post("/api/patients", json={"mrn": "001", "name": "Synthetic"})
    client.post("/api/sync")
    client.post("/api/measurements/1/assignment", json={"patient_id": 1})
    report = client.post("/api/measurements/1/reports").json
    original_html = client.get(f"/api/reports/{report['id']}/html").text
    original = client.get("/api/measurements/1").json
    verified = create_app(
        path,
        generate_password_hash("synthetic-password"),
        verified={"bhWeightKg": "Synthetic reviewed evidence"},
    ).test_client()
    verified.environ_base["HTTP_X_CSRF_TOKEN"] = verified.post(
        "/api/login", json={"password": "synthetic-password"}
    ).json["csrf"]
    # Merely starting with new evidence must not silently rewrite history.
    assert verified.get("/api/patients/1").json["trends"]["weight"][0]["value"] is None
    response = verified.post("/api/measurements/1/revalidate")
    assert response.status_code == 200
    assert response.json["changed"]
    assert verified.get("/api/patients/1").json["trends"]["weight"][0]["value"] == 70
    result = verified.get("/api/measurements/1").json
    assert result["raw"] == original["raw"]
    assert result["source_row"] == original["source_row"]
    assert len(result["normalizations"]) == 2
    assert result["normalizations"][0]["metrics"]["weight"]["status"] == "unverified"
    assert result["normalizations"][1]["metrics"]["weight"]["status"] == "verified"
    assert verified.get(f"/api/reports/{report['id']}/html").text == original_html
    replacement = verified.post("/api/measurements/1/reports").json
    assert replacement["id"] != report["id"]
    assert not verified.post("/api/measurements/1/revalidate").json["changed"]
