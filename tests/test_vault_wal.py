"""健康库是 WAL 模式：旁边的 -shm 不在时，只读打开也要能读（封版测试 P1）。"""
from __future__ import annotations

import sqlite3

import pytest

from pivis_health.readonly import ReadOnlyObjectiveStore


def _wal_db(path):
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE samples(type TEXT, end_at TEXT)")
    con.execute("INSERT INTO samples VALUES('step_count', '2026-11-06T16:00:00Z')")
    con.commit()
    con.close()
    for ext in ("-wal", "-shm"):    # 拷贝出来的库、或写入方都正常关掉后，旁边就没有这两个文件
        p = path.parent / (path.name + ext)
        if p.exists():
            p.unlink()


def test_wal_db_without_shm_still_readable(tmp_path):
    db = tmp_path / "health.sqlite3"
    _wal_db(db)
    assert not (tmp_path / "health.sqlite3-shm").exists()
    with pytest.raises(sqlite3.OperationalError):          # 旧做法：只读方式直接打不开
        sqlite3.connect(f"file:{db}?mode=ro", uri=True).execute("SELECT count(*) FROM samples").fetchone()
    con = ReadOnlyObjectiveStore(db).connect()
    try:
        assert con.execute("SELECT count(*) FROM samples").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):      # 退回普通打开后照样不能写
            con.execute("INSERT INTO samples VALUES('x', 'y')")
    finally:
        con.close()
