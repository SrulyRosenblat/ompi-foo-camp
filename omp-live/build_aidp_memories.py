"""Build aidp-memories.json: the demo's seed memories about the AI Disclosures Project.

Every note restates public material: the project's site, its GitHub organization and
the Open Memory Protocol repository, as read on 2026-10-22. Each record carries its
source URL in `attributes.source`. Edit the notes here, then run

    python3 build_aidp_memories.py            # embeds through OpenRouter (OPENROUTER_API_KEY)
    python3 build_aidp_memories.py --no-embed # records without vectors; search embeds at boot
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SITE = "https://ai-disclosures.org"
PEOPLE = SITE + "/people.html"
RESEARCH = SITE + "/research.html"
OMPI = SITE + "/ompi"
REPO = "https://github.com/The-AI-Disclosures-Project/Open-Memory-Protocol"
GOV = REPO + "/blob/main/GOVERNANCE.md"
CONTRIB = REPO + "/blob/main/docs/contributing.md"
PR13 = REPO + "/pull/13"
PULLS = REPO + "/pulls"
WALLED = "https://asimovaddendum.substack.com/p/the-memory-walled-garden"
BLOG = "https://asimovaddendum.substack.com"
RETRIEVED = "2026-10-22"

SEED = {"id": "seed:aidp-public-sources", "kind": "system", "contribution": "imported",
        "name": "the omp-live seed (public sources)"}

# (path, title, tags, source, body). Links are relative Markdown links between notes.
NOTES = [
    ("MEMORY.md", "AI Disclosures Project", ["index"], SITE,
     "These notes restate public material from the AI Disclosures Project: its website, its "
     "GitHub organization and the Open Memory Protocol repository, read on 2026-10-22. Each note "
     "keeps its source URL.\n\n"
     "Start with [the project](project/ai-disclosures-project.md), "
     "[the Open Memory Protocol](omp/what-is-omp.md), [the memory record](spec/memory-object.md), "
     "[the open issues](spec/open-issues.md) and [the Asimov’s Addendum blog](blog/asimovs-addendum.md). "
     "Notes about Ilan himself are under [personal](personal/ilan.md)."),

    ("project/ai-disclosures-project.md", "The AI Disclosures Project", ["project"], SITE,
     "The AI Disclosures Project works on market-shaping protocols, technical standards and economic "
     "mechanisms so that value circulates broadly rather than being trapped inside a handful of "
     "gatekeepers. It works through research, prototypes and convenings. It is hosted at "
     "[Code for Science & Society](fiscal-home.md), and its site names Omidyar Network as a funder. "
     "It is led by [Tim O’Reilly and Ilan Strauss](../people/directors.md), who also write "
     "[Asimov’s Addendum](../blog/asimovs-addendum.md)."),

    ("project/fiscal-home.md", "Hosted at Code for Science & Society", ["project", "governance"], GOV,
     "The AI Disclosures Project is a project of Code for Science & Society (CS&S), a registered "
     "501(c)(3) public charity. [OMPI](../ompi/initiative.md) is a named initiative housed there; no "
     "new legal entity is created during the grant period. CS&S and the project keep the fiduciary, "
     "employment, contracting and grant-accountability duties."),

    ("project/github.md", "The project on GitHub", ["project"], "https://github.com/The-AI-Disclosures-Project",
     "The GitHub organization The-AI-Disclosures-Project hosts the Open-Memory-Protocol repository "
     "(created 2026-08-26), follow_up_research, and code for three papers: detecting access violations "
     "in LLM pre-training data, ecosystem exploitation in search results, and real-world gaps in AI "
     "governance research. See [research](../research/attribution-and-access.md)."),

    ("people/directors.md", "Tim O’Reilly and Ilan Strauss direct the project", ["people"], PEOPLE,
     "Tim O’Reilly is founder and co-director (and founder and CEO of O’Reilly Media). Ilan Strauss is "
     "co-director. Strauss also lists roles as an honorary senior fellow at UCL IIPP, a senior fellow "
     "at the Microsoft AI Economy Institute, a visiting associate professor at the University of "
     "Johannesburg, and a member of the Data & Policy editorial board. See also "
     "[the team](team.md) and [Ilan’s profile](../personal/ilan.md)."),

    ("people/team.md", "Researchers, scholars and advisors", ["people"], PEOPLE,
     "Sruly Rosenblat is the project’s technical researcher. Affiliated scholars are Rufus Rock "
     "(CMU) and Jangho Yang (University of Waterloo). The advisory committee is Anna Tumadóttir "
     "(Creative Commons), Erika Augustine (The David Prize), Daniel Goroff (ex officio, Sloan "
     "Foundation), Tim O’Reilly and Ilan Strauss. Leadership: [directors](directors.md)."),

    ("research/protocols-and-power.md", "Protocols and Power (August 2025)", ["research"], RESEARCH,
     "“Protocols and Power”, also published as “Open Protocols Can Prevent AI Monopolies”, is by "
     "M. Moure, T. O’Reilly and I. Strauss (August 2025). It argues that open protocols such as MCP "
     "keep AI context fluid and limit platform lock-in, and recommends authorized access to "
     "user-owned data and portable agent memory. The OMP README cites it as the case that started "
     "[the memory work](../omp/what-is-omp.md)."),

    ("research/mcp-in-practice.md", "MCP in practice (August 2025)", ["research"], RESEARCH,
     "“MCP In Practice” (S. Rosenblat, I. Strauss, T. O’Reilly and I. Moore, August 2025) analyzes "
     "2,874 MCP servers and finds activity concentrated in a few high-use servers. It argues for "
     "open APIs, portable memory and transparent dependencies. Related: "
     "[Protocols and Power](protocols-and-power.md)."),

    ("research/memory-walled-garden.md", "The Memory Walled Garden (October 2025)", ["research", "memory"], WALLED,
     "Published on 2025-10-03 in [Asimov’s Addendum](../blog/asimovs-addendum.md). Chat history is locked inside first-party apps: "
     "none of the five MCP memory servers surveyed could read ChatGPT or Claude history. It "
     "recommends that OpenAI and Anthropic expose memory through MCP or an API with OAuth. The OMP "
     "README calls it the ecosystem’s first public position on [portable agent memory](../omp/why-omp.md)."),

    ("research/attribution-and-access.md", "Attribution and access research", ["research"], RESEARCH,
     "“Beyond Public Access in LLM Pre-Training Data” (Rosenblat, O’Reilly, Strauss; April 2025) "
     "reports that GPT-4o shows signs of prior exposure to paywalled O’Reilly books. “The "
     "Attribution Crisis in LLM Search Results” (Strauss, Yang, O’Reilly, Rosenblat, Moure; Data & "
     "Policy) estimates ecosystem exploitation from about 14,000 LMArena logs. “Governing AI Through "
     "SEC Disclosure” is an SSRC policy report from October 2025."),

    ("blog/asimovs-addendum.md", "Asimov’s Addendum, the blog", ["blog"], BLOG + "/about",
     "Asimov’s Addendum is a newsletter on Substack by Tim O’Reilly and Ilan Strauss. It considers what "
     "additional “laws” might be needed for AI, with a focus on disclosures as protocols and built-in "
     "software standards. Its tagline: “Participatory, decentralized AI markets built for human "
     "participation, reward, and oversight.” It runs parallel to research housed at the Social Science "
     "Research Council but is not affiliated with it. Posts: [summer 2026](summer-2026-posts.md), "
     "[August 2026](august-2026-posts.md), and [The Memory Walled Garden](../research/memory-walled-garden.md)."),

    ("blog/summer-2026-posts.md", "Asimov’s Addendum, May to July 2026", ["blog"], BLOG + "/archive",
     "May 13: “The Salesforce of agents won’t be Salesforce, The Google of agents won’t be Google” "
     "(Jesus Rodriguez, Ilan Strauss, Tim O’Reilly). May 26: “Open Source Ecosystems” (Strauss). "
     "June 5: “Agents Need a Public Square”, on agent discovery and broadcasting (Sruly Rosenblat, "
     "Strauss, O’Reilly). June 17: “The Architecture of Participation”, on the Rockefeller-sponsored "
     "Bellagio convening (O’Reilly, Strauss). July 10: “Where Does Intelligence Reside?” (Strauss). "
     "July 21: “Open Protocols are Shaping AI Markets: The case of MCP” (Tadas Antanavicius, Adam Jones)."),

    ("blog/august-2026-posts.md", "Asimov’s Addendum, August 2026", ["blog"], BLOG + "/archive",
     "August 8: “Google’s Westinghouse Bet” (Tim O’Reilly). August 15: “The Apache Lesson for AI”, "
     "arguing that composability, not just open weights, will determine who controls the AI stack "
     "(O’Reilly). August 21: “When Smaller Models Win: Chess, LoRA, and the case for specialized AI” "
     "(Sruly Rosenblat). Earlier: [May to July](summer-2026-posts.md)."),

    ("omp/what-is-omp.md", "The Open Memory Protocol", ["omp"], REPO,
     "The Open Memory Protocol (OMP) is an open, royalty-free technology for portable, interoperable "
     "memory across AI agents and services. It is a transfer format, not a storage format: each tool "
     "keeps its own storage and implements one import and one export. Why it exists: "
     "[the problem](why-omp.md). Who develops it: [OMPI](../ompi/initiative.md)."),

    ("omp/why-omp.md", "Why agent memory needs a shared format", ["omp"], REPO,
     "Each coding harness (Claude Code, Codex, goose, OpenClaw, Letta Code) keeps memory in its own "
     "conventions: AGENTS.md, MEMORY.md, USER.md, HUMAN.md. Agents can’t move between harnesses, and "
     "provenance and permissions are lost on export. The first vertical is coding agents; see the "
     "[roadmap](roadmap.md)."),

    ("omp/roadmap.md", "OMP roadmap", ["omp", "plan"], OMPI,
     "Year 1 (2026–27): lock the schema and exchange semantics, and have two harnesses ship "
     "conformant export and import. Year 2 (2027–28): a transport layer and extensions. The scoping "
     "note names five shared practices to standardize: persistence across sessions, scope and "
     "ownership, lifecycle operations, selective retrieval, and controls and policy."),

    ("omp/timeline.md", "How the memory work unfolded", ["omp", "history"], REPO,
     "August 2025: [Protocols and Power](../research/protocols-and-power.md). October 2025: [the "
     "Walled Garden post](../research/memory-walled-garden.md). May 2026: first commits on an ACP "
     "memory-server prototype. June 2026: a FOO Camp session. August 2026: Charles Packer circulates "
     "a draft spec. 2026-09-09: first online convening, co-hosted with Mozilla and IBM. October 2026: "
     "an in-person gathering in Berkeley."),

    ("ompi/initiative.md", "OMPI and its partners", ["ompi", "partners"], OMPI,
     "The Open Memory Protocol Initiative (OMPI) is the multi-stakeholder, vendor-neutral ecosystem "
     "that develops OMP, housed at the AI Disclosures Project. Mozilla and IBM are in-kind partners "
     "and co-hosts. Letta is a spec author and reference implementer; Block’s goose is the "
     "first-vertical implementer. Proposals also came from Cognee, Context Nest and the Mila + "
     "Mozilla AMS Card. Governance: [steering group](governance.md)."),

    ("ompi/governance.md", "OMPI governance", ["ompi", "governance"], GOV,
     "A Technical Steering Group holds in-kind partner seats (Mozilla, IBM), a spec-author seat "
     "(Letta) and rotating working-group seats. Breaking changes need a two-thirds vote and a "
     "migration plan. No funder, sponsor or founding organization gets a technical veto. Specs and "
     "docs are CC BY 4.0, code is Apache 2.0, and contributions use a DCO sign-off. See "
     "[how to join](how-to-join.md)."),

    ("ompi/how-to-join.md", "How to take part in OMPI", ["ompi", "community"], CONTRIB,
     "Open issues and pull requests against the drafts, or run the Python loader and validator "
     "prototype. The Discord is by application, and the address is ompi@aidisclosures.org. The "
     "working group meets monthly, on the second Tuesday at 10:00 ET. Protocol changes need an issue "
     "with at least two weeks of public discussion."),

    ("spec/working-draft.md", "The working spec is the v0.1 draft", ["spec"], OMPI,
     "The OMPI page lists the AI Disclosures Project draft spec v0.1 as the working specification. "
     "It is open for review, not an adopted standard."),

    ("spec/memory-object.md", "The OMP memory object", ["spec", "record"], PR13,
     "A memory is metadata plus a body; Markdown is neither required nor preferred. Records carry an "
     "`identifier` and a `media_type`, with optional `path`, `title`, `tags`, `valid_from`, "
     "`valid_until`, `updated_at`, `provenance`, `evidence` and `links`. The audit profile adds "
     "`version` and `checksum`. Who said it: [provenance](provenance.md). How exports travel: "
     "[manifest](manifest-and-receipts.md)."),

    ("spec/provenance.md", "Provenance: who said it", ["spec", "provenance"], PR13,
     "`provenance` is a list of contributors, each with an `id`, a `kind` (human, agent or system) "
     "and a `contribution`. A missing provenance means author unknown, and must not be read as the "
     "user’s own words. The editors propose no portable accuracy score; confidence travels as "
     "contributions such as verified or contradicted, plus evidence (issue I-20)."),

    ("spec/manifest-and-receipts.md", "Manifest, receipts and import rules", ["spec", "exchange"], PR13,
     "An export’s manifest declares the protocol version, profiles, `origin` (with `identifier`, the "
     "global key), when it was exported and whether it is a snapshot, a selection or full history. "
     "Each export declares an intent: copy, move or federation. Import receipts mark each memory "
     "accepted, transformed, omitted or rejected. Dangling links are kept and marked, and credentials "
     "are never exported. Forgetting: [tombstones](forgetting.md)."),

    ("spec/forgetting.md", "Forgetting and tombstones", ["spec", "lifecycle"], PR13,
     "A forget erases content but leaves a tombstone recording when, who and why, never the content. "
     "Receivers must not restore forgotten content from older archives (anti-resurrection). The "
     "editors propose putting this in the audit profile; that is open issue I-7 in "
     "[the open issues](open-issues.md)."),

    ("spec/open-issues.md", "Open issues in the v0.2 draft", ["spec", "open-issues"], PR13,
     "I-5 links (inline or metadata edges). I-7 tombstones and anti-resurrection: core or audit? I-8 "
     "identity on import. I-19 folders beyond `path`. I-20 accuracy as provenance plus evidence, or a "
     "field. I-21 a thin core with separately versioned semantic conventions, Ilan’s proposal. I-22 "
     "trust and sanitization of imported memories. Related pull requests: [open PRs](open-prs.md)."),

    ("spec/open-prs.md", "Proposals under review", ["spec", "open-issues"], PULLS,
     "PR #16 (Cognee) adds origin, invalidated_by, a body-only content hash, evidence with confidence, "
     "and accuracy. PR #17 is a threat model that separates integrity from trustworthiness and "
     "proposes making anti-resurrection core. PR #19 covers versioning. Issue #22, from Ilan Strauss "
     "on 2026-10-22, proposes an `applies_to` field and an agentic-coding conformance profile."),
]

# Ilan's agent's notes about Ilan, in its own voice. Public facts keep their source URL; the two
# things Sruly told the agent (economist, direct communication) are marked as his instruction.
AGENT = {"id": "agent:ilans-agent", "kind": "agent", "name": "Ilan’s agent", "contribution": "authored"}
SRULY = {"id": "user:sruly-rosenblat", "kind": "human", "name": "Sruly Rosenblat", "contribution": "instructed"}
TOLD = "Told to Ilan’s agent by Sruly Rosenblat"

PERSONAL = [
    ("personal/ilan.md", "Ilan Strauss", ["person"], TOLD, [AGENT, SRULY],
     "Ilan is an economist. He co-directs the [AI Disclosures Project](../project/ai-disclosures-project.md) "
     "with Tim O’Reilly and co-writes [Asimov’s Addendum](../blog/asimovs-addendum.md). Before answering "
     "him, check [how he likes to be addressed](communication.md). His work: [papers](papers.md), "
     "[affiliations](affiliations.md) and [his part in OMP](omp-work.md)."),

    ("personal/communication.md", "Ilan prefers direct communication", ["preference"], TOLD, [AGENT, SRULY],
     "Ilan prefers direct communication. Give him the answer first and say plainly what is known and "
     "what isn’t. Profile: [Ilan Strauss](ilan.md)."),

    ("personal/affiliations.md", "Ilan’s affiliations", ["person"], PEOPLE, [AGENT, SEED],
     "Besides co-directing the project, Ilan is an honorary senior fellow at UCL’s Institute for "
     "Innovation and Public Purpose, a senior fellow at the Microsoft AI Economy Institute, a visiting "
     "associate professor at the University of Johannesburg, and on the editorial board of Data & "
     "Policy. Profile: [Ilan Strauss](ilan.md)."),

    ("personal/papers.md", "Ilan’s papers", ["research"], RESEARCH, [AGENT, SEED],
     "Ilan wrote “‘Rich-get-richer’? Platform Attention and Earnings Inequality” with Jangho Yang and "
     "Mariana Mazzucato (Industrial and Corporate Change, July 2026), and “M&A as Capability Building” "
     "with Jangho Yang (Applied Economics Letters, April 2026). With Tim O’Reilly and M. Moure he wrote "
     "[Protocols and Power](../research/protocols-and-power.md); with Sruly Rosenblat, O’Reilly and others, "
     "[MCP in practice](../research/mcp-in-practice.md) and [the attribution work](../research/attribution-and-access.md)."),

    ("personal/omp-work.md", "Ilan’s part in the Open Memory Protocol", ["omp"], PR13, [AGENT, SEED],
     "Ilan co-wrote the ecosystem scoping note with Sruly Rosenblat, one of the drafts the v0.2 spec "
     "combines. He proposed a thin core with separately versioned semantic conventions (issue I-21 in "
     "[the open issues](../spec/open-issues.md)). On 2026-10-22 he opened issue #22, proposing an "
     "`applies_to` field and an agentic-coding conformance profile ([proposals](../spec/open-prs.md))."),
]

# One retained earlier revision, so History and supersession have something real to show.
SUPERSEDED = {
    "spec/working-draft.md": (
        "The working spec is the v0.2 editors’ draft",
        "The working specification is the v0.2 editors’ draft of 2026-10-14 (PR #13), renamed "
        "from v0.1. It defines [the memory object](memory-object.md). It folds in reviews from IBM, the AI Disclosures Project and a technical "
        "working meeting. It is an editors’ draft, not an adopted standard; the OMPI page still lists v0.1.",
        PR13,
        "PR #13 replaced the v0.1 working draft with the v0.2 editors’ draft on 2026-10-14.",
    ),
}


def inline_links(path, body):
    """Markdown links between notes, resolved from the note's folder, as the wiki would export them."""
    links = []
    for href in re.findall(r"(?<!!)\[[^\]\n]+\]\(([^)\s]+\.md)\)", body):
        target = posixpath.normpath(posixpath.join(posixpath.dirname(path), href))
        if {"target": target, "x_carrier": "inline"} not in links:
            links.append({"target": target, "x_carrier": "inline"})
    return links


def record(path, title, tags, source, body, version=1, provenance=None):
    return {
        "identifier": path,
        "media_type": "text/markdown",
        "body": f"# {title}\n\n{body}",
        "attributes": {"source": source, "retrieved": RETRIEVED},
        "path": path,
        "title": title,
        "tags": ["ai-disclosures", *tags],
        "provenance": provenance or [SEED],
        "version": {"value": version, "comparator": "integer"},
        "links": inline_links(path, body),
    }


def build() -> list[dict]:
    records = []
    for path, title, tags, source, body in NOTES:
        records.append(record(path, title, tags, source, body))
        if path in SUPERSEDED:
            new_title, new_body, new_source, reason = SUPERSEDED[path]
            newer = record(path, new_title, tags, new_source, new_body, version=2)
            newer["links"] += [{"target": path, "version": 1, "rel": "supersedes", "reason": reason,
                               "contributor": {k: v for k, v in SEED.items() if k != "contribution"}}]
            records.append(newer)
    for path, title, tags, source, provenance, body in PERSONAL:
        records.append(record(path, title, tags, source, body, provenance=provenance))
    known = {r["identifier"] for r in records}
    missing = {l["target"] for r in records for l in r["links"] if l.get("x_carrier") == "inline"} - known
    assert not missing, f"links to notes that don't exist: {sorted(missing)}"
    return records


def main() -> None:
    records = build()
    if "--no-embed" not in sys.argv:
        from omp_live.embedding import OpenRouterEmbedder, attach, embed_text
        for env in (HERE / ".env", HERE.parent / ".env"):
            if env.exists() and not os.environ.get("OPENROUTER_API_KEY"):
                for line in env.read_text().splitlines():
                    k, _, v = line.partition("=")
                    if k.strip().upper() == "OPENROUTER_API_KEY":
                        os.environ["OPENROUTER_API_KEY"] = v.strip().strip('"\'')
        embedder = OpenRouterEmbedder()
        vectors = embedder.embed([embed_text(r) for r in records])
        records = [attach(r, embedder.model, v) for r, v in zip(records, vectors)]
    out = HERE / "aidp-memories.json"
    out.write_text(json.dumps(records, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} records to {out.name}")


if __name__ == "__main__":
    main()
