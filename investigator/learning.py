"""Bounded private case sharing and aggregate operations; no automatic photo archive."""
import hashlib
import json
import time
import uuid


class LearningStore:
    def __init__(self,db):
        self.db=db
        with db.connect() as q:
            q.execute('CREATE TABLE IF NOT EXISTS shared_cases (id TEXT PRIMARY KEY, owner TEXT NOT NULL, binding TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, expires DOUBLE PRECISION NOT NULL, client_key TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(owner,client_key))')
            q.execute('CREATE TABLE IF NOT EXISTS sharing_lock (id INTEGER PRIMARY KEY)')
            q.execute('INSERT INTO sharing_lock VALUES (1) ON CONFLICT(id) DO NOTHING')
            q.execute('CREATE TABLE IF NOT EXISTS operation_counts (day BIGINT NOT NULL, kind TEXT NOT NULL, count INTEGER NOT NULL, total_ms BIGINT NOT NULL, PRIMARY KEY(day,kind))')

    def prune(self):
        with self.db.connect() as q:
            q.execute('DELETE FROM shared_cases WHERE expires<=?',(time.time(),))
            q.execute('DELETE FROM operation_counts WHERE day<?',(int(time.time()//86400)-14,))

    def event(self,kind,milliseconds=0):
        allowed={'turn_ok','turn_recovery','turn_safety','turn_429','turn_502','turn_503','turn_504','turn_request_error','source_lookup','source_failure','feedback_received'}
        if kind not in allowed:raise ValueError('Unknown operation category')
        with self.db.connect() as q:
            q.execute('INSERT INTO operation_counts VALUES (?,?,1,?) ON CONFLICT(day,kind) DO UPDATE SET count=operation_counts.count+1,total_ms=operation_counts.total_ms+excluded.total_ms',
                      (int(time.time()//86400),kind,max(0,min(int(milliseconds),120000))))

    def operations(self):
        with self.db.connect() as q:
            return [{'utc_day':r[0],'kind':r[1],'requests':r[2],'total_server_ms':r[3]} for r in q.execute('SELECT day,kind,count,total_ms FROM operation_counts WHERE day>=? ORDER BY day,kind',(int(time.time()//86400)-14,))]

    def add(self,owner,binding,key,payload):
        raw=json.dumps(payload,separators=(',',':'),ensure_ascii=True)
        if len(raw.encode())>500000:raise ValueError('This preview is too large; share without photos.')
        digest=hashlib.sha256(raw.encode()).hexdigest();now=time.time()
        with self.db.connect() as q:
            if not q.postgres:q.execute('BEGIN IMMEDIATE')
            q.execute('UPDATE sharing_lock SET id=id WHERE id=1')
            q.execute('DELETE FROM shared_cases WHERE expires<=?',(now,))
            old=q.execute('SELECT id,digest,expires,binding FROM shared_cases WHERE owner=? AND client_key=?',(owner,key)).fetchone()
            if old:
                if old[1]!=digest or old[3]!=binding:raise ValueError('This share receipt belongs to another preview.')
                return {'id':old[0],'expires':old[2],'saved':True}
            total=q.execute('SELECT count(*) FROM shared_cases').fetchone()[0]
            member=q.execute('SELECT count(*) FROM shared_cases WHERE owner=?',(owner,)).fetchone()[0]
            if total>=10 or member>=3:raise ValueError('Private review capacity is full. Keep the evidence on your device; nothing was shared.')
            identity=uuid.uuid4().hex;expires=now+7*86400
            q.execute('INSERT INTO shared_cases VALUES (?,?,?,?,?,?,?,?)',(identity,owner,binding,now,expires,key,digest,raw))
            return {'id':identity,'expires':expires,'saved':True}

    def list(self,owner=None,binding=None):
        with self.db.connect() as q:
            sql='SELECT id,created,expires,payload FROM shared_cases WHERE expires>?';params=[time.time()]
            if owner is not None:sql+=' AND owner=? AND binding=?';params.extend([owner,binding])
            rows=q.execute(sql+' ORDER BY created',tuple(params))
            return [{'id':r[0],'created':r[1],'expires':r[2],
                     'investigation_id':json.loads(r[3])['investigation_id'],
                     'photo_count':len(json.loads(r[3]).get('photos',[])),
                     'verification':'voluntarily shared; unverified'} for r in rows]

    def get(self,identity,owner=None,binding=None):
        with self.db.connect() as q:
            sql='SELECT payload FROM shared_cases WHERE id=? AND expires>?';params=[identity,time.time()]
            if owner is not None:sql+=' AND owner=? AND binding=?';params.extend([owner,binding])
            row=q.execute(sql,tuple(params)).fetchone()
            return json.loads(row[0]) if row else None

    def delete(self,identity,owner=None,binding=None):
        with self.db.connect() as q:
            sql='DELETE FROM shared_cases WHERE id=?';params=[identity]
            if owner is not None:sql+=' AND owner=? AND binding=?';params.extend([owner,binding])
            return q.execute(sql,tuple(params)).rowcount>0
