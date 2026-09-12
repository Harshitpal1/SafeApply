import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from main import create_app


def make_client(tmp_path):
    db_path = tmp_path / "test.db"
    app = create_app(str(db_path))
    return TestClient(app)


def seed_profile(client):
    payload = {
        "name": "Harshit",
        "skills": "python,fastapi,javascript",
        "education": "B.Tech",
        "resume_link": "https://example.com/resume.pdf",
        "preferred_job_type": "intern",
        "preferred_location": "remote",
    }
    res = client.post("/profile", json=payload)
    assert res.status_code == 200


def test_profile_roundtrip(tmp_path):
    client = make_client(tmp_path)
    seed_profile(client)

    data = client.get("/profile").json()
    assert data["name"] == "Harshit"
    assert data["preferred_location"] == "remote"


def test_search_jobs_returns_match_score(tmp_path):
    client = make_client(tmp_path)
    seed_profile(client)

    res = client.post("/search-jobs", json={"site_name": "internshala"})
    assert res.status_code == 200
    jobs = res.json()
    assert jobs
    assert {"job_title", "company", "match_score", "listing_url"}.issubset(jobs[0])


def test_fill_validate_approve_flow(tmp_path):
    client = make_client(tmp_path)
    seed_profile(client)

    jobs = client.post("/search-jobs", json={"site_name": "internshala"}).json()
    target = jobs[0]

    fill = client.post(
        "/fill-application",
        json={
            "job_title": target["job_title"],
            "company": target["company"],
            "site_name": "internshala",
            "listing_url": target["listing_url"],
        },
    )
    assert fill.status_code == 200
    fill_body = fill.json()
    assert fill_body["application_id"] > 0

    validate = client.post(
        "/validate-application",
        json={
            "application_id": fill_body["application_id"],
            "filled_form_json": fill_body["filled_fields"],
            "job_description_text": target["description"],
        },
    )
    assert validate.status_code == 200
    assert validate.json()["status"] in {"approved", "flagged"}

    approve = client.post("/approve-application", json={"application_id": fill_body["application_id"]})
    assert approve.status_code == 200
    assert approve.json()["status"] in {"submitted", "failed"}


def test_validation_flags_bad_resume_link(tmp_path):
    client = make_client(tmp_path)
    seed_profile(client)

    fill = client.post(
        "/fill-application",
        json={
            "job_title": "X",
            "company": "Y",
            "site_name": "internshala",
            "listing_url": "https://internshala.com/job/python-backend-intern-1",
        },
    ).json()

    bad = dict(fill["filled_fields"])
    bad["resume_link"] = "invalid-url"

    validate = client.post(
        "/validate-application",
        json={
            "application_id": fill["application_id"],
            "filled_form_json": bad,
            "job_description_text": "python fastapi role",
        },
    )
    assert validate.status_code == 200
    body = validate.json()
    assert body["status"] == "flagged"
    assert "Resume link" in body["reason"]
