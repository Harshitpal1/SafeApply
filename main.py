import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents import Agent1, build_default_adapter


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z0-9]+", text.lower()) if w}


def keyword_overlap_percent(skills_csv: str, description: str) -> int:
    skills = [s.strip().lower() for s in skills_csv.split(",") if s.strip()]
    if not skills:
        return 0
    description_words = normalize_words(description)
    matched = sum(1 for skill in skills if any(part in description_words for part in normalize_words(skill)))
    return round((matched / len(skills)) * 100)


def is_valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


class ProfileIn(BaseModel):
    name: str
    skills: str
    education: str
    resume_link: str
    preferred_job_type: str
    preferred_location: str


class SearchJobsIn(BaseModel):
    site_name: str


class FillApplicationIn(BaseModel):
    job_title: str
    company: str
    site_name: str
    listing_url: str


class ValidateApplicationIn(BaseModel):
    application_id: int
    filled_form_json: dict[str, Any]
    job_description_text: str


class ApproveApplicationIn(BaseModel):
    application_id: int


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS Profile (
            id INTEGER PRIMARY KEY,
            name TEXT,
            skills TEXT,
            education TEXT,
            resume_link TEXT,
            preferred_job_type TEXT,
            preferred_location TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS LearnedWorkflows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_name TEXT,
            workflow_steps TEXT,
            created_at TEXT,
            last_used_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS Applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_title TEXT,
            company TEXT,
            site_name TEXT,
            match_score INTEGER,
            status TEXT,
            flag_reason TEXT,
            error_log TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()


def create_app(db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="SafeApply")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    base_dir = Path(__file__).resolve().parent
    static_dir = base_dir / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    resolved_db = db_path or str(base_dir / "safeapply.db")

    def get_conn() -> sqlite3.Connection:
        conn = sqlite3.connect(resolved_db)
        conn.row_factory = sqlite3.Row
        return conn

    with get_conn() as conn:
        create_tables(conn)

    def upsert_workflow(site_name: str, purpose: str, workflow_payload: dict[str, Any]) -> None:
        now = utc_now()
        payload = json.dumps(workflow_payload)
        with get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM LearnedWorkflows WHERE site_name = ? AND json_extract(workflow_steps, '$.purpose') = ?",
                (site_name, purpose),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE LearnedWorkflows SET workflow_steps = ?, last_used_at = ? WHERE id = ?",
                    (payload, now, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO LearnedWorkflows(site_name, workflow_steps, created_at, last_used_at) VALUES (?, ?, ?, ?)",
                    (site_name, payload, now, now),
                )
            conn.commit()

    def load_workflow(site_name: str, purpose: str) -> dict[str, Any] | None:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT workflow_steps FROM LearnedWorkflows WHERE site_name = ? AND json_extract(workflow_steps, '$.purpose') = ?",
                (site_name, purpose),
            ).fetchone()
            if not row:
                return None
            return json.loads(row["workflow_steps"])

    def mark_workflow_used(site_name: str, purpose: str) -> None:
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE LearnedWorkflows
                SET last_used_at = ?
                WHERE site_name = ? AND json_extract(workflow_steps, '$.purpose') = ?
                """,
                (utc_now(), site_name, purpose),
            )
            conn.commit()

    def get_profile() -> sqlite3.Row | None:
        with get_conn() as conn:
            return conn.execute("SELECT * FROM Profile WHERE id = 1").fetchone()

    agent1 = Agent1(
        adapter=build_default_adapter(),
        load_workflow=load_workflow,
        save_workflow=upsert_workflow,
        mark_workflow_used=mark_workflow_used,
    )

    def search_jobs(site_name: str, job_type: str, location: str) -> dict[str, Any]:
        return agent1.search(site_name, job_type, location)

    def fill_application(site_name: str, listing_url: str, profile_data: sqlite3.Row) -> dict[str, Any]:
        profile_dict = dict(profile_data)
        return agent1.fill_application({"site_name": site_name, "listing_url": listing_url}, profile_dict)

    def submit_application(site_name: str, listing_url: str) -> tuple[bool, str | None]:
        result = agent1.submit_application(site_name, listing_url)
        return bool(result["success"]), result.get("error")

    def validate_application(
        filled_form_json: dict[str, Any],
        job_description_text: str,
        profile_skills: str,
    ) -> dict[str, str]:
        required_fields = ["name", "education", "resume_link"]
        for field in required_fields:
            value = str(filled_form_json.get(field, "")).strip()
            if not value:
                return {"status": "flagged", "reason": f"Required field '{field}' is empty."}

        resume_link = str(filled_form_json.get("resume_link", "")).strip()
        if not is_valid_url(resume_link):
            return {"status": "flagged", "reason": "Resume link is malformed and must be a valid URL."}

        match_score = keyword_overlap_percent(profile_skills, job_description_text)
        if match_score < 30:
            return {"status": "flagged", "reason": "Skill match is below 30%, indicating a low-fit application."}

        if len(str(filled_form_json.get("name", "")).strip()) < 2:
            return {"status": "flagged", "reason": "Candidate name appears invalid or nonsensical."}

        return {"status": "approved"}

    @app.get("/")
    def root() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.post("/profile")
    def upsert_profile(profile: ProfileIn) -> dict[str, str]:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO Profile(id, name, skills, education, resume_link, preferred_job_type, preferred_location)
                VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name = excluded.name,
                  skills = excluded.skills,
                  education = excluded.education,
                  resume_link = excluded.resume_link,
                  preferred_job_type = excluded.preferred_job_type,
                  preferred_location = excluded.preferred_location
                """,
                (
                    profile.name,
                    profile.skills,
                    profile.education,
                    profile.resume_link,
                    profile.preferred_job_type,
                    profile.preferred_location,
                ),
            )
            conn.commit()
        return {"message": "Profile saved"}

    @app.get("/profile")
    def read_profile() -> dict[str, Any]:
        row = get_profile()
        if not row:
            return {}
        return dict(row)

    @app.post("/search-jobs")
    def search_jobs_endpoint(payload: SearchJobsIn) -> list[dict[str, Any]]:
        profile = get_profile()
        if not profile:
            raise HTTPException(status_code=400, detail="Profile not found")

        search_result = search_jobs(payload.site_name, profile["preferred_job_type"], profile["preferred_location"])
        listings = search_result["results"]
        out = []
        for listing in listings:
            match_score = keyword_overlap_percent(profile["skills"], listing["description"])
            out.append(
                {
                    "job_title": listing["job_title"],
                    "company": listing["company"],
                    "match_score": match_score,
                    "listing_url": listing["listing_url"],
                    "description": listing["description"],
                    "site_name": listing.get("site_name", payload.site_name),
                    "source_mode": search_result["mode"],
                }
            )
        return out

    @app.post("/fill-application")
    def fill_application_endpoint(payload: FillApplicationIn) -> dict[str, Any]:
        profile = get_profile()
        if not profile:
            raise HTTPException(status_code=400, detail="Profile not found")

        fill_result = fill_application(payload.site_name, payload.listing_url, profile)
        filled_fields = dict(fill_result["filled_fields"])
        if "resume" in filled_fields and "resume_link" not in filled_fields:
            filled_fields["resume_link"] = filled_fields["resume"]
        if "cover_letter" in filled_fields and "cover_note" not in filled_fields:
            filled_fields["cover_note"] = filled_fields["cover_letter"]

        field_errors = list(fill_result["field_errors"])
        description = ""
        search_result = search_jobs(payload.site_name, profile["preferred_job_type"], profile["preferred_location"])
        for job in search_result["results"]:
            if job["listing_url"] == payload.listing_url:
                description = job["description"]
                break
        match_score = keyword_overlap_percent(profile["skills"], description) if description else 0
        now = utc_now()

        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO Applications(job_title, company, site_name, match_score, status, flag_reason, error_log, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', NULL, NULL, ?, ?)
                """,
                (payload.job_title, payload.company, payload.site_name, match_score, now, now),
            )
            application_id = cur.lastrowid
            conn.commit()

        return {
            "application_id": application_id,
            "job_title": payload.job_title,
            "company": payload.company,
            "site_name": payload.site_name,
            "listing_url": payload.listing_url,
            "filled_fields": filled_fields,
            "field_errors": field_errors,
            "success": fill_result["success"],
            "automation_mode": search_result["mode"],
        }

    @app.post("/validate-application")
    def validate_application_endpoint(payload: ValidateApplicationIn) -> dict[str, str]:
        profile = get_profile()
        if not profile:
            raise HTTPException(status_code=400, detail="Profile not found")

        with get_conn() as conn:
            existing = conn.execute("SELECT id FROM Applications WHERE id = ?", (payload.application_id,)).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Application not found")

        verdict = validate_application(payload.filled_form_json, payload.job_description_text, profile["skills"])

        with get_conn() as conn:
            if verdict["status"] == "approved":
                conn.execute(
                    "UPDATE Applications SET status = 'approved', flag_reason = NULL, updated_at = ? WHERE id = ?",
                    (utc_now(), payload.application_id),
                )
            else:
                conn.execute(
                    "UPDATE Applications SET status = 'flagged', flag_reason = ?, updated_at = ? WHERE id = ?",
                    (verdict["reason"], utc_now(), payload.application_id),
                )
            conn.commit()

        return verdict

    @app.post("/approve-application")
    def approve_application_endpoint(payload: ApproveApplicationIn) -> dict[str, Any]:
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM Applications WHERE id = ?", (payload.application_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Application not found")

        listing_url = f"https://{row['site_name']}.example/apply/{row['id']}"
        success, error = submit_application(row["site_name"], listing_url)

        with get_conn() as conn:
            if success:
                conn.execute(
                    "UPDATE Applications SET status = 'submitted', error_log = NULL, updated_at = ? WHERE id = ?",
                    (utc_now(), payload.application_id),
                )
            else:
                conn.execute(
                    "UPDATE Applications SET status = 'failed', error_log = ?, updated_at = ? WHERE id = ?",
                    (error, utc_now(), payload.application_id),
                )
            conn.commit()

        return {"application_id": payload.application_id, "status": "submitted" if success else "failed", "error": error}

    @app.get("/applications")
    def list_applications() -> list[dict[str, Any]]:
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM Applications ORDER BY updated_at DESC").fetchall()
            return [dict(r) for r in rows]

    return app


app = create_app()
