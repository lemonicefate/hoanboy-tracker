"""Read-only adapter for the observed Android Debug Database protocol."""

import json
import subprocess
import threading
from typing import Any


class DeviceReader:
    def __init__(self, address: str = "192.168.1.102"):
        import ipaddress

        if not ipaddress.ip_address(address).is_private:
            raise ValueError("設備必須使用區網 IP")
        self.base = f"http://{address}:8080/"
        self.lock = threading.Lock()

    def get(self, route: str) -> dict[str, Any]:
        result = subprocess.run(
            [
                "curl.exe",
                "--noproxy",
                "*",
                "--connect-timeout",
                "5",
                "--max-time",
                "15",
                "--fail",
                "--silent",
                "--max-filesize",
                "67108864",
                self.base + route,
            ],
            capture_output=True,
            timeout=20,
            check=True,
        )
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict) or payload.get("isSuccessful") is not True:
            raise ValueError("設備回應失敗")
        return payload

    def __call__(self) -> dict[str, Any]:
        with self.lock:
            tables = self.get("getTableList?database=heer_scale.db")
            if "bodyparm" not in tables.get("rows", []):
                raise ValueError("設備資料庫沒有 bodyparm")
            first = self.get("getAllDataFromTheTable?tableName=bodyparm")
            # Re-select and compare schema after reading to catch observable interference.
            self.get("getTableList?database=heer_scale.db")
            second = self.get("getAllDataFromTheTable?tableName=bodyparm")
            if first.get("tableInfos") != second.get("tableInfos"):
                raise ValueError("設備資料結構在讀取期間改變")
            validate_snapshot(first)
            validate_snapshot(second)
            return second


def validate_snapshot(
    payload: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if (
        not isinstance(payload, dict)
        or payload.get("isSuccessful") is not True
        or payload.get("isSelectQuery") is not True
    ):
        raise ValueError("不是成功的唯讀資料回應")
    schema, rows = payload.get("tableInfos"), payload.get("rows")
    if not isinstance(schema, list) or not isinstance(rows, list):
        raise ValueError("設備資料結構錯誤")
    if any(
        not isinstance(c, dict) or not isinstance(c.get("title"), str) for c in schema
    ):
        raise ValueError("設備欄位結構錯誤")
    columns = [c["title"] for c in schema]
    if len(set(columns)) != len(columns) or not {
        "uid",
        "username",
        "time",
        "bhWeightKg",
        "bhBMI",
        "bhBodyFatRate",
    }.issubset(columns):
        raise ValueError("設備欄位缺漏或重複")
    if not any(c["title"] == "uid" and c.get("isPrimary") is True for c in schema):
        raise ValueError("設備來源鍵結構改變")
    records, seen = [], set()
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != len(columns)
            or any(not isinstance(c, dict) or "value" not in c for c in row)
        ):
            raise ValueError("設備列寬或儲存格結構錯誤")
        record = {k: cell["value"] for k, cell in zip(columns, row)}
        if any(
            v is not None and not isinstance(v, (str, int, float))
            for v in record.values()
        ):
            raise ValueError("設備值格式錯誤")
        uid = str(record["uid"]) if record["uid"] is not None else ""
        if not uid or uid in seen:
            raise ValueError("設備來源鍵缺漏或重複")
        seen.add(uid)
        records.append(record)
    return schema, records
