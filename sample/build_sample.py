"""Write the sample OMP export used by the Foo Camp deck.

Checksums use this demo's canonicalization: SHA-256 over the record without
`checksum`, serialized as JSON with sorted keys and no whitespace. The deck
computes the same value in the browser. v0.2 does not fix a canonicalization.
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent
ORIGIN = "store:6f1c2a9e-4b7d-4e2a-9c1f-3d8e5a7b0c42"

manifest = {
    "protocol_version": "0.2",
    "profiles": ["minimal"],
    "origin": ORIGIN,
    "exported_at": "2026-10-20T09:00:00Z",
    "selection": "snapshot",
    "intent": "copy",
    "media_types": ["text/markdown", "application/json", "text/plain"],
}

JORDAN = {"id": "user:jordan", "kind": "human"}
ASSISTANT = {"id": "agent:coding-assistant", "kind": "agent", "name": "example-model-1"}

memories = [
    {
        "identifier": "9b2e7c14-3f6a-4d1e-8a5b-2c7f9e0d4b31",
        "path": "team/preferences/status-update-day.md",
        "title": "Status updates move to Friday",
        "media_type": "text/markdown",
        "tags": ["preference", "team-process"],
        "scope": ["team:platform"],
        "created_at": "2026-09-15T09:30:00Z",
        "valid_from": "2026-09-15T00:00:00Z",
        "version": {"value": 2, "comparator": "integer"},
        "provenance": [
            {**JORDAN, "contribution": "instructed", "at": "2026-09-15T09:28:00Z"},
            {**ASSISTANT, "contribution": "authored"},
            {"id": "user:sam", "kind": "human", "contribution": "approved", "at": "2026-09-15T09:30:00Z"},
            {"id": "agent:review-judge", "kind": "agent", "contribution": "verified",
             "name": "example-judge-1", "at": "2026-10-01T12:00:00Z"},
        ],
        "evidence": [
            {"ref": "transcripts/2026-09-15-standup#turn-14", "relation": "stated", "dangling": True},
        ],
        "links": [{"target": "9b2e7c14-3f6a-4d1e-8a5b-2c7f9e0d4b31", "version": 1, "rel": "supersedes"}],
        "body": "Status updates are due **Fridays** from Sep 15. They were due Tuesdays before that.",
    },
    {
        "identifier": "2f8a1c3e-pnpm",
        "path": "projects/web/tooling.md",
        "title": "Use pnpm in the web repo",
        "media_type": "text/markdown",
        "tags": ["preference", "tooling"],
        "scope": ["repo:web"],
        "created_at": "2026-08-02T14:11:00Z",
        "version": {"value": 1, "comparator": "integer"},
        "provenance": [
            {**JORDAN, "contribution": "instructed", "at": "2026-08-02T14:10:00Z"},
            {**ASSISTANT, "contribution": "authored"},
        ],
        "evidence": [{"ref": "transcripts/2026-08-02-setup#turn-3", "relation": "stated", "dangling": True}],
        "x_editor_rule_glob": "apps/web/**",
        "body": "Use `pnpm`, never `npm` or `yarn`, in `apps/web`. The lockfile is `pnpm-lock.yaml`.",
    },
    {
        "identifier": "c41d7e02-flaky",
        "path": "projects/web/known-issues.md",
        "title": "Checkout e2e test is flaky until the fix lands",
        "media_type": "text/markdown",
        "tags": ["workaround", "testing"],
        "scope": ["repo:web"],
        "created_at": "2026-10-06T16:45:00Z",
        "valid_until": "2026-11-01T00:00:00Z",
        "provenance": [{**ASSISTANT, "contribution": "authored"}],
        "evidence": [{"ref": "https://ci.example.com/runs/88213", "relation": "observed", "dangling": True}],
        "links": [{"target": "e7b9a210-billing-owner", "rel": "relates_to"}],
        "body": "`checkout.spec.ts` fails about 1 run in 6 on the card-decline path. Retry once, then flag Maya. Remove this workaround after Nov 1.",
    },
    {
        "identifier": "5a0f93bd-rate-limit",
        "path": "projects/payments/limits.md",
        "title": "Payments API rate limit",
        "media_type": "text/markdown",
        "tags": ["fact", "system-of-record"],
        "scope": ["team:platform"],
        "created_at": "2026-07-21T10:02:00Z",
        "stub": True,
        "provenance": [{**ASSISTANT, "contribution": "imported"}],
        "evidence": [{"ref": "https://payments.example.com/docs/limits", "relation": "observed", "dangling": True}],
        "body": "The payments API is rate-limited per merchant. Read the current limit from the provider docs before load testing; do not copy the number here.",
    },
    {
        "identifier": "e7b9a210-billing-owner",
        "path": "team/people/maya.md",
        "title": "Maya owns billing",
        "media_type": "text/markdown",
        "tags": ["person", "ownership"],
        "scope": ["team:platform"],
        "created_at": "2026-06-30T11:00:00Z",
        "valid_from": "2026-06-01T00:00:00Z",
        "provenance": [
            {**JORDAN, "contribution": "authored", "at": "2026-06-30T11:00:00Z"},
        ],
        "body": "Maya Chen owns the billing service and reviews every change to the ledger schema.",
    },
    {
        "identifier": "0d6e4f88-ledger-decision",
        "path": "projects/payments/decisions/ledger-store.md",
        "title": "Decision: Postgres for the ledger",
        "media_type": "text/markdown",
        "tags": ["decision", "architecture"],
        "scope": ["team:platform"],
        "created_at": "2026-09-03T15:20:00Z",
        "version": {"value": 1, "comparator": "integer"},
        "provenance": [
            {**ASSISTANT, "contribution": "authored", "at": "2026-09-03T15:20:00Z"},
            {"id": "user:maya", "kind": "human", "contribution": "approved", "at": "2026-09-03T16:02:00Z"},
        ],
        "evidence": [{"ref": "transcripts/2026-09-03-design-review#turn-41", "relation": "stated", "dangling": True}],
        "links": [{"target": "e7b9a210-billing-owner", "rel": "relates_to"}],
        "body": "We keep the ledger in **Postgres**, not DynamoDB: we need multi-row transactions for refunds. Revisit if write volume passes 5k/s.",
    },
    {
        "identifier": "b3c2e9f1-ci-matrix",
        "path": "projects/web/ci-matrix.json",
        "title": "CI matrix the team agreed on",
        "media_type": "application/json",
        "tags": ["config", "testing"],
        "scope": ["repo:web"],
        "created_at": "2026-09-22T09:00:00Z",
        "provenance": [{**JORDAN, "contribution": "authored"}],
        "body": json.dumps({"node": ["20", "22"], "os": ["ubuntu-latest"], "browsers": ["chromium", "webkit"]}),
    },
    {
        "identifier": "f19a0c77-ships-fridays",
        "path": "team/patterns/release-rhythm.md",
        "title": "The team batches releases at the end of the week",
        "media_type": "text/markdown",
        "tags": ["observation", "consolidated"],
        "scope": ["team:platform"],
        "created_at": "2026-10-12T03:00:00Z",
        "provenance": [
            {"id": "agent:nightly-consolidator", "kind": "agent", "contribution": "authored", "name": "example-model-2"},
            {"id": "user:sam", "kind": "human", "contribution": "operates", "at": "2026-10-01T00:00:00Z"},
        ],
        "evidence": [
            {"ref": "9b2e7c14-3f6a-4d1e-8a5b-2c7f9e0d4b31", "relation": "derived"},
            {"ref": "c41d7e02-flaky", "relation": "derived"},
        ],
        "links": [
            {"target": "9b2e7c14-3f6a-4d1e-8a5b-2c7f9e0d4b31", "rel": "derived_from"},
            {"target": "c41d7e02-flaky", "rel": "derived_from"},
        ],
        "body": "Releases cluster on Thursdays and Fridays, after status updates. Expect review load to peak then.",
    },
    {
        "identifier": "MEMORY.md",
        "media_type": "text/markdown",
        "created_at": "2026-10-14T00:00:00Z",
        "body": "The user prefers concise answers.",
    },
]


def checksum(record: dict) -> str:
    covered = {k: v for k, v in record.items() if k != "checksum"}
    text = json.dumps(covered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


# Records with a version also get a checksum, so three of nine can pass the audit checks.
for record in memories:
    if "version" in record:
        record["checksum"] = checksum(record)

(HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
(HERE / "memories.json").write_text(json.dumps(memories, indent=2, ensure_ascii=False) + "\n")
print(f"wrote {len(memories)} memories")
