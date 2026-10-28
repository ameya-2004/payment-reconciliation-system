import pytest

from app import create_app


@pytest.fixture()
def client(starter):
    path, _ = starter
    return create_app(data_dir=str(path)).test_client()


def test_home_and_health(client):
    assert client.get("/").status_code == 200
    assert client.get("/health").get_json() == {"status": "healthy"}


def test_summary_counts_match_the_tables(client, starter):
    _, res = starter
    body = client.get("/api/summary").get_json()
    assert body["status"] == "ready"
    assert body["exceptions"] == len(res["tables"]["exceptions"])
    assert sum(body["exceptions_by_type"].values()) == body["exceptions"]


def test_exception_filters_and_paging(client):
    all_rows = client.get("/api/exceptions?limit=1000").get_json()
    kind = all_rows["exceptions"][0]["exception_type"]
    some = client.get("/api/exceptions?type=%s" % kind).get_json()
    assert some["count"] == sum(1 for x in all_rows["exceptions"] if x["exception_type"] == kind)
    assert len(client.get("/api/exceptions?limit=2").get_json()["exceptions"]) == 2
    assert client.get("/api/exceptions?limit=abc").status_code == 400


def test_exception_detail_is_traceable(client):
    first = client.get("/api/exceptions?limit=1000").get_json()["exceptions"]
    resolved = next(x for x in first if x["status"] == "RESOLVED")
    body = client.get("/api/exceptions/%s" % resolved["exception_id"]).get_json()
    assert body["exception"]["exception_id"] == resolved["exception_id"]
    assert body["resolution"]["exception_id"] == resolved["exception_id"]
    assert body["status_history"][0]["to_status"] == "OPEN"
    assert body["status_history"][-1]["to_status"] == "RESOLVED"
    assert client.get("/api/exceptions/EXC-2026-999999").status_code == 404


def test_validation_and_evaluation_endpoints(client):
    v = client.get("/api/validation").get_json()
    assert v["passed"] == v["total"]
    assert client.get("/api/evaluation").get_json()["detection"]["false_neg"] == 0


def test_not_ready_when_nothing_has_been_generated(tmp_path):
    c = create_app(data_dir=str(tmp_path)).test_client()
    assert c.get("/api/summary").status_code == 503
