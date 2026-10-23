"""Run narrowly scoped, visible browser-assisted broker opt-out workflows."""

import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal, Protocol
from urllib.parse import urlsplit

from ollama_databroker_compliance_agent.directory import (
    BROKER_DIRECTORY,
    BrokerRecord,
)
from ollama_databroker_compliance_agent.cases import CaseStatus


class _Locator(Protocol):
    """Browser control operations used by the broker-specific workflows."""

    def count(self) -> int: ...

    def fill(self, value: str) -> None: ...

    def input_value(self) -> str: ...

    def is_enabled(self) -> bool: ...

    def click(self) -> None: ...

    def inner_text(self, *, timeout: float | None = None) -> str: ...


class _Page(Protocol):
    """Small typed surface of the visible browser page."""

    @property
    def url(self) -> str: ...

    @property
    def main_frame(self) -> object: ...

    def get_by_role(
        self,
        role: Literal["textbox", "button"],
        *,
        name: str | re.Pattern[str],
    ) -> _Locator: ...

    def locator(self, selector: str) -> _Locator: ...

    def route(self, url: str, handler: Callable[..., None]) -> object: ...


class _Request(Protocol):
    """Navigation metadata used to prevent cross-host top-level redirects."""

    url: str
    frame: object

    def is_navigation_request(self) -> bool: ...


class _Route(Protocol):
    """Route continuation controls used by the host-navigation guard."""

    request: _Request

    def abort(self) -> None: ...

    def continue_(self) -> None: ...


def validate_profile_url(broker_id: str, profile_url: str) -> str:
    """Validate a user-provided listing URL against the selected broker host."""
    record = _broker_record(broker_id)
    normalized_url = profile_url.strip()
    parsed_url = urlsplit(normalized_url)
    official_host = urlsplit(record["opt_out_url"]).hostname
    profile_host = parsed_url.hostname
    if (
        parsed_url.scheme != "https"
        or len(normalized_url) > 2_048
        or profile_host is None
        or official_host is None
        or profile_host.casefold() != official_host.casefold()
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.port not in (None, 443)
        or parsed_url.query
        or parsed_url.fragment
        or not parsed_url.path.strip("/")
    ):
        raise ValueError(
            f"Enter a listing URL from the official {record['broker']} website."
        )
    return normalized_url


def validate_contact_email(email: str) -> str:
    """Validate and normalize the contact email required by Spokeo."""
    normalized_email = email.strip()
    if len(normalized_email) > 254 or not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized_email
    ):
        raise ValueError("Enter a valid email address.")
    return normalized_email


def run_opt_out_workflow(
    broker_id: str,
    profile_url: str,
    *,
    email: str = "",
    input_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], None] | None = None,
    status_callback: Callable[[CaseStatus], None] | None = None,
    user_authorized: bool = False,
) -> str:
    """Fill supported official form fields and pause at human-required steps.

    This workflow uses a fresh visible browser context and does not save
    profile URLs, email addresses, browser state, or page contents.
    """
    prompt = input if input_fn is None else input_fn
    write = print if output_fn is None else output_fn
    record = _broker_record(broker_id)
    normalized_profile_url = validate_profile_url(broker_id, profile_url)
    normalized_email = (
        validate_contact_email(email) if broker_id == "spokeo" else ""
    )

    write(f"Official destination: {record['opt_out_url']}")
    write(f"Information entered into the broker form: listing URL")
    if broker_id == "spokeo":
        write("Information entered into the broker form: contact email")
    write(
        "The browser is visible. The broker will receive the submitted fields "
        "and may receive your network address. Details are not sent to Ollama "
        "or saved by this application."
    )
    if not user_authorized and prompt(
        "Type START to open the official form and enter these fields: "
    ).strip() != "START":
        return "Cancelled; no broker page was opened."

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Browser automation is not installed. Install project requirements "
            "and Chromium as described in the README."
        ) from error

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            try:
                page = browser.new_page()
                _install_navigation_guard(page, record)
                page.goto(record["opt_out_url"], wait_until="domcontentloaded")
                _require_official_origin(page.url, record)
                if broker_id == "spokeo":
                    return run_spokeo_form(
                        page,
                        normalized_profile_url,
                        normalized_email,
                        prompt,
                        write,
                        status_callback,
                    )
                return run_whitepages_form(
                    page, normalized_profile_url, prompt, write, status_callback
                )
            finally:
                browser.close()
    except PlaywrightError as error:
        raise RuntimeError(f"Official broker browser workflow failed: {error}") from error


def recheck_profile_listing(
    broker_id: str,
    profile_url: str,
    confirm_observation: Callable[[str], str],
) -> dict[str, str]:
    """Open a user-selected official listing visibly and record their observation."""
    record = _broker_record(broker_id)
    normalized_profile_url = validate_profile_url(broker_id, profile_url)
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Browser automation is not installed. Install project requirements "
            "and Chromium as described in the README."
        ) from error

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            try:
                page = browser.new_page()
                _install_navigation_guard(page, record)
                page.goto(normalized_profile_url, wait_until="domcontentloaded")
                _require_official_origin(page.url, record)
                page.locator("body").inner_text(timeout=10_000)
                observation = confirm_observation(page.url)
                if observation not in {
                    "user_reports_present",
                    "user_reports_not_observed",
                    "uncertain",
                }:
                    raise ValueError("Choose a supported listing observation.")
                return {
                    "broker": record["broker"],
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "observation": observation,
                    "final_url": page.url,
                    "message": (
                        "The official listing page loaded in a visible browser. "
                        "The outcome records the user's visual observation; "
                        "a page load or absent result is not independent proof "
                        "of deletion or legal compliance."
                    ),
                }
            finally:
                browser.close()
    except PlaywrightError as error:
        raise RuntimeError(f"Official listing recheck failed: {error}") from error


def run_spokeo_form(
    page: _Page,
    profile_url: str,
    email: str,
    prompt: Callable[[str], str],
    write: Callable[[str], None],
    status_callback: Callable[[CaseStatus], None] | None = None,
) -> str:
    """Fill Spokeo's reviewed initial form and require human CAPTCHA action."""
    url_field = page.get_by_role("textbox", name="Enter URL here")
    email_field = page.get_by_role("textbox", name="Enter email address here")
    if url_field.count() != 1 or email_field.count() != 1:
        raise RuntimeError(
            "The Spokeo form no longer matches its reviewed fields. "
            "No form submission was attempted."
        )
    url_field.fill(profile_url)
    email_field.fill(email)
    if status_callback is not None:
        status_callback("awaiting_user_verification")

    captcha_frame = page.locator('iframe[title*="reCAPTCHA"]')
    captcha_response = page.locator('textarea[name="g-recaptcha-response"]')
    if captcha_frame.count() == 0 or captcha_response.count() != 1:
        write(
            "The expected CAPTCHA control was not available to verify. "
            "Complete the official form manually; the agent will not submit it."
        )
        return "Stopped for manual verification; submission was not attempted."
    write(
        "The official form is filled. Complete the CAPTCHA yourself in the "
        "visible browser; the agent will not interact with CAPTCHA."
    )
    if prompt("After the CAPTCHA is complete, type READY to submit: ").strip() != "READY":
        return "Stopped before submission; the form was not submitted."
    if not captcha_response.input_value().strip():
        return (
            "The CAPTCHA is not confirmed as complete. The form remains "
            "unsubmitted; finish the official process manually."
        )

    submit_button = page.get_by_role("button", name=re.compile("OPT OUT", re.IGNORECASE))
    if submit_button.count() != 1 or not submit_button.is_enabled():
        return (
            "The expected submit control is unavailable. The form remains "
            "unsubmitted; finish the official process manually."
        )
    submit_button.click()
    if status_callback is not None:
        status_callback("submission_initiated")
    write(
        "The submit action was initiated. Spokeo requires email confirmation; "
        "open its message and click the confirmation link yourself. This app "
        "does not verify removal."
    )
    return "Submission initiated; email confirmation and removal are unverified."


def run_whitepages_form(
    page: _Page,
    profile_url: str,
    prompt: Callable[[str], str],
    write: Callable[[str], None],
    status_callback: Callable[[CaseStatus], None] | None = None,
) -> str:
    """Enter the Whitepages listing URL and hand off its multi-step process."""
    url_field = page.get_by_role(
        "textbox", name="Copy and paste the URL of your profile"
    )
    next_button = page.get_by_role("button", name="Next")
    if url_field.count() != 1 or next_button.count() != 1:
        raise RuntimeError(
            "The Whitepages form no longer matches its reviewed first step. "
            "No form submission was attempted."
        )
    url_field.fill(profile_url)
    next_button.click()
    _require_official_origin(page.url, _broker_record("whitepages"))
    if status_callback is not None:
        status_callback("in_progress")
    write(
        "The listing URL was entered and the first form step was advanced. "
        "Whitepages has a multi-step process and may require telephone "
        "verification. Complete those steps yourself in the visible browser."
    )
    prompt("Press Enter after finishing or closing the Whitepages form: ")
    return (
        "Whitepages form opened and first step advanced. Further steps and "
        "submission were not verified by this application."
    )


def _broker_record(broker_id: str) -> BrokerRecord:
    """Return a maintained broker record or reject the selection."""
    record = next(
        (entry for entry in BROKER_DIRECTORY if entry["broker_id"] == broker_id),
        None,
    )
    if record is None or broker_id not in {"whitepages", "spokeo"}:
        raise ValueError("Choose Whitepages or Spokeo from the maintained directory.")
    return record


def _require_official_origin(current_url: str, record: BrokerRecord) -> None:
    """Stop if the official opt-out page redirects to a different host."""
    if not _is_official_origin(current_url, record):
        raise RuntimeError(
            "The broker page redirected outside its maintained official host. "
            "No form fields were entered."
        )


def _install_navigation_guard(page: _Page, record: BrokerRecord) -> None:
    """Block top-level navigation outside the maintained official host."""
    def guard(route: _Route, request: _Request) -> None:
        if (
            request.is_navigation_request()
            and request.frame == page.main_frame
            and not _is_official_origin(request.url, record)
        ):
            route.abort()
            return
        route.continue_()

    page.route("**/*", guard)


def _is_official_origin(url: str, record: BrokerRecord) -> bool:
    current = urlsplit(url)
    official = urlsplit(record["opt_out_url"])
    return (
        current.scheme == "https"
        and current.hostname is not None
        and official.hostname is not None
        and current.hostname.casefold() == official.hostname.casefold()
        and current.port in (None, 443)
        and current.username is None
        and current.password is None
    )
