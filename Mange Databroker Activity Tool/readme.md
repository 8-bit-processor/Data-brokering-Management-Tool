# Databroker Management Tool

This project is at the beginning of development. Its intended purpose is to
help ordinary citizens understand and organize information about commercial
data brokers, their handling of personal data, and possible avenues for
recourse. The longer-term goal is to help users build an evidence-based case
file and prepare questions and materials for review by a professional
attorney.

The primary user experience is intended to be an agent-chat concierge that
educates the user, coordinates mature module tools, and handles supported
legwork with clear explanations and appropriate approval pauses. The desktop
includes an initial local concierge chat, a limited approval-gated public
broker search, and visible actions for two supported brokers; it does not yet
coordinate all modules or provide comprehensive broker coverage.

## Project documents

- [ROADMAP.md](./ROADMAP.md) records the agreed project scope, shared rules,
  module boundaries, and plain-English workflows.
- `ollama_databroker_compliance_agent/todo` describes the broker compliance,
  discovery, and opt-out preparation module.
- `agent_ollama_data_mishandling_damages_expert/todo` describes evidence-led
  impact analysis and legal research for attorney review.
- `repeated_broker_conduct_tracker/todo` describes records and timelines for
  possible repeated broker conduct after a user's notice.

These documents are planning notes, not promises that the features already
exist. Update them when the project owner clarifies scope or priorities.

## Intended public-repository role

This is unfinished work intended to become a clear, modular boilerplate that
others can inspect, fork, and adapt for their own privacy-focused projects.
It is not a finished product, legal service, or claim of complete privacy or
regulatory compliance. Forkers should be able to understand which parts are
shared framework, which belong to individual modules, what is implemented,
and what remains a planning item.

MIT has been selected as the intended license, with an anonymous copyright
notice. An anonymous notice avoids publishing a person's name; it does not
establish rights ownership or mean that copyright does not apply. Confirm that
the person publishing the project has the authority to license its contents.

## Requirements and run

- Python 3.10 or later.
- Playwright and its Chromium browser are required for assisted opt-out forms.
- Ollama is optional for the command-line broker directory. Other ReAct agent
  workflows require Ollama running locally at `127.0.0.1:11434` and a model
  such as `mistral:7b` (or one selected with `OLLAMA_MODEL`).

To use the optional ReAct agents, pull a local model once:

```powershell
ollama pull mistral:7b
```

From the project folder, launch the desktop app:

```powershell
python databroker_management_tool.py
```

To run the command-line interface:

```powershell
python databroker_management_tool.py --cli
```

Install the browser-assistance dependency and its visible Chromium browser
before using the assisted opt-out option:

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

The CLI searches the maintained local directory directly; it does not send a
region or personal information to Ollama. The initial directory contains
Whitepages and Spokeo listing-removal instructions, checked against their
official sources on 2026-10-22. It can fetch one of a broker's listed official
pages after you approve the exact URL, then report a text comparison against
the last approved local fetch. This page-monitoring feature does not search
the wider web or submit opt-out requests.

## Current foundation

The desktop keeps a local Ollama concierge chat visible beside every app tab.
It can explain broker concepts and use read-only local tools to look up the manually vetted directory,
the reviewed public-source inventory, and an imported California candidate
snapshot. It keeps conversation history only in memory and does not save chat
transcripts. On a direct request for general broker research, it can search
fixed public topics through Tavily after showing the exact query and asking for
approval. The app sends no chat history, case information, or user identifiers
in these searches, but Tavily receives the query and network request metadata.
Individual footprint searches are not available. Search findings are leads
shown in chat; they are not yet saved as candidate records or maintained as a
broker inventory. Broad cross-module delegation remains unimplemented.
The assistant can use supported app tools and limited, approval-gated public
broker searches; it does not have unrestricted internet access. It can explain
general privacy concepts and summarize available public legal sources, but
verified jurisdiction-specific legal research is not currently configured.
It is not a lawyer and does not claim knowledge or judgment superior to an
attorney.
On each message, the assistant also receives relevant visible content from
the selected in-app tab automatically; no extra permission prompt is required.
The local directory, source details, selected registry candidate, or selected
case metadata may be included as applicable. Listing/contact form fields and
imported evidence contents are excluded. Context is bounded and treated as
untrusted data, not instructions. It goes to the local Ollama model and is not
saved as a transcript.
For a selected public source, **Fetch page and discuss** loads bounded visible
text on demand, strips scripts and embedded content, and asks the concierge to
explain the page. The fetched text is held in memory and included in local
Ollama prompts until the user clears page context or closes the app; it is not
saved to disk or sent to Tavily. The fetch is limited to a 512 KB response and
12,000 characters of page context. This is a targeted user-requested page
fetch, not an embedded browser or general-purpose crawler.
The concierge is designed to educate users about potential safety and scam
risks, and how personal data may contribute to profiling or decisions affecting
employment, sales, eligibility, offers, prices, or citizen scoring and grading.
It presents these as possible concerns, not assumed or proven outcomes, and
does so without fear-based pressure or unsupported claims.
When the user asks for focused education about these risks or their potential
impacts, the concierge can consult the local privacy impact analysis specialist.
If the user asks that specialist to inspect case evidence, a separate approval
is required before it can read supported text files and the user-entered
timeline from the selected case's local workspace. Case data remains
unencrypted, and the specialist
must state its clearest supported conclusion, evidence basis, confidence, and
material limits. It can provide preliminary factual and impact conclusions,
but not a legal ruling or established monetary damages assessment.
It can also summarize local opt-out case statuses as a simple progress report.
When the user explicitly asks, it can record a status the user reports in the
saved case record.
With a direct current-turn request naming Whitepages or Spokeo, it can run the
existing visible broker form or open a user-provided listing for a user-reviewed
recheck. CAPTCHA, identity checks, email confirmation, and any remaining broker
steps stay with the user. For a selected saved case, the user may also choose a
supported text evidence file and approve sending its contents to local Ollama
for analysis; the file is copied into the unencrypted local case workspace.
These operations report progress and evidence, not a legal compliance finding.
An absent listing or a stored evidence fingerprint alone is not proof that a
broker complied.
The My requests tab also lets the user create a case-local impact timeline.
Entries are explicitly user-reported, can be linked to already imported
originals by path and SHA-256, and can record the user's description of the
item, source, creation/receipt date, sender, recipient, and relationship to an
event. Corrections are appended and linked to the earlier event rather than
silently replacing it. These are user reports; evidence links and dates are not
independently verified. Timeline details are stored unencrypted in the case
workspace. The user can preview a factual attorney-preparation draft containing
the timeline, a bounded evidence metadata index, questions for counsel, and
limitations. The draft excludes evidence contents and is saved locally as a
new derived file only after explicit approval; it does not include verified
legal research or agent conclusions.
When discussing legal protections, the expert must not assume that the
jurisdiction with the strongest rules governs the user. It can use that
jurisdiction only as a labeled comparison, explain uncertainty about local
protections, and offer to help prepare neutral educational material or
questions for local lawmakers.
The case timeline also has a direct action to ask the privacy impact specialist a
case-specific question; it uses the same separate approval for workspace
review and displays the preliminary conclusion in its own window.
It can explain general reasons privacy laws may provide rights, but does not
provide jurisdiction-specific legal research. Listing checks are limited to a
user-provided Whitepages or Spokeo URL with the user's visible confirmation;
the app cannot discover listings or independently verify their absence.
Directory and registry results must not be presented as that person's footprint.
The user can switch to existing app tabs for supported research references,
California registry candidate import, local case tracking, and visible
Whitepages/Spokeo assistance.

The local desktop app also shows manually vetted broker records, explains their
documented removal processes, launches supported official-site workflows,
tracks follow-up dates, and records case status and evidence fingerprints. Its broker directory
currently contains only Whitepages and Spokeo; coverage is incomplete. The
app does not automatically find a user's listing, maintain a complete broker
census, research law, or assess damages. General public web search is available
only for fixed broker research topics after explicit per-query approval; it
does not search for people. Assisted opt-out opens a fresh visible
browser at the selected broker's maintained official page. For Spokeo, the
app fills the listing URL and contact email, then pauses for the user to solve
the CAPTCHA before initiating submission. Spokeo email confirmation remains
a user step. For Whitepages, the app enters the listing URL and advances the
first step; the remaining multi-step process and any telephone verification
are user controlled. The app does not claim removal or legal compliance.

The **Coverage and sources** tab records four reviewed official California,
Oregon, and Texas sources, including California's DROP portal. These are
source references, not themselves imported broker records. After explicit
user initiation by clicking **Refresh California registry**, the **Registry
candidates** tab downloads California's public registration CSV and stores a
local candidate snapshot. The registry site receives normal connection
metadata; no personal data or search query is sent. It retains only
registered business names, DBAs, and registrant-listed websites; contact
details and sensitive-practice disclosures are discarded. Those registry
entries are not promoted to the actionable directory or treated as verified
opt-out instructions. Oregon and Texas rosters are not imported. Candidate
snapshots are unencrypted local JSON. The broker-specific directory remains
two U.S. people-search services, and no international discovery source
inventory or all-sector broker census is implemented. The intended discovery
scope includes commercial data brokerage across sectors and jurisdictions;
this remains an expansion goal, not a claim of comprehensive coverage.

Listing URLs and contact email are entered locally, used only in the active
browser workflow, and not sent to Ollama or saved by this app. The fields
remain in memory only while the workflow is active and are cleared from the
desktop form when it finishes. The broker receives the fields the user
submits and may receive the user's network address. The visible browser uses
a fresh context; users must complete any CAPTCHA, telephone verification,
email confirmation, or other required human step themselves. A successful
click is not proof that the broker received, acknowledged, or completed the
request.

## Case tracking and evidence

The desktop app stores local JSON metadata under the user's application-data
directory. Case records include broker, generated case ID, status history,
timestamps, reminder date, evidence category, and SHA-256 fingerprint. They do
not save the listing URL, contact email, evidence filename, or evidence file contents.
Selected evidence files are read locally to calculate a fingerprint and stay
where the user stored them. Case JSON is not encrypted.

Status changes made in the case tracker are user-reported unless produced by
the browser workflow. "Submission initiated" does not mean a broker
acknowledged or processed the request. A removal status means only that the
user reported that result; the app does not independently verify it. Users
can update a case, fingerprint evidence, or delete its metadata.

Live page checks remain limited to explicit checks of official pages already
in the broker directory. The California candidate import downloads only the
public registration CSV when the user clicks refresh and does not search for
the user's personal information.
The directory is incomplete: a broker missing from it was not found in the
sources currently checked. This does not mean all brokers have been
identified, that the user is unaffected, or that the broker is compliant.
Opaque or unlisted brokers warrant additional scrutiny, but absence from a
public listing alone is not evidence of misconduct or proof that such brokers
are statistically more likely to break the law.

### Public broker web search

The initial live-search adapter uses Tavily's documented Search API. It supports
the keyless, rate-limited access mode; setting `TAVILY_API_KEY` in the process
environment enables authenticated access instead. Each approved search is
limited to one of four fixed, generic broker topics and at most five results.
The exact query is shown before sending. The query contains no user-supplied
text; Tavily still receives the query and ordinary network metadata such as the
device's IP address. Individual footprint searches remain disabled. Tavily's
technical documentation was checked for the API and keyless mode; its legal
terms, retention practices, and production-use rights have not been verified
for this project, so review those before production deployment. Returned
sources are untrusted leads, not verified broker records. Results currently
appear in the chat only and are not automatically incorporated into the local
directory or candidate inventory.

### GUI discovery design and future refresh workflow

Keep the local desktop application as the primary user interface. Add a
user-triggered **Search and update broker list** action; do not make a browser
the primary interface or run an always-on general-purpose crawler. The action
should use a user-managed source list that users can inspect, add to, edit, and
remove in the GUI; do not require developers to hardcode every source. The
Coverage and sources tab now supports managing this list locally, including
source format, coverage, limitations, and confirmation that the user reviewed
the source terms. Saving a source does not fetch it. Automated bounded refresh,
comparison, and directory updates remain future work. Explain what each
source covers and what the app will retrieve, so users can understand the
service they are choosing. Keep the interaction concierge-like: the user
starts a search, the app handles routine bounded fetching and comparison, and
the user receives a concise, understandable summary and review of proposed
directory changes rather than a series of unnecessary technical prompts. Make
material choices and the final user-authorized directory update clear; do not
hide external requests or silently change trusted records.

Only add a record to the actionable directory when source evidence supports
both that the organization operates as a data broker and that it has a current
official opt-out process. Store source URLs and last-checked dates with each
record, deduplicate safely, and report skipped or ambiguous candidates instead
of silently promoting them. Search results and registry listings alone are
leads, not proof that an organization sells personal data or has an actionable
opt-out process. Fetch only user-selected public sources in ways permitted by
applicable law and source terms; use bounded requests and never search for the
user's personal footprint as part of broker discovery.

Keep searches generic, non-identifying, and approval-gated as described above.
Prefer small, sequential searches over bulk crawling, and use public sources
only in ways permitted by applicable law and source/provider terms. A browser
can use additional RAM and CPU, and may contend with Ollama for GPU resources
when both use the same device; the degree of impact depends on the machine,
model, and pages loaded. Keep browser sessions closed when not needed, avoid
browser-heavy work concurrent with model generation on resource-constrained
machines, and consider an optional user-controlled pause/unload-Ollama setting
if testing shows it is useful. Do not promise that a browser will or will not
slow inference without measuring on the user's hardware.

The target concierge experience is that the user states an outcome, such as
opting out, and the agent explains its approach, researches through approved
public sources, coordinates the relevant module tools, performs supported
steps, and reports what was and was not confirmed. Ask only for missing details,
unusually sensitive or disproportionate disclosures, and required user
verification. Track submission, acknowledgment, response, and outcome as
separate facts; never bypass CAPTCHA or other access/identity controls. The
current chat is a limited local concierge—not full multi-module delegation or
unrestricted web research. Supported broker actions are also available from
chat when the user explicitly requests them and through the dedicated tab.

Run the focused tests from the project folder:

```powershell
python -m unittest discover -s tests
```

The maintained public broker data is in
`ollama_databroker_compliance_agent/broker_directory.json`. The source
inventory is in
[`broker_discovery_sources.json`](./ollama_databroker_compliance_agent/broker_discovery_sources.json).
Before promoting a registry candidate into the actionable directory, verify
the broker's identity, official opt-out page, current steps, and any proposed
automation independently. Update `verified_at` and preserve source limitations.
The application does not automatically re-verify sources or declare records
current based on their age.

Choose **Check an official broker page for changes** in the CLI to inspect a
listed source or opt-out page. The app shows the URL and asks you to type
`FETCH` before making that request. The site may receive your network address.
Page text and comparison history are kept unencrypted under the user's local
application-data directory. A changed page is only a lead for review—not proof
that the broker changed its procedure. You may manually stage replacement
instructions, method, or opt-out URL. Review the source and proposal, then
explicitly type `APPLY` before it updates the trusted directory; no agent can
apply changes. Approved record changes are saved in an application-data
override file, leaving the shipped seed directory unchanged. Redirects are
not followed; a redirected page must be reviewed and added to the directory
before it can be checked. Fetch size and time are bounded.

For setup and module scope, see the
[broker-compliance TODO](./ollama_databroker_compliance_agent/todo) and its
[agent configuration](./ollama_databroker_compliance_agent/agent.py).

## Independent agent framework

Each feature module has its own ReAct agent configuration and tool set. The
shared [react_framework](./react_framework) package provides the local Ollama
conversation and tool-call loop; it does not define module policy or connect
modules together.

Available tool schemas are registered in
[react_framework/tool_catalog.py](./react_framework/tool_catalog.py). Feature
modules bind only the tools they need. Only explicitly selected tools are sent
to Ollama for that agent, so unrelated schemas do not consume prompt tokens.

- `ollama_databroker_compliance_agent/agent.py` configures the initial
  read-only desktop concierge and the separate broker-directory and page-monitor
  agents.
- `agent_ollama_data_mishandling_damages_expert/agent.py` provides the local
  privacy impact analysis specialist. It presents a direct bottom line with
  evidence, confidence, and material limits; after separate approval, it can
  inspect supported text evidence for one selected case.
- `repeated_broker_conduct_tracker/agent.py` provides an independent
  repeated-conduct agent configuration.

### Local case files

[react_framework/workspace.py](./react_framework/workspace.py) provides
app-managed local case folders with separate `originals/` and `derived/`
directories. A user explicitly imports a source file as a copy into
`originals/`; the source remains untouched. Agent tools can read and search
originals, but cannot alter, rename, or delete them. Copies and generated text
are create-new files in `derived/`; existing files are never overwritten.

The tools include file review, filename lookup, copying an original to derived,
creating a derived file, and `grep_search`. Search returns exact matching
quotes with a case-relative file path, line number, and SHA-256 identifier. It
also reports files it skipped. Currently supported for text review/search are
UTF-8 `.csv`, `.json`, `.log`, `.md`, `.py`, `.rst`, `.text`, and `.txt` files.
PDF text extraction and scanned-image OCR are not configured.

Create a case in Python, import selected originals, then give the workspace to
the relevant module's agent:

```python
from pathlib import Path

from react_framework import CaseWorkspace
from agent_ollama_data_mishandling_damages_expert.agent import create_agent

workspace = CaseWorkspace.create("case-001")
workspace.import_original(Path(r"C:\path\to\selected-evidence.txt"))
agent = create_agent(workspace)
response = agent.run("Find and cite the opt-out confirmation in my evidence.")
print(response.content)
```

Case folders default to the user's local application-data directory. The
workspace also appends content-free agent/tool activity metadata to
`activity.jsonl` and shows actions live in the console. Prompts and document
contents are not copied into that log.

### Local specialist agents and research

The framework can invoke separate local Ollama research-planning, architecture,
and preliminary legal-issue-spotting specialists. These are local model roles,
not external delegated services. The evidence and repeated-conduct agents
select only the local specialists relevant to their work.

The desktop configures the provider-neutral interface in
[react_framework/research.py](./react_framework/research.py) with the Tavily
Search API. The concierge can search only fixed, generic broker topics after
the user approves the exact query; no identifying details or case files are
sent. Tavily receives the query and ordinary network metadata. Its technical
API documentation was checked, but its legal terms, retention practices, and
production-use rights have not been verified for this project. The local legal
specialist can review case context but has no verified legal source library;
its output is preliminary and should be checked by professional counsel.

Future broker research is about the broker and its public record: its
locations and jurisdictions, publicly documented practices or incidents,
affected populations described by credible sources, and possible opt-out,
regulatory, or attorney-review steps. It is not a search for a victim's
personal data or a list of identified victims. If provider options are added,
users may choose only among providers whose applicable terms permit the
intended search method. Show the exact query and selected provider before
sending; never include victim PII, case-file contents, or identifying details.
Provider terms and interfaces must be rechecked over time. Local Ollama does
not prevent an external search provider from receiving or retaining an
approved query.

The concierge has one limited handoff to the privacy impact analysis specialist.
The specialist owns its domain policy and conclusions; the concierge passes
only the current user request. Access to a selected case's evidence requires
separate approval. Broader cross-module orchestration remains future work and
requires explicit handoff and approval design.

## Scope boundary

The scope is commercial data brokerage across sectors, including services
involving identity, advertising, financial, health-related, business, and
other personal data. An organization is not a data broker merely because it
holds personal information; its activities must be assessed against the
relevant source and jurisdiction. The app does not audit institutions as a
whole.

The intended initial audience is an ordinary citizen. The intended legal
context is global, but research and legal coverage are not yet global. If a
broker's location can be established, later research may consider the laws
that apply in that broker's jurisdiction. The app must distinguish confirmed
facts, user reports, source material, and agent analysis. Agent analysis is
preliminary material for the user and a professional attorney to review; it
must not be portrayed as proven facts or as a guaranteed legal outcome.

Research is limited to publicly accessible information and queries that do not
contain personal identifiers. The app must not break laws or submit private
personal information to public search or research services. Local Ollama is
the intended model runtime. During development, case material is intended to
be kept locally rather than in a browser or cloud service; production
encryption requirements remain future work.

## Planning status

No feature roadmap item below should be treated as implemented merely because
it is documented. Develop the modules separately and preserve their ownership
of policy, tools, and domain conclusions. Any additional case-data sharing,
combined workflows, or agent orchestration requires explicit handoff and
approval design before implementation.

