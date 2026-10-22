"""Local application server. Temporary sessions; no photo files or external storage."""
from __future__ import annotations

import argparse
import base64
import ipaddress
import hashlib
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import secrets
import threading
import time
import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .engine import SYSTEM_PROMPT, Investigation, build_context, gate_finding, normalize_image, safe_finding, safety_trigger
from .models import TurnInput, ImageInput, Specification
from .provider import Gemini, ProviderError
from .research import research
from .access import Access
from .continuity import checkpoint, restore
from .feedback import FeedbackStore
from .storage import Database, ControlStore, StorageUnavailable
from .ledger import add_reports, decision_record, constrain_finding, capture_action, local_finding

STATIC = Path(__file__).with_name("static")
TTL = 1800
PHOTO_MEMORY_LIMIT = 32_000_000  # encoded photos/crops across all sessions, excluding temporary decode buffers


@dataclass
class Session:
    csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    touched: float = field(default_factory=time.monotonic)
    case: Investigation = field(default_factory=Investigation)
    lock: threading.Lock = field(default_factory=threading.Lock)
    references: dict | None = None
    reference_requests: int = 0
    owner: str = 'local'
    reports: list = field(default_factory=list)
    decision_goal: str = 'general'
    binding: str = 'local'
    rejected_answers: list = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)


def create_app(provider=None, max_calls: int = 30, allow_lan: bool = False, access=None, enable_ledger=True, feedback_path=None, control=None) -> FastAPI:
    provider = provider or Gemini()
    access = access or Access.configured()
    if access.beta:
        target=os.environ.get('VI_DATABASE_URL') or os.environ.get('VI_STATE_PATH') or feedback_path
        if control is None and not target:
            raise ValueError('Private beta requires durable VI_DATABASE_URL (or a persistent VI_STATE_PATH). No ephemeral fallback is allowed.')
        control=control or ControlStore(Database(target))
        control.seed(access.invites)
        access.registry=control
        feedback=FeedbackStore(control.db)
    else:
        feedback=FeedbackStore(feedback_path or os.environ.get('VI_FEEDBACK_PATH','.cache/visual-investigator/feedback.sqlite3'))
    sessions: dict[str, Session] = {}
    calls = {"total": 0, "recent": []}
    budget_lock = threading.Lock()
    member_calls = {}
    login_attempts = []
    member_requests = {}
    model_slots = asyncio.Semaphore(2)
    image_slots = asyncio.Semaphore(1)
    upload_slots = asyncio.Semaphore(2)

    def public(session):
        record=decision_record(session.decision_goal,session.reports) if enable_ledger else None
        return {**session.case.public(),'references':session.references,'reports':session.reports,
                'decision_goal':session.decision_goal,'reported_decision':record}

    async def bounded_json(request,maximum=8000):
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>maximum:raise ProviderError('This request exceeds the size limit.',413)
        try:
            value=json.loads(raw)
            if not isinstance(value,dict):raise ValueError()
            return value
        except ValueError:raise ProviderError('Send a valid JSON object.',422) from None

    def expire():
        now = time.monotonic()
        for sid, session in list(sessions.items()):
            if now - session.touched > TTL and not session.lock.locked():
                sessions.pop(sid, None)

    def check_photo_capacity(current, pictures):
        size=lambda ps:sum(len(p.data)+len(p.target_data or b'') for p in ps)
        used=sum(size(s.case.pictures) for s in sessions.values() if s is not current)
        if used+size(pictures)>PHOTO_MEMORY_LIMIT:
            raise ProviderError('Photo memory is full. Your existing investigation is unchanged; try later.',503)

    @asynccontextmanager
    async def lifespan(_):
        async def cleanup():
            while True:
                await asyncio.sleep(60)
                expire()
        task = asyncio.create_task(cleanup())
        yield
        task.cancel()
        sessions.clear()

    app = FastAPI(title="Visual Investigator", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.sessions = sessions
    app.state.provider_calls = calls
    app.state.control=control

    @app.middleware("http")
    async def privacy_and_origin(request: Request, call_next):
        host = request.url.hostname
        allowed = host in ("localhost", "127.0.0.1", "::1", "testserver")
        if not allowed and allow_lan:
            try:
                allowed = ipaddress.ip_address(host).is_private
            except ValueError:
                pass
        if access.beta:
            from urllib.parse import urlparse
            allowed=host==urlparse(access.origin).hostname
            if request.url.path!='/healthz' and (not allowed or request.url.scheme!='https'):
                return JSONResponse({'error':'Use the configured HTTPS beta address.'},status_code=400)
        if not allowed and request.url.path!='/healthz':
            return JSONResponse({"error": "Use this server's local address."}, status_code=400)
        if request.method in ("POST", "DELETE"):
            origin = request.headers.get("origin")
            expected = access.origin if access.beta else f"{request.url.scheme}://{request.url.netloc}"
            if origin and origin != expected:
                return JSONResponse({"error": "This request must come from the application."}, status_code=403)
        try:member=None if request.url.path=='/healthz' else access.identify(request.cookies.get('__Host-vi_access'))
        except StorageUnavailable:
            return JSONResponse({'error':'Private access storage is temporarily unavailable. Nothing was sent to the model.','category':'infrastructure'},status_code=503)
        request.state.member=member
        if access.beta and not member and request.url.path.startswith('/api/') and request.url.path!='/api/access':
            return JSONResponse({'error':'Open your private invite to join this beta.'},status_code=401)
        if access.beta and member and request.method=='POST':
            now=time.monotonic();recent=member_requests.setdefault(member['id'],[])
            recent[:]=[stamp for stamp in recent if now-stamp<60]
            if len(recent)>=30:return JSONResponse({'error':'Please wait before sending more requests.'},status_code=429)
            recent.append(now)
        if request.method=='POST' and request.url.path in ('/api/turn','/api/prepare-image','/api/restore'):
            # Bound large JSON buffers before reading/decoding them, not only
            # the later image/model work. Reject rather than queue photo bodies.
            if upload_slots.locked():return JSONResponse({'error':'Two uploads or investigations are already running. Your evidence is unchanged; try shortly.','category':'infrastructure'},status_code=503)
            async with upload_slots:response=await call_next(request)
        else:response = await call_next(request)
        sid = request.cookies.get("vi_session")
        if sid in sessions:
            response.set_cookie("vi_session", sid, httponly=True, samesite="strict", secure=request.url.scheme == "https", max_age=TTL)
        return response

    @app.middleware('http')
    async def security_headers(request:Request,call_next):
        # Wrap early auth/origin rejections too, so a private response is never cacheable.
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Permissions-Policy']='camera=(self), microphone=(), geolocation=()'
        if access.beta:response.headers['Strict-Transport-Security']='max-age=31536000'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    def session_for(request, mutation=False):
        expire()
        session = sessions.get(request.cookies.get("vi_session", ""))
        if session is None or not request.state.member or session.owner!=request.state.member['id'] or session.binding!=request.state.member.get('binding','local'):
            raise ProviderError("This temporary session expired. Refresh the page to start again.", 401)
        if mutation and request.headers.get("x-csrf-token") != session.csrf:
            raise ProviderError("Refresh this page before sending another request.", 403)
        session.touched = time.monotonic()
        return session

    @app.exception_handler(ProviderError)
    async def provider_error(_, exc):
        return JSONResponse({"error": str(exc),'category':exc.category}, status_code=exc.status)

    @app.exception_handler(StorageUnavailable)
    async def storage_error(_,exc):
        return JSONResponse({'error':'Private storage is unavailable. No successful save or access change is assumed.','category':'infrastructure'},status_code=503)

    @app.get('/healthz')
    def health():return {'ok':True}

    @app.post('/api/access')
    async def join(request:Request):
        now=time.monotonic()
        with budget_lock:
            login_attempts[:]=[stamp for stamp in login_attempts if now-stamp<60]
            if len(login_attempts)>=12:raise ProviderError('Too many invite attempts. Wait a minute.',429)
            login_attempts.append(now)
        value=await bounded_json(request,1024)
        code=value.get('code','')
        token=access.redeem(code) if isinstance(code,str) and 16<=len(code)<=128 else None
        if not token:raise ProviderError('This invite is invalid, expired or revoked.',403)
        if value.get('eligible') is not True:raise ProviderError('This Free Tier beta is for adults 18+ in supported regions outside the EEA, UK and Switzerland. Confirm eligibility before joining.',403)
        response=JSONResponse({'ok':True})
        response.set_cookie('__Host-vi_access',token,httponly=True,secure=True,samesite='strict',max_age=access.cookie_seconds,path='/')
        return response

    @app.post('/api/logout')
    async def logout(request:Request):
        session=session_for(request,True)
        sessions.pop(request.cookies.get('vi_session'),None)
        response=JSONResponse({'ok':True});response.delete_cookie('__Host-vi_access',secure=True,httponly=True,samesite='strict')
        response.delete_cookie('vi_session');return response

    @app.get("/api/session")
    def bootstrap(request: Request):
        expire()
        sid = request.cookies.get("vi_session")
        if sid not in sessions or sessions[sid].owner!=request.state.member['id'] or sessions[sid].binding!=request.state.member.get('binding','local'):
            if len(sessions) >= 32:
                raise ProviderError("This local server has too many active sessions. Try later.", 503)
            sid = secrets.token_urlsafe(32)
            sessions[sid] = Session(owner=request.state.member['id'],binding=request.state.member.get('binding','local'))
        session = sessions[sid]
        session.touched = time.monotonic()
        response = JSONResponse({"csrf": session.csrf, "provider": provider.name, "model": provider.model,
            "model_ready": provider.ready(), "expires_in_seconds": TTL, "mode": "live" if isinstance(provider, Gemini) else "test",
            **public(session), 'member':{k:request.state.member[k] for k in ('id','role')},'private_beta':access.beta,'ledger_enabled':enable_ledger})
        response.set_cookie("vi_session", sid, httponly=True, samesite="strict", secure=request.url.scheme == "https", max_age=TTL)
        return response

    @app.post("/api/turn")
    async def turn(request: Request):
        session = session_for(request, True)
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise ProviderError("Send the question and photo as JSON.", 415)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 8_200_000:
                raise ProviderError("That upload is too large. Choose a smaller photo.", 413)
        try:
            value = TurnInput.model_validate_json(raw)
        except (ValidationError, ValueError):
            raise ProviderError("Check your question and choose a JPEG, PNG, or WebP photo under 6 MB.", 422) from None
        if not value.question.strip() and value.image is None:
            raise ProviderError("Add a photo or a question to continue.", 422)
        if not value.consent:
            raise ProviderError("Allow the photo and question to be sent to Gemini before investigating.", 400)
        if not session.lock.acquire(blocking=False):
            raise ProviderError("One answer is already being prepared. Please wait.", 409)
        try:
            case = session.case
            if len(case.turns) >= 10:
                raise ProviderError("This investigation has reached ten turns. Export the record and start a new one.", 409)
            if not case.pictures and value.image is None:
                raise ProviderError("Add a photo to start the investigation.", 422)
            if value.image is not None and len(case.pictures) >= 4:
                raise ProviderError("This investigation already has four photos. Add a text observation or start another case.", 409)
            pictures = list(case.pictures)
            if value.image is not None:
                try:
                    if image_slots.locked():raise ProviderError('Another photo is being prepared. Try again shortly.',409)
                    async with image_slots:
                        picture = await asyncio.to_thread(normalize_image, value.image, f"P{len(pictures)+1}")
                    if value.image.conversion_receipt:
                        receipt=access.verify('conversion',value.image.conversion_receipt,2048)
                        if receipt['owner']!=session.owner or receipt.get('binding','local')!=session.binding or receipt['preview_sha256']!=picture.uploaded_sha256:raise ValueError('Conversion receipt does not match the uploaded photo.')
                        picture.uploaded_sha256=receipt['original_sha256']
                except ValueError as exc:
                    raise ProviderError(str(exc), 422) from None
                pictures.append(picture)
            check_photo_capacity(session,pictures)
            text_id = f"T{len(case.turns)+1}"
            context = build_context(case, value.question, text_id, pictures)
            goal=value.decision_goal if value.decision_goal!='general' else session.decision_goal
            if enable_ledger and session.reports:
                data=json.loads(context);data['confirmed_user_reports']=session.reports;data['comparison_goal']=goal
                context=json.dumps(data)
            evidence = {p.id: "image" for p in pictures} | {f"T{i+1}": "text" for i in range(len(case.turns)+1)}
            evidence.update({p.id+":target": "image" for p in pictures if p.target_data})
            evidence.update({r['id']:'text' for r in session.reports})
            all_text = "\n".join([t["question"] for t in case.turns] + [value.question])
            called = False
            usage = {}
            reason='model_interpretation'
            local=local_finding(decision_record(goal,session.reports)) if enable_ledger else None
            if safety_trigger(all_text):
                finding = safe_finding()
                reason='precautionary_safety_stop'
            elif local is not None:
                finding=local;reason='reported_evidence_rule'
            else:
                if model_slots.locked():raise ProviderError('Two investigations are already running. Your evidence is unchanged; try shortly.',409)
                with budget_lock:
                    now = time.monotonic()
                    calls["recent"] = [t for t in calls["recent"] if now-t < 60]
                    if calls["total"] >= max_calls:
                        raise ProviderError("This server's model-call budget is used up. No additional request was sent.", 429)
                    if len(calls["recent"]) >= 8:
                        raise ProviderError("Please wait a minute before another investigation request.", 429)
                    if control:
                        try:control.reserve(session.owner)
                        except ValueError as exc:raise ProviderError(str(exc),429) from None
                    calls["total"] += 1
                    calls["recent"].append(now)
                called = True
                async with model_slots:
                    try:finding, usage = await asyncio.to_thread(provider.investigate, context, pictures)
                    except ProviderError as exc:
                        if exc.private_response:
                            session.rejected_answers=(session.rejected_answers+[{'turn':text_id,'response':exc.private_response,'reason':'invalid_answer_format'}])[-10:]
                        if control and exc.status in (429,503):control.pause_provider()
                        raise
                from .engine import recover_finding
                original=finding.model_dump()
                finding,recovered=recover_finding(finding,evidence,all_text)
                if recovered:
                    session.rejected_answers=(session.rejected_answers+[{'turn':text_id,'response':original,'reason':'invalid_evidence_citation'}])[-10:]
                    reason='evidence_recovery'
                if enable_ledger:finding=constrain_finding(finding,decision_record(goal,session.reports))
            # Commit only after a complete, validated answer. Failed turns leave context intact.
            check_photo_capacity(session,pictures)
            record = {"id": text_id, "question": value.question, "picture_id": pictures[-1].id if value.image else None,
                      "finding": finding.model_dump(), "provider_called": called,
                      "protocol_version": "product-v0.3-beta-evidence", "model": provider.model,
                      "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
                      "usage": {k: v for k, v in usage.items() if k in ("promptTokenCount", "candidatesTokenCount", "totalTokenCount")},
                      'capture_action':capture_action(finding.next_question)}
            record['response_kind']=reason
            case.pictures = pictures
            case.turns.append(record)
            session.decision_goal=goal
            session.touched = time.monotonic()
            return {**public(session), "provider": provider.name}
        finally:
            session.lock.release()

    @app.get("/api/images/{picture_id}")
    def image(picture_id: str, request: Request):
        session = session_for(request)
        picture = next((p for p in session.case.pictures if p.id == picture_id), None)
        if picture is None:
            return Response(status_code=404)
        return Response(picture.data, media_type="image/jpeg")

    @app.get("/api/images/{picture_id}/target")
    def target_image(picture_id: str, request: Request):
        session = session_for(request)
        picture = next((p for p in session.case.pictures if p.id == picture_id), None)
        if picture is None or picture.target_data is None:
            return Response(status_code=404)
        return Response(picture.target_data, media_type="image/jpeg")

    @app.post("/api/research")
    async def official_references(request: Request):
        session = session_for(request, True)
        if not session.lock.acquire(blocking=False):
            raise ProviderError("Wait for the current request before consulting references.", 409)
        try:
            if not session.case.turns:
                raise ProviderError("Start an investigation before consulting references.", 400)
            if session.reference_requests >= 6:
                raise ProviderError("This investigation has reached its reference-lookup limit. Existing sources are still available.", 429)
            session.reference_requests += 1
            latest = session.case.turns[-1]
            query = " ".join(t["question"] for t in session.case.turns) + " " + latest["finding"]["title"] + " " + latest["finding"]["answer"]
            result = await asyncio.to_thread(research, query)
            session.references = {**result, "context_turn": latest["id"]}
            return session.references
        finally:
            session.lock.release()

    @app.post("/api/reset")
    def reset(request: Request):
        session = session_for(request, True)
        if not session.lock.acquire(blocking=False):
            raise ProviderError("Wait for the current answer before starting a new case.", 409)
        try:
            session.case = Investigation()
            session.references = None
            session.reference_requests = 0
            session.reports=[];session.decision_goal='general';session.rejected_answers=[];session.started=time.monotonic()
            return {"ok": True}
        finally:
            session.lock.release()

    @app.get("/api/export")
    def export(request: Request):
        session = session_for(request)
        return {"product": "Visual Investigator", "verification": "Unverified AI investigation; image readings and user reports are not certified specifications.",
                **public(session)}

    @app.post('/api/specifications')
    async def specifications(request:Request):
        if not enable_ledger:raise ProviderError('The experimental specification ledger is disabled.',404)
        session=session_for(request,True);value=await bounded_json(request)
        if not session.lock.acquire(blocking=False):raise ProviderError('Wait for the current answer.',409)
        try:
            goal=value.get('goal',session.decision_goal)
            if goal not in ('general','dc_adapter','filter','thread'):raise ValueError('Choose a supported comparison goal.')
            additions=[Specification.model_validate(r).model_dump() for r in value.get('reports',[])]
            reports=add_reports(session.reports,additions,{p.id for p in session.case.pictures})
            session.reports=reports;session.decision_goal=goal
            return public(session)
        except (ValueError,TypeError) as exc:raise ProviderError('Check specification, unit, photo and correction fields.',422) from None
        finally:session.lock.release()

    @app.post('/api/prepare-image')
    async def prepare_image(request:Request):
        session=session_for(request,True);value=await bounded_json(request,8_200_000)
        try:
            if image_slots.locked():raise ProviderError('Another photo is being prepared. Try again shortly.',409)
            async with image_slots:
                picture=await asyncio.to_thread(normalize_image,ImageInput.model_validate(value),'preview')
            from PIL import ImageStat, Image
            import io
            with Image.open(io.BytesIO(picture.data)) as im:
                brightness=ImageStat.Stat(im.convert('L')).mean[0]
            warning='This photo may be very dark or overexposed. Check that the target and label are readable.' if brightness<25 or brightness>245 else ''
            return {'data':base64.b64encode(picture.data).decode(),'mime_type':'image/jpeg','width':picture.width,'height':picture.height,'capture_warning':warning,
                    'conversion_receipt':access.sign('conversion',{'owner':session.owner,'binding':session.binding,'original_sha256':picture.uploaded_sha256,'preview_sha256':picture.sent_sha256,'expires':time.time()+1800}),
                    'notice':'Converted on this private server; no model request made. Original metadata removed.'}
        except (ValueError,ValidationError):raise ProviderError('Choose a supported still photo under 6 MB and 20 megapixels.',422) from None

    @app.post('/api/checkpoint')
    async def save_device(request:Request):
        session=session_for(request,True)
        if not session.lock.acquire(blocking=False):raise ProviderError('Wait for the current answer.',409)
        try:return checkpoint(access,session.owner,session.case,session.references,session.reports,session.decision_goal,binding=session.binding)
        except ValueError as exc:raise ProviderError(str(exc),422) from None
        finally:session.lock.release()

    @app.post('/api/restore')
    async def restore_device(request:Request):
        session=session_for(request,True);value=await bounded_json(request,10_100_000)
        if not session.lock.acquire(blocking=False):raise ProviderError('Wait for the current answer.',409)
        try:
            case,refs,reports,goal=restore(access,session.owner,value.get('token',''),binding=session.binding)
            check_photo_capacity(session,case.pictures)
            session.case=case;session.references=refs;session.reports=reports
            session.decision_goal=goal;session.rejected_answers=[];session.started=time.monotonic()
            return public(session)
        except (ValueError,KeyError,TypeError):raise ProviderError('This device save is invalid, expired, or belongs to another member.',422) from None
        finally:session.lock.release()

    @app.post('/api/feedback')
    async def submit_feedback(request:Request):
        session=session_for(request,True);value=await bounded_json(request,4000)
        if set(value)-{'outcome','note','share_reference','detail'}:raise ProviderError('Feedback accepts outcomes and optional notes, never photos or a conversation.',422)
        if value.get('outcome') not in ('solved','helped_stuck','wrong','not_found'):raise ProviderError('Choose an outcome.',422)
        note=value.get('note','');reference=value.get('share_reference','')
        if not isinstance(note,str) or len(note)>1000 or not isinstance(reference,str) or len(reference)>80:raise ProviderError('Keep the optional note short.',422)
        detail=value.get('detail')
        if detail is not None:
            allowed={'completion':('yes','no','unclear'),'source_usefulness':('helpful','unhelpful','unused'),
                     'unsupported_advice':('yes','no','unsure'),'infrastructure_problem':('yes','no','unsure')}
            if not isinstance(detail,dict) or any(k not in allowed or v not in allowed[k] for k,v in detail.items()):raise ProviderError('Choose the optional feedback details from the provided choices.',422)
            detail=detail|{'successful_turns':len(session.case.turns),'photos':len(session.case.pictures),'session_seconds':int(time.monotonic()-session.started),
                          'correctly_unresolved':'requires voluntary evidence review','verification':'user_report_only'}
        try:identity=feedback.add(session.owner,value['outcome'],note,reference,detail)
        except ValueError:raise ProviderError('Feedback could not be saved; keep your downloaded copy.',503) from None
        return {'id':identity,'saved':True,'notice':'Your chosen outcome and note were saved for 14 days. Photos/conversation were not collected. This is your reported experience, not independent verification.'}

    @app.get('/api/feedback/export')
    def export_feedback(request:Request):
        session_for(request)
        if request.state.member['role']!='owner':raise ProviderError('Only the beta owner can export submitted feedback.',403)
        return {'feedback':feedback.export(),'retention_days':14,'photos_collected':False}

    @app.get('/api/owner/report')
    def owner_report(request:Request):
        session_for(request)
        if request.state.member['role']!='owner':raise ProviderError('Only the beta owner can review feedback.',403)
        return feedback.summary() | {'members':control.members() if control else [],'beta_enabled':control.enabled() if control else True}

    @app.post('/api/owner/access')
    async def owner_access(request:Request):
        session_for(request,True)
        if request.state.member['role']!='owner' or not control:raise ProviderError('Only the private beta owner can change access.',403)
        value=await bounded_json(request,200)
        if set(value)=={'revoke'} and isinstance(value['revoke'],str):
            if value['revoke']==request.state.member['id']:raise ProviderError('Use the local administrator tool to revoke your own owner access.',422)
            return {'revoked':control.revoke(value['revoke'])}
        if value=={'disable':True}:control.set_enabled(False);return {'enabled':False}
        raise ProviderError('Choose one invitation to revoke, or disable the beta.',422)

    @app.post('/api/share-case')
    async def share_case(request:Request):
        session=session_for(request,True);value=await bounded_json(request,200)
        if value.get('consent') is not True:raise ProviderError('Explicitly choose to export the conversation and photos.',400)
        if session.lock.locked():raise ProviderError('Wait for the current answer.',409)
        return {'product':'Visual Investigator','verification':'Unverified AI case evidence, shared voluntarily.',**public(session),
                'rejected_model_answers':session.rejected_answers,
                'private_photos':[{'id':p.id,'mime_type':'image/jpeg','data':base64.b64encode(p.data).decode()} for p in session.case.pictures]}

    @app.get("/")
    def home(request:Request):
        return FileResponse(STATIC / ("index.html" if request.state.member else 'join.html'))

    @app.get('/sw.js')
    def worker():return FileResponse(STATIC/'sw.js',media_type='application/javascript',headers={'Service-Worker-Allowed':'/'})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description="Launch the local Visual Investigator app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get('PORT','8765')))
    parser.add_argument("--max-calls", type=int, default=int(os.environ.get('VI_MAX_CALLS','30')), help="Lifetime model request cap, including failed requests.")
    parser.add_argument('--experimental-ledger',action='store_true',help='Opt into the unproven reported-specification workflow.')
    args = parser.parse_args()
    access=Access.configured()
    uvicorn.run(create_app(max_calls=args.max_calls, access=access, enable_ledger=args.experimental_ledger, allow_lan=args.host not in ("127.0.0.1", "localhost", "::1")), host=args.host, port=args.port, access_log=False,proxy_headers=True,forwarded_allow_ips=os.environ.get('FORWARDED_ALLOW_IPS','127.0.0.1'))


if __name__ == "__main__":
    main()
