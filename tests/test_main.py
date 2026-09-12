import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from main import create_app


def make_client(tmp_path):
    db_path = tmp_path / "test.db"
    app = create_app(str(db_path))
    return TestClient(app), db_path


def get_conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


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
    client, _ = make_client(tmp_path)
    seed_profile(client)

    data = client.get("/profile").json()
    assert data["id"] == 1
    assert data["name"] == "Harshit"
    assert data["skills"] == "python,fastapi,javascript"
    assert data["education"] == "B.Tech"
    assert data["resume_link"] == "https://example.com/resume.pdf"
    assert data["preferred_job_type"] == "intern"
    assert data["preferred_location"] == "remote"


def test_search_jobs_returns_match_score(tmp_path):
    client, _ = make_client(tmp_path)
    seed_profile(client)

    res = client.post("/search-jobs", json={"site_name": "internshala"})
    assert res.status_code == 200
    jobs = res.json()
    assert jobs
    assert {"job_title", "company", "match_score", "listing_url"}.issubset(jobs[0])


def test_fill_validate_approve_flow(tmp_path):
    client, _ = make_client(tmp_path)
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
    client, _ = make_client(tmp_path)
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


def test_fresh_db_initializes_expected_schema(tmp_path):
    _, db_path = make_client(tmp_path)

    with get_conn(db_path) as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert tables == {"Profile", "LearnedWorkflows", "Applications"}

        profile_cols = [r["name"] for r in conn.execute("PRAGMA table_info(Profile)").fetchall()]
        workflows_cols = [r["name"] for r in conn.execute("PRAGMA table_info(LearnedWorkflows)").fetchall()]
        applications_cols = [r["name"] for r in conn.execute("PRAGMA table_info(Applications)").fetchall()]

        assert profile_cols == [
            "id",
            "name",
            "skills",
            "education",
            "resume_link",
            "preferred_job_type",
            "preferred_location",
        ]
        assert workflows_cols == ["id", "site_name", "workflow_steps", "created_at", "last_used_at"]
        assert applications_cols == [
            "id",
            "job_title",
            "company",
            "site_name",
            "match_score",
            "status",
            "flag_reason",
            "error_log",
            "created_at",
            "updated_at",
        ]


def test_learned_workflows_fields_and_workflow_steps_json(tmp_path):
    client, db_path = make_client(tmp_path)
    seed_profile(client)

    res = client.post("/search-jobs", json={"site_name": "internshala"})
    assert res.status_code == 200

    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM LearnedWorkflows WHERE site_name = ?", ("internshala",)).fetchone()
        assert row is not None
        assert row["id"] > 0
        assert row["created_at"]
        assert row["last_used_at"]
        assert conn.execute("SELECT json_valid(?)", (row["workflow_steps"],)).fetchone()[0] == 1
        payload = json.loads(row["workflow_steps"])
        assert payload["purpose"] == "search"
        assert isinstance(payload["steps"], dict)

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO LearnedWorkflows(site_name, workflow_steps, created_at, last_used_at)
                VALUES (?, ?, ?, ?)
                """,
                ("internshala", "{bad json", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )


def test_applications_fields_status_values_and_timestamps(tmp_path):
    client, db_path = make_client(tmp_path)
    seed_profile(client)

    fill = client.post(
        "/fill-application",
        json={
            "job_title": "Python Backend Intern",
            "company": "Alpha Labs",
            "site_name": "internshala",
            "listing_url": "https://internshala.com/job/python-backend-intern-1",
        },
    )
    assert fill.status_code == 200
    application_id = fill.json()["application_id"]

    with get_conn(db_path) as conn:
        created = conn.execute("SELECT * FROM Applications WHERE id = ?", (application_id,)).fetchone()
        assert created is not None
        assert created["job_title"] == "Python Backend Intern"
        assert created["company"] == "Alpha Labs"
        assert created["site_name"] == "internshala"
        assert created["status"] == "pending"
        assert created["flag_reason"] is None
        assert created["error_log"] is None
        created_at = created["created_at"]
        initial_updated_at = created["updated_at"]
        assert created_at
        assert initial_updated_at

    validate = client.post(
        "/validate-application",
        json={
            "application_id": application_id,
            "filled_form_json": fill.json()["filled_fields"],
            "job_description_text": "python fastapi javascript backend role",
        },
    )
    assert validate.status_code == 200
    assert validate.json()["status"] == "approved"

    with get_conn(db_path) as conn:
        validated = conn.execute("SELECT * FROM Applications WHERE id = ?", (application_id,)).fetchone()
        assert validated["status"] == "approved"
        assert validated["updated_at"] != initial_updated_at
        assert datetime.fromisoformat(validated["updated_at"]) >= datetime.fromisoformat(created_at)

        now = "2026-01-01T00:00:00+00:00"
        for status in ["pending", "flagged", "approved", "submitted", "failed"]:
            conn.execute(
                """
                INSERT INTO Applications(job_title, company, site_name, match_score, status, flag_reason, error_log, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("Role", "Company", "site", 10, status, None, None, now, now),
            )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO Applications(job_title, company, site_name, match_score, status, flag_reason, error_log, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("Role", "Company", "site", 10, "invalid-status", None, None, now, now),
            )
