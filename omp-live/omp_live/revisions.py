"""SQLite revision snapshots used by the non-Markdown adapters."""
import json

from .model import checksum, title_of, version_value

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_revisions (
 key TEXT PRIMARY KEY, identifier TEXT NOT NULL, version INTEGER NOT NULL, record TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS revision_identity ON memory_revisions(identifier, version);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_revision_fts USING fts5(
 key UNINDEXED, identifier UNINDEXED, title, body, tags, tokenize='porter unicode61'
);
"""


def remember(db, records):
    for record in records:
        key = checksum(record)
        result = db.execute('INSERT OR IGNORE INTO memory_revisions VALUES(?,?,?,?)',
                            (key, record['identifier'], version_value(record), json.dumps(record, ensure_ascii=False)))
        if result.rowcount:
            db.execute('INSERT INTO memory_revision_fts VALUES(?,?,?,?,?)',
                       (key, record['identifier'], title_of(record), record['body'], ' '.join(record.get('tags') or [])))


def history(db, identifier=None):
    where, args = (' WHERE identifier=?', (identifier,)) if identifier is not None else ('', ())
    rows = db.execute('SELECT record FROM memory_revisions' + where + ' ORDER BY rowid', args)
    # Metadata-only variants at one revision are represented by the most recently imported snapshot.
    unique = {}
    for row in rows:
        record = json.loads(row['record'])
        unique[(record['identifier'], version_value(record))] = record
    return list(unique.values())


def forget(db, identifier):
    db.execute('DELETE FROM memory_revisions WHERE identifier=?', (identifier,))
    db.execute('DELETE FROM memory_revision_fts WHERE identifier=?', (identifier,))


def reset(db):
    db.execute('DELETE FROM memory_revisions')
    db.execute('DELETE FROM memory_revision_fts')
