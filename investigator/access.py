"""Invite access and signed device checkpoints. No external identity service."""
import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time

from dotenv import dotenv_values


def encode(raw): return base64.urlsafe_b64encode(raw).decode().rstrip('=')
def decode(value): return base64.urlsafe_b64decode(value+'='*(-len(value)%4))


@dataclass
class Access:
    beta: bool = False
    origin: str = ''
    secret: bytes = field(default_factory=lambda: secrets.token_bytes(32), repr=False)
    invites: dict = field(default_factory=dict, repr=False)
    cookie_seconds: int = 7*86400
    registry: object = field(default=None,repr=False)

    @classmethod
    def configured(cls):
        local=dotenv_values(Path(__file__).resolve().parents[1]/'.env')
        def get(name, default=''):return os.environ.get(name, local.get(name,default))
        beta=get('VI_MODE')=='private-beta'
        origin=get('VI_PUBLIC_ORIGIN') or get('RENDER_EXTERNAL_URL')
        secret=get('VI_SESSION_SECRET')
        if beta:
            from urllib.parse import urlparse
            url=urlparse(origin)
            if url.scheme!='https' or not url.hostname or url.username or url.password or url.path not in ('','/') or url.query or url.fragment:
                raise ValueError('Private beta requires a canonical HTTPS public origin.')
            if len(secret)<43:raise ValueError('Private beta requires a stable high-entropy session secret.')
            invites=json.loads(get('VI_INVITE_HASHES','{}'))
            if not invites or len(invites)>20:raise ValueError('Configure 1–20 individual invite records.')
            for identity, record in invites.items():
                if not identity or identity=='*' or len(identity)>40 or not isinstance(record,dict) or len(record.get('sha256',''))!=64 or record.get('role') not in ('member','owner') or not isinstance(record.get('expires'),(int,float)):
                    raise ValueError('Invalid private-beta invite configuration.')
            return cls(True,origin.rstrip('/'),secret.encode(),invites)
        # Stable local signing key permits intentional device saves across local restarts.
        path=Path('.cache/visual-investigator/local-session-secret')
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():
            try:
                fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                with os.fdopen(fd,'wb') as stream:stream.write(secrets.token_bytes(32))
            except FileExistsError:pass
        key=path.read_bytes()
        if len(key)!=32:raise ValueError('Local signing configuration is invalid; device saves cannot be verified.')
        return cls(secret=key)

    def sign(self, purpose, body):
        payload=encode(json.dumps(body,separators=(',',':'),ensure_ascii=True).encode())
        tag=hmac.new(self.secret,(purpose+'.'+payload).encode(),hashlib.sha256).digest()
        return payload+'.'+encode(tag)

    def verify(self, purpose, token, maximum=12_000_000):
        if not isinstance(token,str) or len(token)>maximum:raise ValueError('Invalid signed record')
        try:
            payload,tag=token.split('.')
            expected=hmac.new(self.secret,(purpose+'.'+payload).encode(),hashlib.sha256).digest()
            if not hmac.compare_digest(decode(tag),expected):raise ValueError()
            body=json.loads(decode(payload))
            if body['expires']<=time.time():raise ValueError()
            return body
        except (ValueError,KeyError,TypeError,UnicodeError):raise ValueError('Invalid or expired signed record') from None

    def identify(self, cookie):
        if not self.beta:return {'id':'local','role':'owner'}
        try:
            value=self.verify('login',cookie or '',2048)
            if self.registry and not self.registry.enabled():return None
            configured=self.registry.member(value['id']) if self.registry else self.invites.get(value['id'])
            if not configured or configured['expires']<=time.time() or configured['sha256']!=value['invite_version']:
                return None
            return {'id':value['id'],'role':configured['role'],'binding':configured['sha256']}
        except (ValueError,KeyError):return None

    def redeem(self, code):
        digest=hashlib.sha256(code.encode()).hexdigest()
        if self.registry:
            if not self.registry.enabled():return None
            identity=self.registry.lookup(digest)
            record=self.registry.member(identity) if identity else None
            if not record:return None
            return self.sign('login',{'id':identity,'invite_version':digest,'expires':min(time.time()+self.cookie_seconds,record['expires'])})
        for identity, record in self.invites.items():
            if hmac.compare_digest(digest,record['sha256']) and record['expires']>time.time():
                return self.sign('login',{'id':identity,'invite_version':digest,'expires':min(time.time()+self.cookie_seconds,record['expires'])})
        return None
