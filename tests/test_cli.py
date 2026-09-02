"""CLI tests: arg wiring, output modes, doctor exit codes and --json.

All network is faked by patching the client class that the cmd_* functions
import at call time (`from .client import JobsDBClient`), so these run offline.
Focus: exit codes (important for automation), JSON output shape, and
flag -> filter wiring.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from jobsdb_wrapper.cli import main
from jobsdb_wrapper.doctor import CheckResult, DoctorReport
from jobsdb_wrapper.models import JobDetail, JobSummary, SearchResult

# The cmd_* helpers do `from .client import JobsDBClient` *inside* the function,
# so the class to patch is jobsdb_wrapper.client.JobsDBClient.
_CLIENT_ATTR = "jobsdb_wrapper.client.JobsDBClient"


def _summary(seq):
    return JobSummary(
        id=str(1000 + seq),
        title=f"Job {seq}",
        company=f"Company {seq}",
        location="Bangkok",
        listed_at="2026-08-30T00:00:00Z",
        salary_min=30000,
        salary_max=50000,
        salary_currency="THB",
        salary_period="monthly",
    )


def _result(total=50, n=2, page_size=20):
    return SearchResult(
        jobs=[_summary(i) for i in range(n)], page=1, page_size=page_size, total=total
    )


def _detail(job_id="94162495"):
    return JobDetail(
        id=job_id,
        title="Dev",
        content_html="<p>body</p>",
        company="C",
        location="Bangkok",
        salary_label="THB 50k",
        is_expired=False,
        listed_at="2026-08-30T00:00:00Z",
        created_at="2026-08-30T00:00:01Z",
        url="https://th.jobsdb.com/th/job/94162495",
    )


def _patch_cli_client(monkeypatch, *, result=None, job=None, markdown="# Dev\n\nbody"):
    """Patch the JobsDBClient class and wire `with` to yield the same mock."""
    fake = MagicMock()
    client = fake.return_value
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.search.return_value = result if result is not None else _result()
    client.job.return_value = job if job is not None else _detail()
    client.job_markdown.return_value = markdown
    monkeypatch.setattr(_CLIENT_ATTR, fake)
    return fake


# ------------------------------------------------------------------ search

def test_search_json_output(monkeypatch, capsys):
    fake = _patch_cli_client(monkeypatch)
    rc = main(["search", "python", "--where", "Bangkok", "--page-size", "5", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total"] == 50
    assert data["page_size"] == 20
    assert len(data["jobs"]) == 2
    assert data["jobs"][0]["title"] == "Job 0"
    # the --page-size flag reached the client
    assert fake.return_value.search.call_args.kwargs["page_size"] == 5


def test_search_flag_wiring(monkeypatch):
    fake = _patch_cli_client(monkeypatch)
    rc = main(
        ["search", "data analyst", "--where", "Bangkok", "--posted-within", "7",
         "--salary-min", "50000", "--salary-period", "monthly",
         "--work-type", "full_time", "--arrangement", "remote",
         "--sort", "date", "--facets", "--page-size", "10"]
    )
    assert rc == 0
    kw = fake.return_value.search.call_args.kwargs
    assert kw["keywords"] == "data analyst"
    assert kw["where"] == "Bangkok"
    assert kw["posted_within_days"] == 7
    assert kw["salary_min"] == 50000
    assert kw["salary_period"] == "monthly"
    assert kw["work_types"] == ["full_time"]
    assert kw["work_arrangements"] == ["remote"]
    assert kw["sort"] == "date"
    assert kw["include_facets"] is True
    assert kw["page_size"] == 10


def test_search_country_json(monkeypatch):
    fake = _patch_cli_client(monkeypatch)
    rc = main(["search", "accountant", "--where", "Hong Kong", "--country", "hk", "--json"])
    assert rc == 0
    # country reached the client constructor
    assert fake.call_args.kwargs["country"] == "hk"


# ------------------------------------------------------------------ job

def test_job_output_to_file(monkeypatch, tmp_path):
    fake = _patch_cli_client(monkeypatch)
    out = tmp_path / "job.md"
    rc = main(["job", "94162495", "-o", str(out)])
    assert rc == 0
    assert out.read_text() == "# Dev\n\nbody"
    assert fake.return_value.job_markdown.call_args.args[0] == "94162495"


def test_job_json_output(monkeypatch, capsys):
    _patch_cli_client(monkeypatch)
    rc = main(["job", "94162495", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["id"] == "94162495"
    assert data["content_html"] == "<p>body</p>"


# ------------------------------------------------------------------ doctor

def test_doctor_exit_zero_when_healthy(monkeypatch, capsys):
    rep = DoctorReport(results=[CheckResult("search.basic", True, "total=50")])
    monkeypatch.setattr("jobsdb_wrapper.doctor.run_doctor", lambda country="th": rep)
    rc = main(["doctor"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[PASS] search.basic" in out
    assert "Contract status: HEALTHY" in out


def test_doctor_exit_one_when_drift(monkeypatch, capsys):
    rep = DoctorReport(results=[CheckResult("salary", False, "missing")])
    monkeypatch.setattr("jobsdb_wrapper.doctor.run_doctor", lambda country="th": rep)
    rc = main(["doctor"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "[FAIL] salary" in out
    assert "Contract status: DRIFT DETECTED" in out


def test_doctor_json_output(monkeypatch, capsys):
    rep = DoctorReport(
        results=[CheckResult("basic", True, "ok"), CheckResult("facet", False, "nope")]
    )
    monkeypatch.setattr("jobsdb_wrapper.doctor.run_doctor", lambda country="th": rep)
    rc = main(["doctor", "--json"])
    assert rc == 1  # exit code still reflects drift
    data = json.loads(capsys.readouterr().out)
    assert data == {
        "status": "unhealthy",
        "checks": [
            {"name": "basic", "status": "pass", "detail": "ok"},
            {"name": "facet", "status": "fail", "detail": "nope"},
        ],
    }
