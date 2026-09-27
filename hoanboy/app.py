from datetime import datetime, timezone, timedelta
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from typing import Any
from flask import Flask, jsonify, request, session, Response, render_template
import base64
import hashlib
import re
from werkzeug.security import check_password_hash
from werkzeug.exceptions import HTTPException
from hoanboy.store import Store
from hoanboy.device import DeviceReader
from hoanboy.service import Archive, Busy, SyncFailed, measurement
from hoanboy.backup import Backups


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_app(data_dir: Path, password_hash: str, **options: Any) -> Flask:
    data_dir.mkdir(parents=True, exist_ok=True)
    secret_path = data_dir / "session.key"
    try:
        with secret_path.open("x", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=secret_path.read_text(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=16384,
    )
    store = Store(data_dir / "archive.sqlite3")
    app.extensions["store"] = store
    archive = Archive(
        store,
        options.get("reader") or DeviceReader(),
        options.get("device", "hoanboy-370"),
        options.get("verified", {}),
    )
    app.extensions["archive"] = archive
    backups = Backups(
        store, options.get("backup_dir", data_dir / "backups"), data_dir / "restores"
    )
    app.extensions["backups"] = backups
    login_failures: list[float] = []
    login_lock = threading.Lock()

    @app.before_request
    def protect() -> Any:
        if request.host.split(":")[0] not in ("localhost", "127.0.0.1"):
            return jsonify(error="僅允許本機存取"), 403
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin")
            if origin and origin != request.host_url.rstrip("/"):
                return jsonify(error="來源不符"), 403
        if request.path.startswith("/api/") and request.path != "/api/login":
            if not session.get("authenticated"):
                return jsonify(error="請先登入"), 401
            if request.method not in (
                "GET",
                "HEAD",
                "OPTIONS",
            ) and not secrets.compare_digest(
                request.headers.get("X-CSRF-Token", ""), session["csrf"]
            ):
                return jsonify(error="請重新登入後操作"), 403

    @app.after_request
    def headers(response: Any) -> Any:
        if (
            request.method in ("POST", "PUT")
            and response.status_code < 400
            and request.path.startswith("/api/")
            and request.path not in ("/api/login", "/api/logout")
            and not request.path.startswith("/api/backups")
        ):
            backups.automatic()
            if backups.error:
                response.headers["X-Backup-Failed"] = "1"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        )
        if request.path.endswith("/html") and response.status_code == 200:
            styles = re.findall(
                r"<style>(.*?)</style>", response.get_data(as_text=True), re.S
            )
            hashes = " ".join(
                "'sha256-"
                + base64.b64encode(hashlib.sha256(s.encode()).digest()).decode()
                + "'"
                for s in styles
            )
            response.headers["Content-Security-Policy"] = (
                f"default-src 'none'; style-src {hashes}; frame-ancestors 'none'; base-uri 'none'"
            )
        return response

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException) -> Any:
        return jsonify(error="請求格式錯誤"), error.code

    @app.errorhandler(ValueError)
    def invalid(error: ValueError) -> Any:
        return jsonify(error=str(error)), 400

    @app.errorhandler(sqlite3.IntegrityError)
    def conflict(error: sqlite3.IntegrityError) -> Any:
        return jsonify(error="病歷號重複或資料關聯無效"), 409

    @app.errorhandler(sqlite3.OperationalError)
    @app.errorhandler(OSError)
    def storage_failure(error: Exception) -> Any:
        return jsonify(error="本機儲存失敗；請檢查磁碟空間與權限後重試"), 503

    @app.errorhandler(LookupError)
    def missing(error: LookupError) -> Any:
        return jsonify(error=str(error)), 404

    @app.errorhandler(Busy)
    def busy(error: Busy) -> Any:
        return jsonify(error=str(error)), 409

    @app.errorhandler(SyncFailed)
    def sync_failed(error: SyncFailed) -> Any:
        return jsonify(error=str(error)), 502

    @app.post("/api/login")
    def login() -> Any:
        body = request.get_json()
        password = body.get("password", "") if isinstance(body, dict) else ""
        if not isinstance(password, str) or len(password) > 1024:
            return jsonify(error="登入失敗"), 401
        with login_lock:
            login_failures[:] = [x for x in login_failures if x > time.monotonic() - 60]
            if len(login_failures) >= 10:
                return jsonify(error="請稍後再試"), 429
            if not check_password_hash(password_hash, password):
                login_failures.append(time.monotonic())
                return jsonify(error="登入失敗"), 401
            login_failures.clear()
        session.clear()
        session.update(authenticated=True, csrf=secrets.token_hex(32))
        session.permanent = True
        return jsonify(csrf=session["csrf"])

    @app.get("/")
    def index() -> Any:
        return render_template("index.html")

    @app.get("/api/session")
    def current_session() -> Any:
        return jsonify(csrf=session["csrf"])

    @app.post("/api/logout")
    def logout() -> Any:
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/patients")
    def patients() -> Any:
        query = request.args.get("q", "")[:200]
        with store.connect() as db:
            rows = db.execute(
                "SELECT * FROM patients WHERE instr(mrn,?) OR instr(name,?) OR instr(phone,?) ORDER BY mrn LIMIT 100",
                (query, query, query),
            )
            return jsonify([dict(r) for r in rows])

    @app.post("/api/patients")
    def create_patient() -> Any:
        body = patient_input()
        with store.connect() as db:
            cursor = db.execute(
                "INSERT INTO patients(mrn,name,phone,updated_at) VALUES(?,?,?,?)",
                (*body, now()),
            )
            patient = dict(
                db.execute(
                    "SELECT * FROM patients WHERE id=?", (cursor.lastrowid,)
                ).fetchone()
            )
        return jsonify(patient), 201

    @app.put("/api/patients/<int:patient_id>")
    def edit_patient(patient_id: int) -> Any:
        body = patient_input()
        with store.connect() as db:
            if (
                db.execute(
                    "UPDATE patients SET mrn=?,name=?,phone=?,updated_at=? WHERE id=?",
                    (*body, now(), patient_id),
                ).rowcount
                == 0
            ):
                return jsonify(error="找不到病人"), 404
        return jsonify(ok=True)

    @app.get("/api/patients/<int:patient_id>")
    def patient_detail(patient_id: int) -> Any:
        return jsonify(archive.patient(patient_id))

    @app.post("/api/sync")
    def sync() -> Any:
        return jsonify(archive.sync())

    @app.get("/api/sync")
    def sync_status() -> Any:
        return jsonify(archive.sync_status())

    @app.get("/api/measurements")
    def pending() -> Any:
        ignored = request.args.get("state") == "ignored"
        before = request.args.get("before", type=int) or 9223372036854775807
        with store.connect() as db:
            rows = db.execute(
                "SELECT * FROM measurements WHERE patient_id IS NULL AND ignored=? AND id<? ORDER BY id DESC LIMIT 100",
                (int(ignored), before),
            )
            return jsonify([measurement(r) for r in rows])

    @app.get("/api/measurements/<int:measurement_id>")
    def measurement_detail(measurement_id: int) -> Any:
        with store.connect() as db:
            row = db.execute(
                "SELECT * FROM measurements WHERE id=?", (measurement_id,)
            ).fetchone()
            if row is None:
                raise LookupError("找不到量測")
            result = measurement(row)
            result["events"] = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM assignment_events WHERE measurement_id=? ORDER BY id",
                    (measurement_id,),
                )
            ]
            result["candidates"] = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM patients WHERE phone=? AND phone<>'' ORDER BY mrn",
                    (result["source_identifier"],),
                )
            ]
            return jsonify(result)

    @app.post("/api/measurements/<int:measurement_id>/assignment")
    def assign(measurement_id: int) -> Any:
        body = request.get_json()
        if not isinstance(body, dict) or "patient_id" not in body:
            raise ValueError("請選擇病人，解除歸檔請使用 null")
        patient_id = body["patient_id"]
        if patient_id is not None and (type(patient_id) is not int or patient_id <= 0):
            raise ValueError("病人識別格式錯誤")
        archive.assign(measurement_id, patient_id)
        return jsonify(ok=True)

    @app.post("/api/measurements/<int:measurement_id>/<action>")
    def ignore(measurement_id: int, action: str) -> Any:
        if action not in ("ignore", "restore"):
            raise LookupError("找不到操作")
        archive.assign(measurement_id, None, action)
        return jsonify(ok=True)

    @app.post("/api/measurements/<int:measurement_id>/reports")
    def generate_report(measurement_id: int) -> Any:
        return jsonify(archive.report(measurement_id)), 201

    @app.get("/api/reports/<int:report_id>")
    def report_metadata(report_id: int) -> Any:
        with store.connect() as db:
            row = db.execute(
                "SELECT id,measurement_id,patient_id,created_at,status,invalidated_at,template_version,mapping_version FROM reports WHERE id=?",
                (report_id,),
            ).fetchone()
            if row is None:
                raise LookupError("找不到報告")
            return jsonify(dict(row))

    @app.get("/api/reports/<int:report_id>/html")
    def report_html(report_id: int) -> Any:
        with store.connect() as db:
            row = db.execute(
                "SELECT html,invalidated_at FROM reports WHERE id=?", (report_id,)
            ).fetchone()
            if row is None:
                raise LookupError("找不到報告")
            if row["invalidated_at"]:
                return jsonify(error="此報告因歸檔修正失效，請重新產生"), 409
            return Response(row["html"], mimetype="text/html")

    @app.get("/api/backups")
    def backup_status() -> Any:
        return jsonify(backups.status())

    @app.post("/api/backups")
    def create_backup() -> Any:
        try:
            return jsonify(backups.create()), 201
        except (OSError, sqlite3.Error, ValueError):
            return jsonify(error="備份失敗，請檢查儲存位置"), 503

    @app.post("/api/backups/<name>/restore")
    def restore_backup(name: str) -> Any:
        return jsonify(backups.restore(name)), 201

    return app


def patient_input() -> tuple[str, str, str]:
    body = request.get_json()
    if not isinstance(body, dict):
        raise ValueError("請輸入病人資料")
    values = tuple(body.get(k, "") for k in ("mrn", "name", "phone"))
    if any(not isinstance(v, str) or len(v) > 200 for v in values):
        raise ValueError("欄位須為 200 字以內文字")
    mrn, name, phone = (v.strip() for v in values)
    if not mrn or not name:
        raise ValueError("病歷號及姓名必填")
    return mrn, name, phone
