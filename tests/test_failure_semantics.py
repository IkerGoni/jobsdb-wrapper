"""Tests for typed failure semantics (P2.2).

Verifies:
- Five failure classes distinguishable in code
- JobsDBError hierarchy: JobsDBError -> JobsDBBlockedError, JobsDBHTTPError
- RequestError.kind carries: network, http, blocked, runtime
- Exceptions include diagnostic context (status, body snippet, operation)
"""
from jobsdb_wrapper.http import classify_response
from jobsdb_wrapper.models import JobsDBBlockedError, JobsDBError, JobsDBHTTPError


def test_exception_hierarchy():
    """JobsDBError -> JobsDBBlockedError, JobsDBHTTPError"""
    assert issubclass(JobsDBBlockedError, JobsDBError)
    assert issubclass(JobsDBHTTPError, JobsDBError)
    assert JobsDBBlockedError.__bases__ == (JobsDBError,)
    assert JobsDBHTTPError.__bases__ == (JobsDBError,)


def test_five_failure_classes_distinguishable():
    """Five classes: ok (dict return), network, http, blocked, runtime"""
    # RequestError kinds
    kinds = set()
    for status, text in [
        (200, "<html>Just a moment</html>"),
        (403, "forbidden"),
        (429, "rate limit"),
        (500, "server err"),
        (200, "not json"),
    ]:
        err = classify_response(status, text)
        kinds.add(err.kind)
    assert kinds == {"blocked", "http", "network"}

    # runtime comes from interpret_body path - tested separately
    # ok is dict return from classify_response(200, valid_json)
    ok_result = classify_response(200, '{"data":{}}')
    assert isinstance(ok_result, dict)


def test_request_error_kinds():
    """RequestError.kind carries: network, http, blocked, runtime"""
    assert classify_response(200, "not json").kind == "network"
    assert classify_response(403, "forbidden").kind == "blocked"
    assert classify_response(429, "rate limited").kind == "http"
    assert classify_response(500, "server error").kind == "http"
    # runtime is raised by interpret_body for UNSTABLE_QUERY_ERROR


def test_jobsdberror_diagnostic_context():
    """JobsDBError includes status, body_snippet, operation"""
    e = JobsDBError(
        "network failure",
        kind="network",
        status=None,
        body_snippet="connection refused",
        operation="JobSearchV7",
    )
    assert e.kind == "network"
    assert e.status is None
    assert e.body_snippet == "connection refused"
    assert e.operation == "JobSearchV7"


def test_jobsdblockederror_diagnostic_context():
    """JobsDBBlockedError includes status, body_snippet, operation"""
    e = JobsDBBlockedError(
        "challenged",
        status=403,
        body_snippet="<html>challenge</html>",
        operation="JobSearchV7",
    )
    assert e.kind == "blocked"
    assert e.status == 403
    assert e.body_snippet == "<html>challenge</html>"
    assert e.operation == "JobSearchV7"


def test_jobsdbhttperror_diagnostic_context():
    """JobsDBHTTPError includes status, body_snippet, operation"""
    e = JobsDBHTTPError(
        502,
        "bad gateway body",
        operation="JobDetail",
    )
    assert e.kind == "http"
    assert e.status == 502
    assert e.body_snippet == "bad gateway body"
    assert e.operation == "JobDetail"


def test_classify_response_diagnostic_fields():
    """RequestError carries status and body_snippet for diagnostics"""
    # Cloudflare challenge in 200
    err = classify_response(200, "<html>Just a moment...</html>")
    assert err.kind == "blocked"
    assert err.status == 200
    assert err.body_snippet is not None
    assert "Just a moment" in err.body_snippet

    # HTTP 403
    err = classify_response(403, "forbidden access")
    assert err.kind == "blocked"
    assert err.status == 403
    assert err.body_snippet is not None
    assert "forbidden" in err.body_snippet.lower()

    # HTTP 429
    err = classify_response(429, "rate limited")
    assert err.kind == "http"
    assert err.status == 429
    assert err.body_snippet is not None
    assert "rate limited" in err.body_snippet

    # Non-JSON 200
    err = classify_response(200, "not json at all")
    assert err.kind == "network"
    assert err.status == 200
    assert err.body_snippet == "not json at all"

    # 500
    err = classify_response(500, "server error")
    assert err.kind == "http"
    assert err.status == 500
