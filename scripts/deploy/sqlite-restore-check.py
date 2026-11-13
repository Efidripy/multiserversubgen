#!/usr/bin/env python3
"""Restore a backup into a temporary directory and check its integrity."""
import argparse
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path


def check_backup(path, temp_dir):
    source = path.resolve(strict=True)
    with source.open("rb") as stream:
        if stream.read(16) != b"SQLite format 3\x00":
            raise ValueError("invalid SQLite backup header")
    with tempfile.TemporaryDirectory(prefix="sqlite-restore-", dir=temp_dir) as temp:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as backup:
            with closing(sqlite3.connect(Path(temp) / "restored.db")) as restored:
                backup.backup(restored)
                if restored.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise RuntimeError("restored database integrity check failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("--metrics-backup", type=Path)
    parser.add_argument("--temp-dir", type=Path, default=None)
    args = parser.parse_args()
    check_backup(args.backup, args.temp_dir)
    if args.metrics_backup:
        check_backup(args.metrics_backup, args.temp_dir)
    print("Restore integrity check: ok")


if __name__ == "__main__":
    main()
