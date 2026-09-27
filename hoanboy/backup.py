"""Consistent SQLite snapshots include rendered reports and all source records."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from typing import Any
from hoanboy.store import Store


def inspect(path: Path) -> dict[str, int]:
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            if (
                connection.execute("PRAGMA application_id").fetchone()[0] != 1213153614
                or connection.execute("PRAGMA user_version").fetchone()[0] != 1
            ):
                raise ValueError("備份格式或版本不符")
            if (
                connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or connection.execute("PRAGMA foreign_key_check").fetchall()
            ):
                raise ValueError("備份完整性檢查失敗")
            return {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "patients",
                    "measurements",
                    "assignment_events",
                    "reports",
                )
            }
        finally:
            connection.close()
    except sqlite3.DatabaseError as error:
        raise ValueError("備份資料損毀") from error


class Backups:
    def __init__(self, store: Store, directory: Path, restores: Path):
        self.store, self.directory, self.restores = store, directory, restores
        self.lock = threading.Lock()
        self.error: str | None = None

    def create(self, automatic: bool = False) -> dict[str, Any]:
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone(timedelta(hours=8)))
            name = (
                f"auto-{stamp:%Y-%m-%d}.sqlite3"
                if automatic
                else f"manual-{stamp:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}.sqlite3"
            )
            target = self.directory / name
            temporary = self.directory / (uuid.uuid4().hex + ".tmp")
            try:
                with self.store.connect() as source:
                    destination = sqlite3.connect(temporary)
                    try:
                        source.backup(destination)
                    finally:
                        destination.close()
                counts = inspect(temporary.resolve())
                digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
                os.replace(temporary, target)
                manifest = target.with_suffix(".json")
                manifest_tmp = manifest.with_suffix(".tmp")
                manifest_tmp.write_text(
                    json.dumps(
                        dict(sha256=digest, counts=counts, created_at=stamp.isoformat())
                    ),
                    encoding="utf-8",
                )
                os.replace(manifest_tmp, manifest)
                for old in sorted(self.directory.glob("auto-*.sqlite3"), reverse=True)[
                    30:
                ]:
                    old.unlink()
                    old.with_suffix(".json").unlink(missing_ok=True)
                self.error = None
                return dict(name=name, counts=counts, created_at=stamp.isoformat())
            finally:
                temporary.unlink(missing_ok=True)

    def automatic(self) -> None:
        try:
            self.create(automatic=True)
        except (OSError, sqlite3.Error, ValueError):
            self.error = "自動備份失敗；資料已存入本機，請立即檢查備份位置並重試"

    def status(self) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        try:
            for path in sorted(self.directory.glob("*.sqlite3"), reverse=True):
                files.append(dict(name=path.name, bytes=path.stat().st_size))
        except OSError:
            self.error = "無法讀取備份位置"
        return dict(
            files=files,
            error=self.error,
            automatic=any(f["name"].startswith("auto-") for f in files),
            directory=str(self.directory),
        )

    def restore(self, name: str) -> dict[str, Any]:
        if not re.fullmatch(
            r"(?:auto-\d{4}-\d{2}-\d{2}|manual-\d{8}T\d{6}-[a-f0-9]{8})\.sqlite3", name
        ):
            raise ValueError("備份名稱無效")
        with self.lock:
            source = self.directory / name
            try:
                manifest = json.loads(
                    source.with_suffix(".json").read_text(encoding="utf-8")
                )
                content = source.read_bytes()
                if hashlib.sha256(content).hexdigest() != manifest["sha256"]:
                    raise ValueError("備份校驗碼不符")
            except (OSError, KeyError, json.JSONDecodeError) as error:
                raise ValueError("備份或校驗資料缺漏") from error
            restore_id = uuid.uuid4().hex
            folder = self.restores / restore_id
            folder.mkdir(parents=True)
            target = folder / "archive.sqlite3"
            target.write_bytes(content)
            counts = inspect(target.resolve())
            if counts != manifest["counts"]:
                raise ValueError("備份資料筆數不符")
            (folder / "restore.json").write_text(
                json.dumps(dict(sha256=manifest["sha256"], source=name, counts=counts)),
                encoding="utf-8",
            )
            return dict(
                id=restore_id,
                counts=counts,
                status="verified-isolated",
                instruction="已在隔離位置還原並驗證。停止程式後用 restore 指令啟用。",
            )
