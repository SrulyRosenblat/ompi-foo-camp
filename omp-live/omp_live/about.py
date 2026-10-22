"""What OMP and OMPI are, for agents: served by the MCP `about_omp` tool and
summarized in the demo agent's system prompt.

Sources: the Open Memory Protocol repository README, this checkout's PITCH.md
and PROTOTYPE-PLAN.md, and the code in omp_live/. Keep it to what those say;
the spec is an editors' draft, not an adopted standard.
"""
from __future__ import annotations

REPO = "https://github.com/The-AI-Disclosures-Project/Open-Memory-Protocol"
SITE = "https://ai-disclosures.org/ompi"
SPEC_PR = REPO + "/pull/13"

SUMMARY = (
    "The Open Memory Protocol (OMP) is an open, royalty-free format for portable, interoperable memory across "
    "AI agents and services: what an agent remembers, who said it, and what was forgotten can move between tools "
    "such as Claude Code, Codex, goose and Letta Code. The Open Memory Protocol Initiative (OMPI) is the "
    "multi-stakeholder, vendor-neutral open-source ecosystem that develops OMP, hosted at the AI Disclosures "
    "Project and co-hosted with Mozilla and IBM. OMP is pre-1.0: the current working specification is the v0.2 "
    f"editors' draft (PR #13), open for review and not an adopted standard. Repository: {REPO} · Site: {SITE}"
)

TOPICS: dict[str, str] = {
    "overview": SUMMARY,

    "ompi": (
        "OMPI, the Open Memory Protocol Initiative, develops, maintains and grows OMP. It is hosted at the AI "
        "Disclosures Project (a project of Code for Science & Society), with Mozilla and IBM as co-hosts and "
        "in-kind partners; Letta is a technology author and reference implementer, and Block/goose a first-vertical "
        "implementer. Governance is member- and consensus-driven, modeled on W3C, IETF, FDX and DTI: a Technical "
        "Steering Group, DCO-based contributions, CC BY 4.0 for documents and Apache 2.0 for code. Discussion happens "
        f"in the repository and on Discord (membership by application). Repository: {REPO} · Site: {SITE}"
    ),

    "why": (
        "Every coding-agent harness keeps memory differently (AGENTS.md, MEMORY.md, USER.md, HUMAN.md, memory "
        "blocks, vector stores), so switching tools loses what an agent learned, who told it, and what was deleted. "
        "Developers write bespoke adapters, provenance is lost on copy, and permissions may not survive export. "
        "OMP aims to be the smallest shared layer: each tool implements one import and one export instead of a "
        "converter for every pair, and keeps its own storage. It is a transfer format, not a storage format. "
        "The first vertical is coding agents."
    ),

    "record": (
        "A memory object (record) in the v0.2 draft has required fields identifier, media_type, body and "
        "attributes. body is a string (I-17); attributes is an object for additional metadata. Common optional "
        "fields: title, tags, path (a mutable location, e.g. a wiki folder), links (typed edges: target, rel), "
        "provenance (a list of contributors), version, updated_at, valid_until, evidence, scope. A checksum over "
        "the canonical record detects change. Unknown fields are preserved, so a system keeps what it does not "
        "understand. In this demo, search also stores an embedding vector in attributes.embedding."
    ),

    "export": (
        "An OMP export is a plain folder: manifest.json (protocol_version, profiles, origin, exported_at, "
        "selection, intent, media_types), memories/ with one JSON record per memory, tombstones/ for forgotten "
        "identifiers, and receipts/ recording what happened on import. Global identity is the manifest origin plus "
        "the record identifier, so identity survives renames and round trips. Profiles run from 'a folder of "
        "markdown' (minimal) up to 'audit'."
    ),

    "provenance": (
        "provenance is a list of contributors, each with an id, a kind (human, agent, system) and a contribution "
        "(authored, instructed, imported, edited). It is append-only: a system that imports or edits a memory adds "
        "itself and keeps contributors it never saw. A memory with no provenance stays without one; tools show "
        "'author unknown' rather than inventing an author."
    ),

    "lifecycle": (
        "Lifecycle operations: remember (create), recall (read), revise (update), forget (delete). Forgetting writes a "
        "tombstone that keeps when, who and why but never the content, and a tombstoned identifier never comes back: "
        "a system re-presenting a pre-forget copy is rejected with a receipt (anti-resurrection). valid_until expires "
        "a memory without deleting it. A supersedes link marks an explicit replacement of an earlier description, "
        "with a reason and the contributor; ordinary edits are just new versions."
    ),

    "conflicts": (
        "If two systems edit the same version, OMP does not pick a winner: both revisions are kept, marked "
        "incomparable, and a person resolves it. Receipts record each outcome: accepted, transformed (the system "
        "holds a projection and dropped or reshaped fields), omitted, conflict, rejected, forgotten."
    ),

    "open-issues": (
        "Open questions the v0.2 draft leaves for the working group include: I-5 links (inline Markdown links vs "
        "typed edges), I-7 whether forgetting is core, I-8 identity on import, I-11 change notification, I-19 path "
        "(graphs have nowhere to put it), I-20 whether accuracy should travel as a number, I-21 a thin core with "
        "semantic conventions, I-22 trust on import and the prompt-injection surface. Outcomes are discussed in the "
        f"repository: {REPO}"
    ),

    "drafts": (
        "The v0.2 working spec (PR #13) combines seven sources: Letta's draft (Charles Packer), IBM's draft, the AI "
        "Disclosures Project's Federated Memory Protocol (AIDP/FMP), Cognee's proposal (PR #16, identity, evidence, "
        "validity, accuracy), Context Nest's governed Markdown profile, the Mila + Mozilla Agent Memory System Card, "
        "and the ecosystem scoping note. PR #17 covers the memory security and threat model. "
        f"Spec PR: {SPEC_PR}"
    ),

    "this-demo": (
        "omp-live shows OMP as the only thing moving between three unrelated systems and an agent: a Markdown wiki, "
        "a graph store and a full-text/embedding search index. The OMP export folder is the bus; there is no hub. Each "
        "system implements one import and one export, and the sync turns a change in any system into a new revision "
        "that every other system imports, with provenance, receipts, tombstones and conflicts as above. The memories "
        "are fictional (the Cloudberry Observatory and its night observer, Juniper Hale). This MCP server writes "
        "through the search index; changes reach the wiki and graph through the same OMP export."
    ),
}


def about(topic: str | None = None) -> dict:
    """One topic, or the summary and the list of topics."""
    key = (topic or "").strip().lower().replace(" ", "-").replace("_", "-")
    if key in TOPICS:
        return {"topic": key, "text": TOPICS[key], "repository": REPO, "site": SITE}
    result = {"summary": SUMMARY, "topics": list(TOPICS), "repository": REPO, "site": SITE, "spec": SPEC_PR}
    if key:
        result["note"] = f"No topic {topic!r}; choose one of the topics listed."
    return result
