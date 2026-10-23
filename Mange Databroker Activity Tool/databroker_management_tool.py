"""Launch the Databroker Management Tool desktop or command-line interface."""

import argparse


def main() -> None:
    """Run the desktop app by default, with an optional CLI mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cli",
        action="store_true",
        help="run the command-line interface instead of the desktop app",
    )
    options = parser.parse_args()

    if options.cli:
        from ollama_databroker_compliance_agent.cli import main as cli_main

        cli_main()
    else:
        from ollama_databroker_compliance_agent.desktop import main as desktop_main

        desktop_main()


if __name__ == "__main__":
    main()
