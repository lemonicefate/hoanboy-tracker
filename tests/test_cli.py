import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from werkzeug.security import generate_password_hash
from hoanboy.app import create_app


def test_restore_activation_refuses_live_server_and_recovers_archive(tmp_path):
    password_hash = generate_password_hash("synthetic-password")
    options = dict(data_dir=tmp_path, password_hash=password_hash)
    client = create_app(**options).test_client()
    client.environ_base["HTTP_X_CSRF_TOKEN"] = client.post(
        "/api/login", json={"password": "synthetic-password"}
    ).json["csrf"]
    client.post("/api/patients", json={"mrn": "001", "name": "Before backup"})
    name = client.post("/api/backups").json["name"]
    restore_id = client.post(f"/api/backups/{name}/restore").json["id"]
    client.put("/api/patients/1", json={"mrn": "001", "name": "After backup"})
    (tmp_path / "config.json").write_text(
        json.dumps(
            dict(
                password_hash=password_hash,
                backup_dir=str(tmp_path / "backups"),
                device_address="192.168.1.102",
                device_id="test",
            )
        )
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = [sys.executable, "-m", "hoanboy", "--data-dir", str(tmp_path)]
    process = subprocess.Popen(
        command + ["serve", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}", timeout=0.3
                ) as response:
                    assert response.status == 200
                    break
            except OSError:
                assert process.poll() is None
                time.sleep(0.05)
        else:
            raise AssertionError("Local server did not start")
        refused = subprocess.run(
            command + ["restore", restore_id], capture_output=True, timeout=5
        )
        assert refused.returncode == 1
    finally:
        process.terminate()
        process.communicate(timeout=5)
    restored = subprocess.run(
        command + ["restore", restore_id], capture_output=True, timeout=5
    )
    assert restored.returncode == 0, restored.stderr
    client = create_app(**options).test_client()
    client.post("/api/login", json={"password": "synthetic-password"})
    assert client.get("/api/patients/1").json["patient"]["name"] == "Before backup"
