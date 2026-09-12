import json
import shutil
from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass
class BrowserAutomationError(Exception):
    error_type: str
    message: str
    field: str | None = None

    def as_dict(self) -> dict[str, str]:
        data = {"error_type": self.error_type, "message": self.message}
        if self.field:
            data["field"] = self.field
        return data


class WebCmdAdapter(Protocol):
    mode: str

    def search(self, site_name: str, job_type: str, location: str) -> list[dict[str, Any]]:
        ...

    def learn_workflow(self, site_name: str, purpose: str, listing_url: str | None = None) -> dict[str, Any]:
        ...

    def fill(
        self,
        site_name: str,
        listing_url: str,
        workflow_steps: dict[str, Any],
        values: dict[str, str],
    ) -> dict[str, str]:
        ...

    def submit(self, site_name: str, listing_url: str, workflow_steps: dict[str, Any]) -> None:
        ...


def is_webcmd_available() -> bool:
    return shutil.which("webcmd") is not None


class MockWebCmdAdapter:
    mode = "mock"

    def __init__(self) -> None:
        self.learn_counts: dict[tuple[str, str], int] = {}
        self.submit_calls: list[tuple[str, str]] = []

    def _simulate_common_failures(self, listing_url: str) -> None:
        url = listing_url.lower()
        if "timeout" in url:
            raise BrowserAutomationError("timeout", "Browser action timed out")
        if "navigation-fail" in url:
            raise BrowserAutomationError("navigation_failure", "Failed to navigate to job listing")
        if "browser-startup-fail" in url:
            raise BrowserAutomationError("browser_startup_failure", "Browser startup failed")

    def search(self, site_name: str, job_type: str, location: str) -> list[dict[str, Any]]:
        key = site_name.lower().strip() or "internshala"
        listings = {
            "internshala": [
                {
                    "job_title": "Python Backend Intern",
                    "company": "Alpha Labs",
                    "description": "Build APIs with Python FastAPI and SQLite for backend automation projects.",
                    "listing_url": "https://internshala.com/job/python-backend-intern-1",
                    "site_name": "internshala",
                },
                {
                    "job_title": "Frontend Intern",
                    "company": "Beta UI",
                    "description": "Work with JavaScript, HTML, and browser automation integrations.",
                    "listing_url": "https://internshala.com/job/frontend-intern-2",
                    "site_name": "internshala",
                },
                {
                    "job_title": "QA Automation Intern",
                    "company": "Gamma Testing",
                    "description": "Form automation role with unusual layout testing.",
                    "listing_url": "https://internshala.com/job/qa-intern-broken-layout",
                    "site_name": "internshala",
                },
            ],
            "wellfound": [
                {
                    "job_title": "AI Agent Intern",
                    "company": "Delta Agents",
                    "description": "Develop AI agents in Python and integrate LLM APIs.",
                    "listing_url": "https://wellfound.com/jobs/ai-agent-intern-1",
                    "site_name": "wellfound",
                }
            ],
        }
        return listings.get(key, listings["internshala"])

    def learn_workflow(self, site_name: str, purpose: str, listing_url: str | None = None) -> dict[str, Any]:
        key = (site_name.lower(), purpose)
        self.learn_counts[key] = self.learn_counts.get(key, 0) + 1

        if purpose == "search":
            return {
                "search_box": "input[name='q']",
                "job_type_filter": "select[name='job_type']",
                "location_filter": "select[name='location']",
                "results_container": "[data-jobs-list]",
            }
        if purpose == "submit":
            return {"submit_button": "#submit-btn"}

        if purpose == "apply":
            if listing_url and "broken-layout" in listing_url and self.learn_counts[key] > 1:
                return {
                    "name_field": "#name",
                    "email_field": "#email",
                    "resume_field": "#resume",
                    "education_field": "#education-new",
                    "cover_letter_field": "#cover-note",
                    "submit_button": "#submit-btn",
                }
            return {
                "name_field": "#name",
                "email_field": "#email",
                "resume_field": "#resume",
                "education_field": "#education",
                "cover_letter_field": "#cover-note",
                "submit_button": "#submit-btn",
            }

        raise BrowserAutomationError("workflow_failure", f"Unknown workflow purpose: {purpose}")

    def fill(
        self,
        site_name: str,
        listing_url: str,
        workflow_steps: dict[str, Any],
        values: dict[str, str],
    ) -> dict[str, str]:
        self._simulate_common_failures(listing_url)

        if "broken-layout" in listing_url and workflow_steps.get("education_field") != "#education-new":
            raise BrowserAutomationError(
                "selector_not_found",
                "Selector not found for education field",
                field="education",
            )

        required_map = {
            "name": "name_field",
            "email": "email_field",
            "resume": "resume_field",
            "education": "education_field",
            "cover_letter": "cover_letter_field",
        }

        for field, selector_key in required_map.items():
            selector = str(workflow_steps.get(selector_key, "")).strip()
            if not selector:
                raise BrowserAutomationError(
                    "selector_not_found",
                    f"Selector not found for {field}",
                    field=field,
                )

        if "fill-failure" in listing_url:
            raise BrowserAutomationError("fill_failure", "Failed to fill one or more fields")

        return {
            "name": values.get("name", ""),
            "email": values.get("email", ""),
            "resume": values.get("resume", ""),
            "education": values.get("education", ""),
            "cover_letter": values.get("cover_letter", ""),
        }

    def submit(self, site_name: str, listing_url: str, workflow_steps: dict[str, Any]) -> None:
        self._simulate_common_failures(listing_url)
        self.submit_calls.append((site_name, listing_url))

        selector = str(workflow_steps.get("submit_button", "")).strip()
        if not selector:
            raise BrowserAutomationError("selector_not_found", "Selector not found for submit button", field="submit")
        if "submit-error" in listing_url:
            raise BrowserAutomationError("submission_failure", "Submit button click failed")


class RealWebCmdAdapter:
    mode = "real"

    def search(self, site_name: str, job_type: str, location: str) -> list[dict[str, Any]]:
        raise BrowserAutomationError(
            "workflow_failure",
            "webcmd is installed but SafeApply webcmd commands are not configured in this environment",
        )

    def learn_workflow(self, site_name: str, purpose: str, listing_url: str | None = None) -> dict[str, Any]:
        raise BrowserAutomationError(
            "workflow_failure",
            "webcmd is installed but workflow discovery command mapping is not configured",
        )

    def fill(
        self,
        site_name: str,
        listing_url: str,
        workflow_steps: dict[str, Any],
        values: dict[str, str],
    ) -> dict[str, str]:
        raise BrowserAutomationError(
            "fill_failure",
            "webcmd is installed but fill command mapping is not configured",
        )

    def submit(self, site_name: str, listing_url: str, workflow_steps: dict[str, Any]) -> None:
        raise BrowserAutomationError(
            "submission_failure",
            "webcmd is installed but submit command mapping is not configured",
        )


def build_default_adapter() -> WebCmdAdapter:
    if is_webcmd_available():
        return RealWebCmdAdapter()
    return MockWebCmdAdapter()


class Agent1:
    def __init__(
        self,
        adapter: WebCmdAdapter,
        load_workflow: Callable[[str, str], dict[str, Any] | None],
        save_workflow: Callable[[str, str, dict[str, Any]], None],
        mark_workflow_used: Callable[[str, str], None],
    ) -> None:
        self.adapter = adapter
        self._load_workflow = load_workflow
        self._save_workflow = save_workflow
        self._mark_workflow_used = mark_workflow_used

    def _ensure_workflow(self, site_name: str, purpose: str, listing_url: str | None = None) -> tuple[dict[str, Any], bool]:
        workflow = self._load_workflow(site_name, purpose)
        if workflow is not None:
            return workflow.get("steps", workflow), True

        learned_steps = self.adapter.learn_workflow(site_name, purpose, listing_url)
        payload = {"purpose": purpose, "steps": learned_steps}
        self._save_workflow(site_name, purpose, payload)
        return learned_steps, False

    def search(self, site_name: str, job_type: str, location: str) -> dict[str, Any]:
        workflow_steps, reused = self._ensure_workflow(site_name, "search")
        listings = self.adapter.search(site_name, job_type, location)
        if reused:
            self._mark_workflow_used(site_name, "search")
        return {
            "success": True,
            "results": listings,
            "site_name": site_name,
            "mode": self.adapter.mode,
            "workflow_steps": workflow_steps,
        }

    def fill_application(self, job_listing: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        site_name = str(job_listing.get("site_name", "")).strip()
        listing_url = str(job_listing.get("listing_url", "")).strip()
        if not site_name or not listing_url:
            return {
                "success": False,
                "filled_fields": {},
                "field_errors": [
                    {
                        "field": "workflow",
                        "error_type": "workflow_failure",
                        "message": "site_name and listing_url are required",
                    }
                ],
            }

        field_values = {
            "name": str(profile.get("name") or "").strip(),
            "email": str(profile.get("email") or "").strip(),
            "resume": str(profile.get("resume_link") or "").strip(),
            "education": str(profile.get("education") or "").strip(),
            "cover_letter": str(profile.get("cover_letter") or f"Applying with skills: {profile.get('skills', '')}").strip(),
        }

        value_errors = []
        for field_name in ["name", "resume", "education"]:
            if not field_values[field_name]:
                value_errors.append(
                    {
                        "field": field_name,
                        "error_type": "fill_failure",
                        "message": f"Missing value for {field_name}",
                    }
                )

        workflow_steps, reused = self._ensure_workflow(site_name, "apply", listing_url)

        def attempt_fill(steps: dict[str, Any]) -> dict[str, str]:
            return self.adapter.fill(site_name, listing_url, steps, field_values)

        filled_fields: dict[str, str] = {}
        browser_errors: list[dict[str, str]] = []

        try:
            filled_fields = attempt_fill(workflow_steps)
            if reused:
                self._mark_workflow_used(site_name, "apply")
        except BrowserAutomationError as first_error:
            if first_error.error_type == "selector_not_found":
                try:
                    refreshed_steps = self.adapter.learn_workflow(site_name, "apply", listing_url)
                    payload = {"purpose": "apply", "steps": refreshed_steps}
                    self._save_workflow(site_name, "apply", payload)
                    filled_fields = attempt_fill(refreshed_steps)
                    self._mark_workflow_used(site_name, "apply")
                except BrowserAutomationError as second_error:
                    browser_errors.append(
                        {
                            "field": second_error.field or "workflow",
                            "error_type": second_error.error_type,
                            "message": second_error.message,
                        }
                    )
            else:
                browser_errors.append(
                    {
                        "field": first_error.field or "workflow",
                        "error_type": first_error.error_type,
                        "message": first_error.message,
                    }
                )

        errors = value_errors + browser_errors
        return {
            "success": len(errors) == 0,
            "filled_fields": {} if errors else filled_fields,
            "field_errors": errors,
        }

    def submit_application(self, site_name: str, listing_url: str) -> dict[str, Any]:
        workflow_steps, reused = self._ensure_workflow(site_name, "submit", listing_url)

        try:
            self.adapter.submit(site_name, listing_url, workflow_steps)
            if reused:
                self._mark_workflow_used(site_name, "submit")
            return {"success": True, "error": None}
        except BrowserAutomationError as first_error:
            if first_error.error_type == "selector_not_found":
                try:
                    refreshed_steps = self.adapter.learn_workflow(site_name, "submit", listing_url)
                    payload = {"purpose": "submit", "steps": refreshed_steps}
                    self._save_workflow(site_name, "submit", payload)
                    self.adapter.submit(site_name, listing_url, refreshed_steps)
                    self._mark_workflow_used(site_name, "submit")
                    return {"success": True, "error": None}
                except BrowserAutomationError as second_error:
                    return {
                        "success": False,
                        "error": second_error.message,
                        "error_type": second_error.error_type,
                    }

            return {
                "success": False,
                "error": first_error.message,
                "error_type": first_error.error_type,
            }
