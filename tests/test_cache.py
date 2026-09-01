import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobsdb_wrapper.cache import DetailCache  # noqa: E402


def test_cache_roundtrip(tmp_path):
    c = DetailCache(tmp_path / "cache.db")
    payload = {"content": "<p>hello</p>", "title": "T"}
    c.put("111", "th", payload)
    got = c.get_valid("111", "th")
    assert got and got["title"] == "T"
    stats = c.stats()
    assert stats["entries"] == 1
    c.close()


def test_cache_market_isolation(tmp_path):
    c = DetailCache(tmp_path / "c2.db")
    c.put("111", "th", {"content": "x"})
    assert c.get("111", "sg") is None
    c.close()


def test_cache_invalid_content_hash(tmp_path):
    c = DetailCache(tmp_path / "c3.db")
    payload = {"content": "<p>v1</p>"}
    c.put("222", "th", payload)
    # simulate upstream edit: stored hash no longer matches new content
    row_payload = c.get("222", "th")
    row_payload["content"] = "<p>v2 changed</p>"
    # write back without updating hash -> get_valid must reject
    with c._lock:
        import json

        c._conn.execute(
            "UPDATE details SET payload=? WHERE job_id='222'", (json.dumps(row_payload),)
        )
        c._conn.commit()
    assert c.get_valid("222", "th") is None
    c.close()


def test_doctor_report_shape():
    from jobsdb_wrapper.doctor import CheckResult, DoctorReport

    r = DoctorReport(results=[CheckResult("a", True, "ok"), CheckResult("b", False, "bad")])
    assert not r.healthy
    s = r.summary()
    assert "[OK ] a" in s and "DRIFT DETECTED" in s
