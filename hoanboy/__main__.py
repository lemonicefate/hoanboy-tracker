import argparse
from contextlib import contextmanager
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sys
from typing import Iterator
from werkzeug.security import generate_password_hash
from hoanboy.app import create_app
from hoanboy.backup import Backups, inspect
from hoanboy.device import DeviceReader
from hoanboy.store import Store


@contextmanager
def process_lock(directory: Path) -> Iterator[None]:
    """An OS lock prevents a second server or live restore on this archive."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "process.lock").open("a+b") as lock:
        lock.seek(0)
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("此資料目錄已有程式執行；請先停止再操作") from error
        try:
            yield
        finally:
            if sys.platform == "win32":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def main() -> None:
    parser = argparse.ArgumentParser(description="HOANBOY 本機量測工作台")
    parser.add_argument("--data-dir", type=Path, default=Path("private/app"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="建立單一操作帳號及本機設定")
    run = sub.add_parser("serve", help="啟動本機工作台")
    run.add_argument("--port", type=int, default=8765)
    restore = sub.add_parser(
        "restore", help="啟用已隔離驗證的還原資料；必須先停止伺服器"
    )
    restore.add_argument("restore_id")
    args = parser.parse_args()
    directory = args.data_dir.resolve()
    config_path = directory / "config.json"
    try:
        with process_lock(directory):
            if args.command == "init":
                if config_path.exists():
                    raise ValueError("設定已存在，未覆寫")
                password = getpass.getpass("設定操作密碼（至少 12 字元）: ")
                if len(password) < 12 or password != getpass.getpass("再次輸入: "):
                    raise ValueError("密碼太短或兩次不符")
                config = dict(
                    password_hash=generate_password_hash(password),
                    device_address="192.168.1.102",
                    device_id="hoanboy-370",
                    backup_dir=str(directory / "backups"),
                    verified_fields={},
                )
                config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
                Store(directory / "archive.sqlite3")
                print("初始化完成。執行 uv run python -m hoanboy serve")
                return
            if not config_path.exists():
                raise ValueError("請先執行 init")
            config = json.loads(config_path.read_text(encoding="utf-8"))
            backup_dir = Path(config["backup_dir"]).resolve()
            if args.command == "restore":
                if not re.fullmatch(r"[a-f0-9]{32}", args.restore_id):
                    raise ValueError("還原識別無效")
                source = directory / "restores" / args.restore_id / "archive.sqlite3"
                manifest = json.loads(
                    source.with_name("restore.json").read_text(encoding="utf-8")
                )
                if (
                    hashlib.sha256(source.read_bytes()).hexdigest()
                    != manifest["sha256"]
                ):
                    raise ValueError("隔離還原資料已變更，請重新驗證原備份")
                counts = inspect(source)
                backup = Backups(
                    Store(directory / "archive.sqlite3"),
                    backup_dir,
                    directory / "restores",
                ).create()
                target = directory / "archive.sqlite3"
                temporary = directory / "restore.tmp"
                temporary.write_bytes(source.read_bytes())
                inspect(temporary)
                os.replace(temporary, target)
                (directory / "session.key").write_text(secrets.token_hex(32))
                print(f"還原完成：{counts}。原資料備份：{backup['name']}")
                return
            # Fail before starting background work if the port is occupied.
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", args.port))
            from waitress import serve

            app = create_app(
                directory,
                config["password_hash"],
                reader=DeviceReader(config["device_address"]),
                device=config["device_id"],
                verified=config.get("verified_fields", {}),
                backup_dir=backup_dir,
            )
            print(f"HOANBOY http://127.0.0.1:{args.port} · Ctrl+C 停止", flush=True)
            serve(
                app,
                host="127.0.0.1",
                port=args.port,
                threads=4,
                clear_untrusted_proxy_headers=True,
            )
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f"操作未完成：{error}\n")


if __name__ == "__main__":
    main()
