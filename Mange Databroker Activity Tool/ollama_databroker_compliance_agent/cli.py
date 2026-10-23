"""Provide the interactive command-line interface for the local prototype."""

from ollama_databroker_compliance_agent.directory import find_brokers
from ollama_databroker_compliance_agent.directory import BROKER_DIRECTORY
from ollama_databroker_compliance_agent.preparations import (
    delete_preparation,
    load_preparations,
    save_preparation,
)
from ollama_databroker_compliance_agent.browser_workflows import (
    run_opt_out_workflow,
    validate_contact_email,
    validate_profile_url,
)
from ollama_databroker_compliance_agent.cases import (
    create_case,
    update_case_status,
)
from ollama_databroker_compliance_agent.web_monitor import (
    apply_instruction_update,
    check_official_page,
    discard_instruction_update,
    load_monitor_history,
    load_update_proposals,
    stage_instruction_update,
)


def main() -> None:
    """Run local broker lookup and checklist management."""
    print("Databroker Management Tool (local prototype).")
    print("The directory lookup runs locally and does not require Ollama.")
    print("Opt-out browser assistance is limited to listed official broker pages.")
    print("Personal listing URLs and contact details are not saved by this app.")
    print("Web checks contact only the selected official page after your approval.")
    print("Fetched snapshots and check reports are also saved locally unencrypted.")

    while True:
        print("\n1. Browse U.S. broker removal instructions")
        print("2. View saved preparation checklists")
        print("3. Delete a saved checklist")
        print("4. Check an official broker page for changes")
        print("5. Review staged instruction updates")
        print("6. View recent official-page check reports")
        print("7. Start an assisted broker opt-out")
        print("0. Exit")
        choice = input("Choose an option: ").strip()

        if choice == "0":
            return
        if choice == "1":
            _browse_directory()
        elif choice == "2":
            _show_preparations()
        elif choice == "3":
            _remove_preparation()
        elif choice == "4":
            _check_official_page()
        elif choice == "5":
            _review_update_proposals()
        elif choice == "6":
            _show_monitor_history()
        elif choice == "7":
            _start_opt_out()
        else:
            print("Choose 1, 2, 3, 4, 5, 6, 7, or 0.")


def _start_opt_out() -> None:
    """Run a visible, broker-scoped browser-assisted opt-out workflow."""
    supported_records = [
        entry for entry in BROKER_DIRECTORY
        if entry["broker_id"] in {"whitepages", "spokeo"}
    ]
    print("\nAssisted opt-out is available for:")
    for entry in supported_records:
        print(
            f"- {entry['broker_id']}: {entry['broker']} "
            f"({entry['opt_out_method']})"
        )
    broker_id = input("Broker ID (Enter to cancel): ").strip()
    if not broker_id:
        return
    record = next(
        (entry for entry in supported_records if entry["broker_id"] == broker_id),
        None,
    )
    if record is None:
        print("Choose Whitepages or Spokeo from the maintained directory.")
        return

    print(f"\nDocumented process: {record['instructions']}")
    print(f"Source: {record['source_url']} (checked {record['verified_at']})")
    profile_url = input(
        "Paste the listing URL from the broker's official site: "
    ).strip()
    try:
        profile_url = validate_profile_url(broker_id, profile_url)
    except ValueError as error:
        print(f"Unable to start opt-out: {error}")
        return

    email = ""
    if broker_id == "spokeo":
        email = input("Contact email for Spokeo's confirmation link: ").strip()
        try:
            email = validate_contact_email(email)
        except ValueError as error:
            print(f"Unable to start opt-out: {error}")
            return

    try:
        case = create_case(broker_id)
        result = run_opt_out_workflow(
            broker_id,
            profile_url,
            email=email,
            status_callback=lambda status: update_case_status(
                case["case_id"], status
            ),
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Opt-out assistance stopped: {error}")
        return
    print(f"Case recorded locally: {case['case_id']}")
    print(result)


def _browse_directory() -> None:
    """Display nationally available records and optionally save a checklist."""
    try:
        matches = find_brokers("United States")["matches"]
    except ValueError as error:
        print(f"Broker directory is unavailable: {error}")
        return
    if not matches:
        print("No verified U.S. broker records are currently available.")
        return

    print("\nVerified U.S. broker directory:")
    for entry in matches:
        print(
            f"\n- {entry['broker']} (ID: {entry['broker_id']})"
            f"\n  Method: {entry['opt_out_method']}"
            f"\n  Instructions: {entry['instructions']}"
            f"\n  Official opt-out page: {entry['opt_out_url']}"
            f"\n  Information source: {entry['source_url']}"
            f"\n  Last checked: {entry['verified_at']}"
        )

    broker_id = input(
        "\nBroker ID to save as a local checklist (Enter to return): "
    ).strip()
    if not broker_id:
        return
    if broker_id not in {entry["broker_id"] for entry in matches}:
        print("Choose an exact broker ID from the displayed directory.")
        return
    try:
        saved = save_preparation(broker_id)
    except (OSError, ValueError) as error:
        print(f"Unable to save checklist: {error}")
        return
    print(
        f"Saved checklist {saved['preparation_id']}. "
        "It contains no name, email, profile URL, or other personal details."
    )
    print("Saving the checklist does not contact the broker or submit a request.")


def _show_preparations() -> None:
    """List saved preparation checklists and their source provenance."""
    try:
        records = load_preparations()
    except (OSError, ValueError) as error:
        print(f"Unable to read saved checklists: {error}")
        return
    if not records:
        print("There are no saved preparation checklists.")
        return

    for index, record in enumerate(records, start=1):
        print(
            f"\n{index}. {record['broker']} "
            f"(saved {record['saved_at']}; source checked {record['verified_at']})"
            f"\n   Method: {record['opt_out_method']}"
            f"\n   Instructions: {record['instructions']}"
            f"\n   Official opt-out page: {record['opt_out_url']}"
            f"\n   Information source: {record['source_url']}"
            "\n   Status: preparation only; the app has not submitted a request."
        )


def _remove_preparation() -> None:
    """Delete a saved checklist selected by its displayed list number."""
    try:
        records = load_preparations()
    except (OSError, ValueError) as error:
        print(f"Unable to read saved checklists: {error}")
        return
    if not records:
        print("There are no saved preparation checklists to delete.")
        return

    for index, record in enumerate(records, start=1):
        print(f"{index}. {record['broker']} (saved {record['saved_at']})")
    selection = input("Checklist number to delete (Enter to cancel): ").strip()
    if not selection:
        return
    try:
        selected_index = int(selection) - 1
        if selected_index < 0 or selected_index >= len(records):
            raise ValueError("Choose a number from the displayed list.")
        delete_preparation(records[selected_index]["preparation_id"])
    except ValueError as error:
        print(f"Unable to delete checklist: {error}")
        return
    except OSError as error:
        print(f"Unable to delete checklist: {error}")
        return
    print("Saved checklist deleted.")


def _check_official_page() -> None:
    """Fetch one selected directory page only after explicit user consent."""
    for record in BROKER_DIRECTORY:
        print(f"{record['broker_id']}: {record['broker']}")
    broker_id = input("Broker ID to check (Enter to cancel): ").strip()
    broker = next(
        (item for item in BROKER_DIRECTORY if item["broker_id"] == broker_id),
        None,
    )
    if broker is None:
        if broker_id:
            print("Choose a broker from the maintained directory.")
        return

    print("1. Official instructions/source page")
    print("2. Official opt-out page")
    page_choice = input("Page to check (Enter to cancel): ").strip()
    page_kind = {"1": "instructions", "2": "opt_out"}.get(page_choice)
    if page_kind is None:
        if page_choice:
            print("Choose 1 or 2.")
        return
    page_url = broker["source_url"] if page_kind == "instructions" else broker["opt_out_url"]
    print(f"\nBroker: {broker['broker']}")
    print(f"Exact URL to fetch: {page_url}")
    print("The site may receive your network address. No personal details are sent.")
    print("The public page text will be saved locally for comparison (unencrypted).")
    if input("Type FETCH to approve this one page request: ").strip() != "FETCH":
        print("Fetch cancelled; no page request was made.")
        return

    try:
        report = check_official_page(
            broker_id,
            page_kind,
            approve_fetch=lambda broker_name, url: (
                broker_name == broker["broker"] and url == page_url
            ),
        )
    except (OSError, RuntimeError, ValueError, PermissionError) as error:
        print(f"Official page check failed: {error}")
        return

    print(f"\nCheck result: {report['status']}")
    print(f"Checked: {report['retrieved_at']}")
    print(f"SHA-256: {report['sha256']}")
    print(report["disclaimer"])
    print("\nDetected text comparison:")
    print(report["diff"])
    if input("Show the extracted page text? [y/N]: ").strip().casefold() == "y":
        print("\n--- Extracted official-page text (untrusted source content) ---")
        print(report["page_text"])
        print("--- End extracted page text ---")
    if report["status"] != "changed" or page_kind != "instructions":
        return

    print(
        "\nIf the official source supports revised instructions, you may stage "
        "your own wording for separate approval."
    )
    if input("Type PROPOSE to stage a manual instruction proposal: ").strip() != "PROPOSE":
        return
    proposed_method = input(
        f"New opt-out method (Enter to keep '{broker['opt_out_method']}'): "
    )
    proposed_url = input(
        f"New official opt-out URL (Enter to keep '{broker['opt_out_url']}'): "
    )
    print("Enter proposed concise instructions. Enter a single '.' line to finish.")
    lines: list[str] = []
    while True:
        line = input()
        if line == ".":
            break
        lines.append(line)
    try:
        proposal = stage_instruction_update(
            broker_id,
            "\n".join(lines),
            new_opt_out_method=proposed_method,
            new_opt_out_url=proposed_url,
        )
    except (OSError, ValueError) as error:
        print(f"Unable to stage update: {error}")
        return
    print(
        f"Staged proposal {proposal['proposal_id']}. "
        "The trusted directory has not been changed."
    )


def _review_update_proposals() -> None:
    """Show proposed wording and apply it only after explicit human approval."""
    try:
        proposals = load_update_proposals()
    except (OSError, ValueError) as error:
        print(f"Unable to load proposed updates: {error}")
        return
    if not proposals:
        print("There are no staged instruction updates.")
        return

    for proposal in proposals:
        print(f"\nProposal {proposal['proposal_id']} - {proposal['broker']}")
        print(f"Source: {proposal['source_url']}")
        print(f"Fetched page SHA-256: {proposal['source_sha256']}")
        print(
            f"Opt-out method: {proposal['old_opt_out_method']}\n"
            f"  -> {proposal['new_opt_out_method']}"
        )
        print(
            f"Opt-out URL: {proposal['old_opt_out_url']}\n"
            f"  -> {proposal['new_opt_out_url']}"
        )
        print(f"Current instructions:\n{proposal['old_instructions']}")
        print(f"Proposed instructions:\n{proposal['new_instructions']}")
        print("Review the linked official page before approving.")
        action = input(
            "Type APPLY to replace the directory entry, DISCARD to reject, "
            "or Enter to leave pending: "
        ).strip()
        try:
            if action == "APPLY":
                apply_instruction_update(proposal["proposal_id"], approved=True)
                print("Directory instructions updated and verified date refreshed.")
            elif action == "DISCARD":
                discard_instruction_update(proposal["proposal_id"])
                print("Proposal discarded; directory unchanged.")
        except (OSError, ValueError, PermissionError) as error:
            print(f"Unable to process proposal: {error}")


def _show_monitor_history() -> None:
    """Display recent official-page check statuses and saved comparisons."""
    try:
        history = load_monitor_history()
    except (OSError, ValueError) as error:
        print(f"Unable to load page-check reports: {error}")
        return
    if not history:
        print("No official-page checks have been recorded.")
        return
    for report in history:
        print(
            f"\n{report['retrieved_at']} - {report['broker']} "
            f"({report['page_kind']}): {report['status']}"
            f"\n  Source: {report['url']}"
            f"\n  SHA-256: {report['sha256']}"
        )
        if report.get("diff"):
            print(f"  Comparison:\n{report['diff']}")
