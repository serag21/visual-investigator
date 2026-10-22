"""Minimal opt-in feedback; never accepts photo bytes or full conversations."""
import json
from pathlib import Path
import sqlite3
import time
import uuid
from .storage import Database


class FeedbackStore:
    def __init__(self,path):
        self.db=path if isinstance(path,Database) else Database(path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, owner TEXT, created DOUBLE PRECISION, outcome TEXT, note TEXT, share_reference TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS feedback_detail (id TEXT PRIMARY KEY, detail TEXT NOT NULL)')

    def connect(self):return self.db.connect()

    def add(self,owner,outcome,note,share_reference,detail=None):
        identity=uuid.uuid4().hex
        with self.connect() as db:
            db.execute('DELETE FROM feedback WHERE created < ?', (time.time()-14*86400,))
            db.execute('DELETE FROM feedback_detail WHERE id NOT IN (SELECT id FROM feedback)')
            count=db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0]
            if count>=1000:raise ValueError('Feedback storage is full; export before accepting more.')
            db.execute('INSERT INTO feedback VALUES (?,?,?,?,?,?)',(identity,owner,time.time(),outcome,note,share_reference))
            if detail:db.execute('INSERT INTO feedback_detail VALUES (?,?)',(identity,json.dumps(detail)))
        return identity

    def export(self):
        with self.connect() as db:
            db.execute('DELETE FROM feedback WHERE created < ?', (time.time()-14*86400,))
            db.execute('DELETE FROM feedback_detail WHERE id NOT IN (SELECT id FROM feedback)')
            columns=['id','member','created','outcome','note','case_export_reference']
            details={r[0]:json.loads(r[1]) for r in db.execute('SELECT id,detail FROM feedback_detail')}
            return [dict(zip(columns,row))|{'optional_detail':details.get(row[0])} for row in db.execute('SELECT * FROM feedback ORDER BY created')]

    def summary(self):
        rows=self.export()
        counts={name:sum(r['outcome']==name for r in rows) for name in ('solved','helped_stuck','wrong','not_found')}
        members={r['member'] for r in rows}
        return {'feedback':rows,'reported_outcomes':counts,'responding_members':len(members),
                'members_with_multiple_submissions':sum(sum(r['member']==m for r in rows)>1 for m in members),
                'limitations':['Outcomes are user reports, not independently verified completion.',
                'Multiple submissions do not establish repeat usage or distinct investigations.',
                'Turn/photo counts include restored history. Session time includes idle time and resets on restore; it is not task duration.',
                'Unsupported advice, correctly unresolved cases, source usefulness and outages need voluntary case review.'],
                'retention_days':14,'photos_collected':False}
