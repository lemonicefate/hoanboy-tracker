from datetime import datetime, timezone
import hashlib
import json
import threading
from typing import Any, Callable
from hoanboy.device import validate_snapshot
from hoanboy.mapping import MAPPING_VERSION, normalize, parse_time
from hoanboy.store import Store
from hoanboy import reports


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def measurement(row: Any) -> dict[str, Any]:
    result = dict(row)
    for key in ("raw", "source_schema", "source_row", "metrics"):
        result[key] = json.loads(result[key])
    result["ignored"] = bool(result["ignored"])
    return result


class Busy(Exception):
    pass


class SyncFailed(Exception):
    pass


class Archive:
    def __init__(
        self,
        store: Store,
        reader: Callable[[], dict[str, Any]],
        device: str,
        verified: dict[str, str],
    ):
        self.store, self.reader, self.device, self.verified = (
            store,
            reader,
            device,
            verified,
        )
        self.sync_lock = threading.Lock()

    def sync(self) -> dict[str, Any]:
        if not self.sync_lock.acquire(blocking=False):
            raise Busy("同步進行中")
        run_id = None
        try:
            with self.store.connect() as db:
                run_id = db.execute(
                    "INSERT INTO sync_runs(started_at,status) VALUES(?, 'running')",
                    (now(),),
                ).lastrowid
            payload = self.reader()
            schema, records = validate_snapshot(payload)
            captured = now()
            counts = {"added": 0, "updated": 0, "unchanged": 0}
            with self.store.connect() as db:
                for raw, source_row in zip(records, payload["rows"]):
                    key = str(raw["uid"])
                    digest = hashlib.sha256(encode(raw).encode()).hexdigest()
                    existing = db.execute(
                        "SELECT id FROM measurements WHERE device=? AND source_key=? AND digest=?",
                        (self.device, key, digest),
                    ).fetchone()
                    if existing:
                        counts["unchanged"] += 1
                        continue
                    previous = db.execute(
                        "SELECT id FROM measurements WHERE device=? AND source_key=? ORDER BY id DESC LIMIT 1",
                        (self.device, key),
                    ).fetchone()
                    counts["updated" if previous else "added"] += 1
                    db.execute(
                        """INSERT INTO measurements(device,source_key,digest,raw,source_schema,source_row,captured_at,
                        source_time,sort_time,source_timezone,clock_status,source_identifier,metrics,mapping_version,changed_from)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            self.device,
                            key,
                            digest,
                            encode(raw),
                            encode(schema),
                            encode(source_row),
                            captured,
                            raw.get("time"),
                            parse_time(raw.get("time")),
                            None,
                            "unverified",
                            raw.get("username"),
                            encode(normalize(raw, self.verified)),
                            MAPPING_VERSION,
                            previous["id"] if previous else None,
                        ),
                    )
                db.execute(
                    "UPDATE sync_runs SET status='success',finished_at=?,added=?,updated=?,unchanged=? WHERE id=?",
                    (
                        now(),
                        counts["added"],
                        counts["updated"],
                        counts["unchanged"],
                        run_id,
                    ),
                )
            return dict(id=run_id, status="success", **counts)
        except Exception as error:
            if run_id is not None:
                with self.store.connect() as db:
                    db.execute(
                        "UPDATE sync_runs SET status='failed',finished_at=?,error=? WHERE id=?",
                        (
                            now(),
                            "設備離線、逾時或資料結構驗證失敗；既有資料未變更",
                            run_id,
                        ),
                    )
            raise SyncFailed(
                "設備離線、逾時或資料結構驗證失敗；請確認設備後重試"
            ) from error
        finally:
            self.sync_lock.release()

    def sync_status(self) -> dict[str, Any]:
        with self.store.connect() as db:
            latest = db.execute(
                "SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            success = db.execute(
                "SELECT finished_at FROM sync_runs WHERE status='success' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(
                running=self.sync_lock.locked(),
                latest=dict(latest) if latest else None,
                last_success=success[0] if success else None,
            )

    def assign(
        self, measurement_id: int, patient_id: int | None, action: str = "assign"
    ) -> None:
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM measurements WHERE id=?", (measurement_id,)
            ).fetchone()
            if row is None:
                raise LookupError("找不到量測")
            if (
                patient_id is not None
                and db.execute(
                    "SELECT 1 FROM patients WHERE id=?", (patient_id,)
                ).fetchone()
                is None
            ):
                raise LookupError("找不到病人")
            if action in ("ignore", "restore") and row["patient_id"] is not None:
                raise ValueError("請先解除歸檔")
            db.execute(
                "UPDATE measurements SET patient_id=?,ignored=? WHERE id=?",
                (patient_id, int(action == "ignore"), measurement_id),
            )
            db.execute(
                "INSERT INTO assignment_events(measurement_id,before_patient,after_patient,action,actor,at) VALUES(?,?,?,?,?,?)",
                (
                    measurement_id,
                    row["patient_id"],
                    patient_id,
                    action,
                    "operator",
                    now(),
                ),
            )
            if row["patient_id"] != patient_id:
                db.execute(
                    "UPDATE reports SET invalidated_at=? WHERE invalidated_at IS NULL AND id IN (SELECT report_id FROM report_measurements WHERE measurement_id=?)",
                    (now(), measurement_id),
                )

    def report(self, measurement_id: int) -> dict[str, Any]:
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            raw = db.execute(
                "SELECT * FROM measurements WHERE id=?", (measurement_id,)
            ).fetchone()
            if raw is None:
                raise LookupError("找不到量測")
            current = measurement(raw)
            if current["patient_id"] is None:
                raise ValueError("請先人工歸檔")
            if current["sort_time"] is None:
                raise ValueError("量測時間無法解析，不能建立截止歷史報告")
            existing = db.execute(
                "SELECT id,status FROM reports WHERE measurement_id=? AND invalidated_at IS NULL ORDER BY id DESC LIMIT 1",
                (measurement_id,),
            ).fetchone()
            if existing:
                return dict(existing)
            patient = dict(
                db.execute(
                    "SELECT * FROM patients WHERE id=?", (current["patient_id"],)
                ).fetchone()
            )
            history = [
                measurement(r)
                for r in db.execute(
                    "SELECT * FROM measurements WHERE patient_id=? AND (sort_time<? OR (sort_time=? AND id<=?)) ORDER BY sort_time,id",
                    (
                        current["patient_id"],
                        current["sort_time"],
                        current["sort_time"],
                        measurement_id,
                    ),
                )
            ]
            saved = dict(
                patient=patient,
                current=current,
                history=history,
                created_at=now(),
                template_version=reports.TEMPLATE_VERSION,
            )
            html = reports.render(saved)
            cursor = db.execute(
                "INSERT INTO reports(measurement_id,patient_id,created_at,template_version,mapping_version,status,snapshot,html) VALUES(?,?,?,?,?,'draft',?,?)",
                (
                    measurement_id,
                    current["patient_id"],
                    saved["created_at"],
                    reports.TEMPLATE_VERSION,
                    current["mapping_version"],
                    encode(saved),
                    html,
                ),
            )
            report_id = cursor.lastrowid
            db.executemany(
                "INSERT INTO report_measurements(report_id,measurement_id) VALUES(?,?)",
                [(report_id, m["id"]) for m in history],
            )
            return dict(id=report_id, status="draft")

    def patient(self, patient_id: int) -> dict[str, Any]:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM patients WHERE id=?", (patient_id,)
            ).fetchone()
            if row is None:
                raise LookupError("找不到病人")
            history = [
                measurement(r)
                for r in db.execute(
                    "SELECT * FROM measurements WHERE patient_id=? ORDER BY sort_time IS NULL,sort_time DESC,id DESC",
                    (patient_id,),
                )
            ]
        trends: dict[str, list[dict[str, Any]]] = {}
        differences = {}
        for key in ("weight", "fat_rate"):
            points = []
            for item in reversed(history):
                if not item["sort_time"]:
                    continue
                metric = item["metrics"][key]
                status = metric["status"] if item["sort_time"] else "invalid_time"
                points.append(
                    dict(
                        id=item["id"],
                        time=item["source_time"],
                        value=metric["value"] if status == "verified" else None,
                        status=status,
                        clock_status=item["clock_status"],
                    )
                )
            trends[key] = points
            values = [p["value"] for p in points]

            def delta(index: int) -> float | None:
                if len(values) < 2 or values[-1] is None or values[index] is None:
                    return None
                return round(values[-1] - values[index], 6)

            differences[key] = dict(first=delta(0), previous=delta(-2))
        return dict(
            patient=dict(row),
            measurements=history,
            trends=trends,
            differences=differences,
            latest=next((m for m in history if m["sort_time"]), None),
        )
