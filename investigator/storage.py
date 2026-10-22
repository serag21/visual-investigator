"""Small durable control store. SQLite locally, TLS PostgreSQL on ephemeral hosts.

Never stores photos, prompts or model answers. Transactions protect quota and
revocation across processes. Configuration URLs are never included in errors.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time


class StorageUnavailable(Exception):pass


class Database:
    def __init__(self,target):
        self.postgres=str(target).startswith(('postgres://','postgresql://'))
        self.target=str(target)
        if not self.postgres:Path(self.target).parent.mkdir(parents=True,exist_ok=True)

    @contextmanager
    def connect(self):
        try:
            if self.postgres:
                import psycopg
                connection=psycopg.connect(self.target,sslmode='verify-full',sslrootcert='system',connect_timeout=8)
            else:connection=sqlite3.connect(self.target,timeout=8)
            try:
                yield Query(connection,self.postgres)
                connection.commit()
            except Exception:
                connection.rollback();raise
            finally:connection.close()
        except (sqlite3.Error,OSError) as exc:raise StorageUnavailable('Durable storage is unavailable; no access or feedback was assumed.') from None
        except Exception as exc:
            if exc.__class__.__module__.startswith('psycopg'):raise StorageUnavailable('Durable storage is unavailable; no access or feedback was assumed.') from None
            raise


class Query:
    def __init__(self,connection,postgres):self.connection=connection;self.postgres=postgres
    def execute(self,sql,params=()):return self.connection.execute(sql.replace('?','%s') if self.postgres else sql,params)


class ControlStore:
    def __init__(self,database):
        self.db=database
        with self.db.connect() as q:
            q.execute('CREATE TABLE IF NOT EXISTS beta_members (id TEXT PRIMARY KEY, digest TEXT NOT NULL, role TEXT NOT NULL, expires BIGINT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)')
            q.execute('CREATE TABLE IF NOT EXISTS beta_settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)')
            q.execute('CREATE TABLE IF NOT EXISTS beta_quota (member TEXT NOT NULL, day BIGINT NOT NULL, attempts INTEGER NOT NULL, PRIMARY KEY(member,day))')
            q.execute("INSERT INTO beta_settings VALUES ('enabled','1') ON CONFLICT(name) DO NOTHING")

    def seed(self,invites):
        with self.db.connect() as q:
            for identity,r in invites.items():
                # Existing records, especially revoked ones, NEVER resurrect from stale env.
                q.execute('INSERT INTO beta_members VALUES (?,?,?,?,0) ON CONFLICT(id) DO NOTHING',(identity,r['sha256'],r['role'],int(r['expires'])))

    def enabled(self):
        with self.db.connect() as q:return q.execute("SELECT value FROM beta_settings WHERE name='enabled'").fetchone()[0]=='1'

    def set_enabled(self,value):
        with self.db.connect() as q:q.execute("UPDATE beta_settings SET value=? WHERE name='enabled'",('1' if value else '0',))

    def member(self,identity):
        with self.db.connect() as q:r=q.execute('SELECT digest,role,expires,revoked FROM beta_members WHERE id=?',(identity,)).fetchone()
        return {'sha256':r[0],'role':r[1],'expires':r[2]} if r and not r[3] and r[2]>time.time() else None

    def lookup(self,digest):
        with self.db.connect() as q:r=q.execute('SELECT id FROM beta_members WHERE digest=? AND revoked=0 AND expires>?',(digest,int(time.time()))).fetchone()
        return r[0] if r else None

    def revoke(self,identity):
        with self.db.connect() as q:return q.execute('UPDATE beta_members SET revoked=1 WHERE id=?',(identity,)).rowcount>0

    def members(self):
        with self.db.connect() as q:
            return [{'id':r[0],'role':r[1],'expires':r[2],'revoked':bool(r[3])} for r in q.execute('SELECT id,role,expires,revoked FROM beta_members ORDER BY id')]

    def reserve(self,member,global_limit=30,member_limit=20):
        day=int(time.time()//86400)
        with self.db.connect() as q:
            if not q.postgres:q.execute('BEGIN IMMEDIATE')
            paused=q.execute("SELECT value FROM beta_settings WHERE name='provider_paused'").fetchone()
            if paused and paused[0]=='1':raise ValueError('Model access is paused after a provider rejection. No new request was sent.')
            for identity,limit in (('*',global_limit),(member,member_limit)):
                q.execute('INSERT INTO beta_quota VALUES (?,?,0) ON CONFLICT(member,day) DO NOTHING',(identity,day))
                result=q.execute('UPDATE beta_quota SET attempts=attempts+1 WHERE member=? AND day=? AND attempts<? RETURNING attempts',(identity,day,limit)).fetchone()
                if not result:raise ValueError('The daily beta model allowance is used. No new request was sent.')
            q.execute('DELETE FROM beta_quota WHERE day<?',(day-30,))

    def pause_provider(self):
        with self.db.connect() as q:q.execute("INSERT INTO beta_settings VALUES ('provider_paused','1') ON CONFLICT(name) DO UPDATE SET value='1'")

    def resume_provider(self):
        with self.db.connect() as q:q.execute("DELETE FROM beta_settings WHERE name='provider_paused'")
