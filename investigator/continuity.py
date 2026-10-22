"""Signed, expiring device saves. The server keeps no checkpoint files or photos."""
import base64
import hashlib
import io
import time

from PIL import Image
from .engine import Investigation, Picture
from .models import Finding


def checkpoint(access, owner, case, references, reports, goal='general',binding='local'):
    pictures=[{**p.public(),'data':base64.b64encode(p.data).decode(),
               'target_data':base64.b64encode(p.target_data).decode() if p.target_data else None} for p in case.pictures]
    body={'version':1,'owner':owner,'binding':binding,'expires':int(time.time()+7*86400),'turns':case.turns,
          'pictures':pictures,'references':references,'reports':reports,'decision_goal':goal}
    token=access.sign('checkpoint',body)
    if len(token)>10_000_000:raise ValueError('This investigation is too large to save on device.')
    return {'token':token,'expires':body['expires'],'title':case.turns[-1]['finding']['title'] if case.turns else 'Investigation'}


def restore(access, owner, token,binding='local'):
    body=access.verify('checkpoint',token,10_000_000)
    if body['owner']!=owner or body.get('version')!=1 or body.get('binding','local')!=binding:raise ValueError('This saved investigation belongs to another invitation.')
    if len(body['pictures'])>4 or len(body['turns'])>10:raise ValueError('Saved investigation exceeds limits.')
    pictures=[]
    for index,p in enumerate(body['pictures'],1):
        data=base64.b64decode(p['data'],validate=True)
        if len(data)>6_000_000 or hashlib.sha256(data).hexdigest()!=p['sent_sha256'] or p['id']!=f'P{index}':raise ValueError('Invalid saved image')
        with Image.open(io.BytesIO(data)) as image:
            if image.format!='JPEG' or max(image.size)>1800:raise ValueError('Invalid saved dimensions')
            image.verify()
        target=base64.b64decode(p['target_data'],validate=True) if p['target_data'] else None
        if target and hashlib.sha256(target).hexdigest()!=p['target_sha256']:raise ValueError('Invalid saved crop')
        pictures.append(Picture(p['id'],data,p['uploaded_sha256'],p['sent_sha256'],p['width'],p['height'],p['region'],target))
    for turn in body['turns']:Finding.model_validate(turn['finding'])
    goal=body.get('decision_goal','general')
    if goal not in ('general','dc_adapter','filter','thread'):raise ValueError('Invalid saved goal')
    return Investigation(turns=body['turns'],pictures=pictures),body['references'],body.get('reports',[]),goal
