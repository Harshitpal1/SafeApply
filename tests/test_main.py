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


def create_application(client, site_name="internshala", listing_url="https://internshala.com/job/python-backend-intern-1"):
    return client.post(
        "/fill-application",
        json={
            "job_title": "Python Backend Intern",
            "company": "Alpha Labs",
            "site_name": site_name,
            "listing_url": listing_url,
        },
    )


def validate_application(client, application_id, filled_form, description="python fastapi javascript backend"):
    return client.post(
        "/validate-application",
        json={
            "application_id": application_id,
            "filled_form_json": filled_form,
            "job_description_text": description,
        },
    )


def get_application(client, application_id):
    rows = client.get("/applications").json()
    for row in rows:
        if row["id"] == application_id:
            return row
    return None


def test_profile_create_get_and_update(tmp_path):
    client = make_client(tmp_path)
    create_payload = {
        "name": "Harshit",
        "skills": "python,fastapi,javascript",
        "education": "B.Tech",
        "resume_link": "https://example.com/resume.pdf",
        "preferred_job_type": "intern",
        "preferred_location": "remote",
    }
    create_res = client.post("/profile", json=create_payload)
    assert create_res.status_code == 200
    assert create_res.json() == {"message": "Profile saved"}

    data = client.get("/profile").json()
    assert data["name"] == "Harshit"
    assert data["preferred_location"] == "remote"

    update_payload = dict(create_payload)
    update_payload["preferred_location"] = "bangalore"
    update_payload["skills"] = "python,fastapi"
    update_res = client.post("/profile", json=update_payload)
    assert update_res.status_code == 200

    updated = client.get("/profile").json()
    assert updated["preferred_location"] == "bangalore"
    assert updated["skills"] == "python,fastapi"


def test_search_jobs_returns_match_score_and_calculation(tmp_path):
    client = make_client(tmp_path)
    seed_profile(client)

    res = client.post("/search-jobs", json={"site_name": "internshala"})
    assert res.status_code == 200
    jobs = res.json()
    assert jobs
    assert {"job_title", "company", "match_score", "listing_url"}.issubset(jobs[0])
    backend_role = next(job for job in jobs if job["job_title"] == "Python Backend Intern")
    assert backend_role["match_score"] == 67


def test_fill_application_creates_pending_and_never_submits(tmp_path):
    client = make_client(tmp_path)
    seed_profile(client)
    fill = create_application(client)
    assert fill.status_code == 200
    fill_body = fill.json()
    assert fill_body["status"] == "pending"
    assert fill_body["field_errors"] == {}

    app_row = get_application(client, fill_body["application_id"])
    assert app_row is not None
    assert app_row["status"] == "pending"
    assert app_row["error_log"] is None

    status_after_fill = client.post("/approve-application", json={"application_id": fill_body["application_id"]})
    assert status_after_fill.status_code == 400
    assert "validated and approved" in status_after_fill.json()["detail"]


def test_validate_application_approved_response_and_no_submission(tmp_path):
    client = make_client(tmp_path)
    seed_profile(client)
    fill = create_application(client).json()

    validate = validate_application(client, fill["application_id"], fill["filled_fields"])
    assert validate.status_code == 200
    assert validate.json() == {"status": "approved"}

    app_row = get_application(client, fill["application_id"])
    assert app_row["status"] == "approved"

    approve = client.post("/approve-application", json={"application_id": fill["application_id"]})
    assert approve.status_code == 200
    assert approve.json()["status"] == "submitted"


def test_validate_application_flagged_response(tmp_path):
    client = make_client(tmp_path)
    seed_profile(client)

    fill = create_application(client).json()

    bad = dict(fill["filled_fields"])
    bad["resume_link"] = "invalid-url"

    validate = validate_application(client, fill["application_id"], bad)
    assert validate.status_code == 200
    body = validate.json()
    assert body["status"] == "flagged"
    assert "Resume link" in body["reason"]

    app_row = get_application(client, fill["application_id"])
    assert app_row["status"] == "flagged"
    assert "Resume link" in app_row["flag_reason"]


def test_fill_failure_handling_persists_failed_status_and_error_log(tmp_path):
    client = make_client(tmp_path)
    seed_profile(client)

    fill = create_application(client, listing_url="https://internshala.com/job/qa-intern-broken-layout")
    assert fill.status_code == 502
    body = fill.json()
    assert body["status"] == "failed"
    assert "Agent 1 fill operation failed" in body["error"]
    assert "education" in body["field_errors"]

    app_row = get_application(client, body["application_id"])
    assert app_row["status"] == "failed"
    assert "selector not found" in app_row["error_log"]


def test_submission_failure_handling_and_persistence(tmp_path):
    client = make_client(tmp_path)
    seed_profile(client)

    fill = create_application(client, site_name="submit-error")
    assert fill.status_code == 200
    fill_data = fill.json()
    validate = validate_application(client, fill_data["application_id"], fill_data["filled_fields"])
    assert validate.status_code == 200
    assert validate.json()["status"] == "approved"

    approve = client.post("/approve-application", json={"application_id": fill_data["application_id"]})
    assert approve.status_code == 502
    approve_body = approve.json()
    assert approve_body["status"] == "failed"
    assert "submit operation failed" in approve_body["error"]

    app_row = get_application(client, fill_data["application_id"])
    assert app_row["status"] == "failed"
    assert "submit button click failed" in app_row["error_log"]


def test_validate_application_cannot_submit(tmp_path):
    client = make_client(tmp_path)
    seed_profile(client)
    fill = create_application(client).json()

    validate = validate_application(client, fill["application_id"], fill["filled_fields"])
    assert validate.status_code == 200
    assert validate.json()["status"] == "approved"

    app_row = get_application(client, fill["application_id"])
    assert app_row["status"] != "submitted"


def test_get_applications_sorted_newest_first(tmp_path):
    client = make_client(tmp_path)
    seed_profile(client)

    first = create_application(client).json()
    second = create_application(
        client,
        listing_url="https://internshala.com/job/frontend-intern-2",
    ).json()

    rows = client.get("/applications")
    assert rows.status_code == 200
    applications = rows.json()
    assert len(applications) >= 2
    assert applications[0]["id"] == second["application_id"]
    assert applications[1]["id"] == first["application_id"]
