"""Standalone Maritime web backend. Supabase Auth/PostgreSQL/private images.
Future Phase 2 connects through the authenticated ingest and command APIs.
No AI or flight-control implementation is included.
"""
import asyncio
import contextlib
import logging
import hashlib
import hmac
import io
import json
import warnings
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4
from urllib.parse import quote, urlsplit
from PIL import Image, UnidentifiedImageError

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

log = logging.getLogger("maritime.server")
Image.MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_BYTES = 10 * 1024 * 1024
auth = HTTPBearer(auto_error=False)

class SupabaseGateway:
    def __init__(self, client, url, secret):
        self.client, self.url, self.secret = client, url.rstrip('/'), secret

    async def request(self, path, method="GET", body=None, token=None, params=None, prefer=None, include_count=False):
        headers = {"apikey": self.secret, "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        # New sb_secret keys go in apikey, never as JWTs. User tokens only here.
        if token:
            headers["Authorization"] = "Bearer " + token
        elif self.secret.startswith("eyJ"):
            headers["Authorization"] = "Bearer " + self.secret
        try:
            response = await self.client.request(method, self.url + "/" + path,
                headers=headers, json=body, params=params)
        except httpx.RequestError:
            raise HTTPException(503, "The data service is unavailable")
        if response.status_code >= 400:
            if path == "auth/v1/user" and response.status_code in (401,403):
                raise HTTPException(401, "Invalid or expired session")
            if path == "auth/v1/admin/users" and response.status_code in (400,422):
                raise HTTPException(400,"Account could not be created; check email, password policy, and existing users")
            log.error("Data service request failed: path=%s status=%s", path.split('?')[0], response.status_code)
            raise HTTPException(503, "The data service could not complete this request")
        data = response.json() if response.content else None
        if include_count:
            total = response.headers.get('content-range', '*/0').rsplit('/', 1)[-1]
            if not total.isdigit():
                raise HTTPException(503, 'Archive count unavailable')
            return {'items': data, 'total': int(total)}
        return data

    async def rpc(self, name, body):
        return await self.request("rest/v1/rpc/" + name, "POST", body)

    async def member(self, user_id):
        rows = await self.request("rest/v1/profiles", params={"id":"eq."+user_id,"select":"id,display_name,role,active"})
        if not rows or not rows[0]["active"]:
            raise HTTPException(403,"Active workspace membership required")
        return rows[0]


class NotificationHub:
    def __init__(self):
        self.queues = set()
    async def publish(self, kind):
        for queue in tuple(self.queues):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait({"type":kind})

hub = NotificationHub()

async def expiry_loop(app):
    while True:
        try:
            count = await app.state.db.rpc("expire_pending_events", {})
            if count:
                await hub.publish("event.updated")
            app.state.last_expiry_success = time.monotonic()
        except Exception:
            log.exception("Pending-event expiry sweep failed")
        await asyncio.sleep(1)

def validate_environment():
    mode = os.environ.get('APP_ENV', 'production')
    if mode not in ('development', 'production'):
        raise RuntimeError('APP_ENV must be development or production')
    for key in ('SUPABASE_URL', 'SUPABASE_SECRET_KEY', 'SUPABASE_PUBLISHABLE_KEY', 'INGEST_API_KEY', 'ALLOWED_ORIGINS'):
        if not os.environ.get(key, '').strip():
            raise RuntimeError(key + ' is required')
    if len(os.environ['INGEST_API_KEY']) < 32:
        raise RuntimeError('INGEST_API_KEY must contain at least 32 characters')
    if not os.environ['SUPABASE_PUBLISHABLE_KEY'].startswith('sb_publishable_'):
        raise RuntimeError('SUPABASE_PUBLISHABLE_KEY must be a publishable key')
    values = [('SUPABASE_URL', os.environ['SUPABASE_URL'])]
    values += [('ALLOWED_ORIGINS', origin.strip()) for origin in os.environ['ALLOWED_ORIGINS'].split(',')]
    for name, value in values:
        u = urlsplit(value)
        local = mode == 'development' and name == 'ALLOWED_ORIGINS' and u.hostname in ('localhost', '127.0.0.1', '::1') and u.scheme == 'http'
        if (u.scheme != 'https' and not local) or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('', '/') or '*' in value:
            raise RuntimeError(name + ' must contain exact HTTPS origins (loopback HTTP allowed only in development)')
        if mode == 'production' and u.hostname in ('localhost', '127.0.0.1', '::1'):
            raise RuntimeError(name + ' cannot use loopback in production')

@asynccontextmanager
async def lifespan(app):
    validate_environment()
    url = os.environ.get("SUPABASE_URL", "")
    secret = os.environ.get("SUPABASE_SECRET_KEY", "")
    origins = os.environ.get("ALLOWED_ORIGINS", "")
    if not url.startswith("https://") or not secret or not origins:
        raise RuntimeError("SUPABASE_URL, SUPABASE_SECRET_KEY and ALLOWED_ORIGINS are required")
    app.state.last_expiry_success = 0
    app.state.admin_rate = {}
    async with httpx.AsyncClient(timeout=10) as client:
        app.state.db = SupabaseGateway(client, url, secret)
        task = asyncio.create_task(expiry_loop(app))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

app = FastAPI(title="Maritime Operations API", version="3.1.0", lifespan=lifespan,
    docs_url="/docs" if os.environ.get("APP_ENV")=="development" else None, redoc_url=None,
    openapi_url="/openapi.json" if os.environ.get("APP_ENV")=="development" else None)
app.add_middleware(CORSMiddleware,
    allow_origins=[o.strip().rstrip('/') for o in os.environ.get("ALLOWED_ORIGINS", "").split(',') if o.strip()],
    allow_methods=["GET","POST","PATCH","DELETE"],
    allow_headers=["Authorization","Content-Type","Idempotency-Key"],
    allow_credentials=False)

async def member(credentials: HTTPAuthorizationCredentials | None = Depends(auth)):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401,"A bearer session is required")
    user = await app.state.db.request("auth/v1/user", token=credentials.credentials)
    if not user or not user.get("id"):
        raise HTTPException(401,"Invalid session")
    security = await app.state.db.request("rest/v1/rpc/current_session_security", "POST", {}, token=credentials.credentials)
    if not isinstance(security, dict) or security.get("aal") != "aal2" or security.get("user_id") != user["id"]:
        raise HTTPException(403, "Authenticator verification required")
    return await app.state.db.member(user["id"])

async def admin(user=Depends(member)):
    if user["role"] != "admin":
        raise HTTPException(403,"Administrator role required")
    return user

class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accepted","rejected"]
    expected_version: int = Field(ge=0)

class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(min_length=1,max_length=100)
    drone_id: str = Field(min_length=1,max_length=160)
    mission_id: str | None = None
    telemetry_timestamp: AwareDatetime
    reason: str = Field(min_length=1,max_length=300)

class AccessChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool


def rpc_response(result):
    status = int(result.get("code",500))
    if status not in (200,201,202,400,403,404,409):
        raise HTTPException(503,"Unexpected data-service response")
    return JSONResponse({k:v for k,v in result.items() if k!="code"},status_code=status)

@app.get("/health")
async def health():
    healthy = time.monotonic()-app.state.last_expiry_success<10
    return JSONResponse({"status":"ok" if healthy else "degraded","expiry_worker":healthy},status_code=200 if healthy else 503)

@app.get("/api/v1/me")
async def me(user=Depends(member)):
    return user

@app.get("/api/v1/capabilities")
async def capabilities(user=Depends(member)):
    commands = await app.state.db.request("rest/v1/command_capabilities",params={"select":"code,label,description,enabled,reason","order":"code.asc"})
    return {"commands":commands,"review_window_seconds":20}

@app.post("/api/v1/events/{event_id}/decision")
async def decide(event_id: str, payload: Decision, user=Depends(member)):
    result = await app.state.db.rpc("review_event",{
        "p_event_id":event_id,"p_actor_id":user["id"],
        "p_decision":payload.decision,"p_expected_version":payload.expected_version})
    if result.get("event"):
        await hub.publish("event.updated")
    return rpc_response(result)

@app.post("/api/v1/commands")
async def request_command(payload: Command, idempotency_key: UUID = Header(), user=Depends(member)):
    if not payload.reason.strip():
        raise HTTPException(422,"A reason is required")
    result = await app.state.db.rpc("request_command",{
        "p_actor_id":user["id"],"p_request_key":str(idempotency_key),
        "p_command":payload.command,"p_drone_id":payload.drone_id,
        "p_mission_id":payload.mission_id,"p_telemetry_timestamp":payload.telemetry_timestamp.isoformat(),
        "p_reason":payload.reason.strip()})
    if result.get("command"):
        await hub.publish("command.updated")
    return rpc_response(result)

@app.get("/api/v1/commands")
async def command_history(limit: int = Query(25,ge=1,le=100), user=Depends(member)):
    params = {"select":"*","order":"created_at.desc","limit":str(limit)}
    if user["role"]!="admin":
        params["actor_id"]="eq."+user["id"]
    return {"items":await app.state.db.request("rest/v1/command_requests",params=params)}

@app.get("/api/v1/admin/users")
async def users(user=Depends(admin)):
    profiles=await app.state.db.request("rest/v1/profiles",params={"select":"id,display_name,role,active,created_at","order":"created_at.desc"})
    identities=await app.state.db.request("rest/v1/login_identities",params={"select":"user_id,login_id"})
    mapping={row["user_id"]:row["login_id"] for row in identities}
    return {"items":[{**row,"login_id":mapping.get(row["id"])} for row in profiles]}

@app.patch("/api/v1/admin/users/{user_id}")
async def update_user(user_id: UUID,payload: AccessChange,user=Depends(admin)):
    result = await app.state.db.rpc("set_member_access",{
        "p_actor_id":user["id"],"p_user_id":str(user_id),"p_active":payload.active})
    await hub.publish("access.updated")
    return rpc_response(result)

@app.get("/api/v1/admin/audit")
async def audit(limit: int = Query(30,ge=1,le=100),user=Depends(admin)):
    return {"items":await app.state.db.request("rest/v1/audit_log",params={"select":"*","order":"created_at.desc","limit":str(limit)})}

@app.post("/api/v1/ws-ticket")
async def ws_ticket(user=Depends(member)):
    ticket = secrets.token_urlsafe(32)
    await app.state.db.request("rest/v1/ws_tickets", "POST", {
        "ticket_hash":hashlib.sha256(ticket.encode()).hexdigest(), "user_id":user["id"],
        "expires_at":(datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat()})
    return {"ticket":ticket,"expires_in":30}

@app.websocket("/api/v1/ws")
async def websocket(ws: WebSocket, ticket: str = ""):
    allowed = [o.strip().rstrip('/') for o in os.environ.get("ALLOWED_ORIGINS","").split(',')]
    if ws.headers.get("origin") not in allowed or not ticket or len(ticket)>100:
        await ws.close(code=1008)
        return
    user_id = await app.state.db.rpc("consume_ws_ticket", {"p_hash":hashlib.sha256(ticket.encode()).hexdigest()})
    if not user_id:
        await ws.close(code=1008)
        return
    try:
        await app.state.db.member(user_id)
    except HTTPException:
        await ws.close(code=1008)
        return
    await ws.accept()
    queue=asyncio.Queue(maxsize=1)
    hub.queues.add(queue)
    connected=time.monotonic()
    try:
        await ws.send_json({"type":"event.updated"})
        while time.monotonic()-connected<300:
            try:
                notification=await asyncio.wait_for(queue.get(),timeout=10)
            except asyncio.TimeoutError:
                notification={"type":"heartbeat"}
            await app.state.db.member(user_id)
            await ws.send_json(notification)
        await ws.close(code=1000)
    except (WebSocketDisconnect,RuntimeError):
        pass
    except Exception:
        with contextlib.suppress(RuntimeError):
            await ws.close(code=1008)
    finally:
        hub.queues.discard(queue)

# Machine-to-machine access for trusted producers / future Phase 2.
# This key never belongs in index.html or a user's browser.
async def producer(credentials: HTTPAuthorizationCredentials | None = Depends(auth)):
    expected = os.environ.get("INGEST_API_KEY", "")
    if len(expected)<32:
        raise HTTPException(503,"Producer API is not configured")
    supplied=credentials.credentials if credentials else ""
    if not credentials or credentials.scheme.lower()!="bearer" or not hmac.compare_digest(supplied,expected):
        raise HTTPException(401,"Invalid producer credentials")
    return True

class EventInput(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)
    event_id: str=Field(min_length=1,max_length=160)
    mission_id: str=Field(min_length=1,max_length=160)
    track_id: int | None=None
    object: str=Field(min_length=1,max_length=100)
    person_visible: bool | None=None
    confidence: float | None=Field(default=None,ge=0,le=1)
    latitude: float | None=Field(default=None,ge=-90,le=90)
    longitude: float | None=Field(default=None,ge=-180,le=180)
    location_validity: Literal['Valid','Approximate','Unavailable']='Unavailable'
    timestamp: AwareDatetime
    image_path: str | None=Field(default=None,max_length=512)
    status: Literal['pending']='pending'
    drone_id: str | None=Field(default=None,max_length=160)
    drone_latitude: float | None=Field(default=None,ge=-90,le=90)
    drone_longitude: float | None=Field(default=None,ge=-180,le=180)
    target_accuracy_m: float | None=Field(default=None,ge=0)
    location_source: Literal['unknown','target_gps','image_projection','manual']='unknown'
    bbox: tuple[float,float,float,float] | None=None
    model_version: str | None=Field(default=None,max_length=100)
    delivery_status: str='delivered'

    @field_validator('event_id','mission_id','object')
    @classmethod
    def nonblank(cls,value):
        if not value.strip(): raise ValueError('Must not be blank')
        return value

    @field_validator('bbox')
    @classmethod
    def normalized_bbox(cls,value):
        if value and not (0<=value[0]<value[2]<=1 and 0<=value[1]<value[3]<=1):
            raise ValueError('bbox must be normalized [xmin,ymin,xmax,ymax]')
        return value

    @field_validator('image_path')
    @classmethod
    def object_key(cls,value):
        if value and (value.startswith('/') or '..' in value.split('/') or '\\' in value or ':' in value):
            raise ValueError('Use a private Storage object key, not a URL or local path')
        return value

    @model_validator(mode='after')
    def location(self):
        if (self.drone_latitude is None) != (self.drone_longitude is None):
            raise ValueError('Drone coordinates require a pair')
        if self.location_validity!='Unavailable' and (self.latitude is None or self.longitude is None):
            raise ValueError('Valid/Approximate location requires both coordinates')
        return self

class TelemetryInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    drone_id: str=Field(min_length=1,max_length=160)
    mission_id: str | None=Field(default=None,max_length=160)
    flight_mode: str | None=Field(default=None,max_length=100)
    mission_state: str | None=Field(default=None,max_length=100)
    battery_percent: float | None=Field(default=None,ge=0,le=100)
    altitude_m: float | None=None
    speed_mps: float | None=Field(default=None,ge=0)
    latitude: float | None=Field(default=None,ge=-90,le=90)
    longitude: float | None=Field(default=None,ge=-180,le=180)
    link_quality_percent: float | None=Field(default=None,ge=0,le=100)
    updated_at: AwareDatetime
    latest_image_path: str | None=Field(default=None,max_length=512)
    stream_url: str | None=Field(default=None,max_length=2048)

    heading_deg: float | None=Field(default=None,ge=0,lt=360)
    distance_to_home_m: float | None=Field(default=None,ge=0)
    distance_travelled_m: float | None=Field(default=None,ge=0)
    home_latitude: float | None=Field(default=None,ge=-90,le=90)
    home_longitude: float | None=Field(default=None,ge=-180,le=180)
    gps_satellites: int | None=Field(default=None,ge=0,le=255)
    gps_hdop: float | None=Field(default=None,ge=0)
    gps_fix_type: Literal['no_fix','2d','3d','dgps','rtk_float','rtk_fixed'] | None=None
    battery_voltage_v: float | None=Field(default=None,ge=0)
    vertical_speed_mps: float | None=None
    armed: bool | None=None
    flight_time_s: int | None=Field(default=None,ge=0)
    connection_type: str | None=Field(default=None,max_length=60)
    signal_dbm: float | None=Field(default=None,le=0)

    @model_validator(mode='after')
    def coordinate_pairs(self):
        if (self.latitude is None)!=(self.longitude is None) or (self.home_latitude is None)!=(self.home_longitude is None):
            raise ValueError('Coordinates require latitude and longitude together')
        return self

    @field_validator('updated_at')
    @classmethod
    def not_future(cls,value):
        if value>datetime.now(timezone.utc)+timedelta(seconds=5): raise ValueError('Telemetry timestamp is in the future')
        return value

    @field_validator('stream_url')
    @classmethod
    def https_only(cls,value):
        if value and not value.startswith('https://'): raise ValueError('Video URL must use HTTPS')
        return value

async def persist_event(event, image_bytes=None):
    payload=event.model_dump(mode='json')
    if image_bytes:
        if len(image_bytes)>MAX_IMAGE_BYTES: raise HTTPException(413,'Image exceeds 10 MiB')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(image_bytes)) as img:
                    image_format=img.format
                    img.verify()
                if image_format not in ('JPEG','PNG','WEBP'): raise ValueError('Unsupported image format')
        except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
            raise HTTPException(422,'Image must be a valid JPEG, PNG or WebP within pixel limits')
        mime,extension={'JPEG':('image/jpeg','jpg'),'PNG':('image/png','png'),'WEBP':('image/webp','webp')}[image_format]
        digest=hashlib.sha256(image_bytes).hexdigest()
        identifier=hashlib.sha256(event.event_id.encode()).hexdigest()[:24]
        path=f'events/{identifier}/{digest}.{extension}'
        headers={'apikey':app.state.db.secret,'Content-Type':mime,'x-upsert':'false'}
        if app.state.db.secret.startswith('eyJ'):headers['Authorization']='Bearer '+app.state.db.secret
        try:
            response=await app.state.db.client.post(app.state.db.url+'/storage/v1/object/event-images/'+path,headers=headers,content=image_bytes)
        except httpx.RequestError:
            raise HTTPException(503,'Image upload could not be confirmed; retry the same event')
        if response.status_code>=400:
            try: body=response.json()
            except ValueError: body={}
            # Content-addressed paths: an existing object is the same upload.
            if not (response.status_code in (400,409) and (str(body.get('statusCode'))=='409' or body.get('error') in ('Duplicate','Asset Already Exists'))):
                raise HTTPException(503,'Image upload failed')
        payload['image_path']=path
    fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    result=await app.state.db.rpc('ingest_event',{'p_event':payload,'p_fingerprint':fingerprint})
    if result.get('code')==201:await hub.publish('event.created')
    if result.get('code') in (200,201):
        result.update(received=True,event_id=event.event_id)
    return rpc_response(result)

@app.post('/api/v1/events',status_code=201)
@app.post('/events',status_code=201,include_in_schema=False)
async def ingest_json(payload:EventInput,allowed=Depends(producer)):
    return await persist_event(payload)

@app.post('/api/v1/events/upload',status_code=201)
async def ingest_with_image(event_json:str=Form(...,max_length=65536),image:UploadFile=File(...),allowed=Depends(producer)):
    try:
        event=EventInput.model_validate_json(event_json)
    except ValidationError:
        raise HTTPException(422,'Invalid event JSON; check the documented schema')
    content=await image.read(MAX_IMAGE_BYTES+1)
    await image.close()
    if not content:raise HTTPException(422,'Image is empty')
    return await persist_event(event,content)

@app.get('/api/v1/events')
async def list_events(limit:int=Query(25,ge=1,le=100),offset:int=Query(0,ge=0),status:Literal['pending','accepted','rejected','timeout']|None=None,user=Depends(member)):
    params={'select':'*','order':'timestamp.desc,event_id.asc','limit':str(limit),'offset':str(offset)}
    if status:params['status']='eq.'+status
    return {'items':await app.state.db.request('rest/v1/events',params=params)}

@app.get('/api/v1/events/{event_id}')
async def event_detail(event_id:str,user=Depends(member)):
    rows=await app.state.db.request('rest/v1/events',params={'event_id':'eq.'+event_id,'limit':'1'})
    if not rows:raise HTTPException(404,'Event not found')
    return rows[0]

@app.get('/api/v1/events/{event_id}/image')
async def event_image(event_id:str,user=Depends(member)):
    event=await event_detail(event_id,user)
    if not event.get('image_path'):raise HTTPException(404,'No image recorded')
    signed=await app.state.db.request('storage/v1/object/sign/event-images/'+quote(event['image_path'],safe='/'),'POST',{'expiresIn':60})
    return {'signed_url':app.state.db.url+'/storage/v1'+(signed.get('signedURL') or signed.get('signedUrl')),'expires_in':60}

@app.post('/api/v1/ingest/telemetry')
async def ingest_telemetry(payload:TelemetryInput,allowed=Depends(producer)):
    result=await app.state.db.rpc('upsert_telemetry',{'p_state':payload.model_dump(mode='json')})
    if result.get('code')==200:await hub.publish('telemetry.updated')
    return rpc_response(result)

class NewUser(BaseModel):
    model_config=ConfigDict(extra='forbid')
    email:str=Field(min_length=3,max_length=254)
    display_name:str=Field(min_length=1,max_length=120)
    password:str=Field(min_length=12,max_length=128)
    role:Literal['admin','operator']='admin'
    login_id:str=Field(min_length=3,max_length=64,pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$')
    @field_validator('email')
    @classmethod
    def email_format(cls,value):
        value=value.strip()
        if '@' not in value or ' ' in value or '.' not in value.rsplit('@',1)[-1]:raise ValueError('Invalid email')
        return value

class NewRole(BaseModel):
    model_config=ConfigDict(extra='forbid')
    role:Literal['admin','operator']

@app.post('/api/v1/admin/users',status_code=201)
async def create_user(payload:NewUser,user=Depends(admin)):
    payload.login_id=payload.login_id.lower()
    existing=await app.state.db.request('rest/v1/login_identities',params={'login_id':'eq.'+payload.login_id,'select':'user_id'})
    if existing:raise HTTPException(409,'Login ID is already assigned')
    # Provisioned accounts only. Password is sent to Supabase Auth; never logged/stored here.
    created=await app.state.db.request('auth/v1/admin/users','POST',{'email':payload.email,'password':payload.password,'email_confirm':True})
    uid=created.get('id') or created.get('user',{}).get('id')
    if not uid:raise HTTPException(503,'Account creation returned no identity')
    try:
        await app.state.db.request('rest/v1/profiles','POST',{'id':uid,'display_name':payload.display_name,'role':payload.role,'active':True})
        await app.state.db.request('rest/v1/login_identities','POST',{'login_id':payload.login_id,'user_id':uid,'email':payload.email})
    except Exception:
        # No profile means no workspace access; attempt compensation without hiding failure.
        try:await app.state.db.request('auth/v1/admin/users/'+uid,'DELETE')
        except Exception:log.error('Profile provisioning failed; orphan Auth user requires administrator cleanup: %s',uid)
        raise
    await app.state.db.request('rest/v1/audit_log','POST',{'actor_id':user['id'],'action':'user.created','details':{'user_id':uid,'role':payload.role}})
    await hub.publish('access.updated')
    return {'user':{'id':uid,'display_name':payload.display_name,'role':payload.role,'active':True}}

@app.patch('/api/v1/admin/users/{user_id}/role')
async def change_role(user_id:UUID,payload:NewRole,user=Depends(admin)):
    result=await app.state.db.rpc('set_member_role',{'p_actor_id':user['id'],'p_user_id':str(user_id),'p_role':payload.role})
    await hub.publish('access.updated')
    return rpc_response(result)

class Capability(BaseModel):
    model_config=ConfigDict(extra='forbid')
    code:str=Field(min_length=1,max_length=100)
    label:str=Field(min_length=1,max_length=120)
    description:str=Field(default='',max_length=500)
    enabled:bool=False
    reason:str=Field(default='',max_length=500)

@app.put('/api/v1/ingest/capabilities')
async def capabilities_update(payload:list[Capability],allowed=Depends(producer)):
    if len(payload)>20:raise HTTPException(422,'Maximum 20 capabilities')
    if payload:
        await app.state.db.request('rest/v1/command_capabilities','POST',[x.model_dump() for x in payload],params={'on_conflict':'code'},prefer='resolution=merge-duplicates')
    await hub.publish('telemetry.updated')
    return {'updated':len(payload)}

@app.post('/api/v1/ingest/commands/claim')
async def claim_commands(drone_id:str=Query(min_length=1,max_length=160),limit:int=Query(10,ge=1,le=20),allowed=Depends(producer)):
    rows=await app.state.db.rpc('claim_commands',{'p_drone_id':drone_id,'p_limit':limit})
    if rows:await hub.publish('command.updated')
    return {'items':rows}

class Acknowledgement(BaseModel):
    model_config=ConfigDict(extra='forbid')
    status:Literal['sent','acknowledged','rejected','failed']
    acknowledgement:str=Field(min_length=1,max_length=1000)

@app.post('/api/v1/ingest/commands/{command_id}/ack')
async def acknowledge(command_id:UUID,payload:Acknowledgement,allowed=Depends(producer)):
    result=await app.state.db.rpc('acknowledge_command',{'p_command_id':str(command_id),'p_status':payload.status,'p_ack':payload.acknowledgement})
    await hub.publish('command.updated')
    return rpc_response(result)

@app.post('/api/v1/admin/events/upload',status_code=201)
async def admin_test_event(event_json:str=Form(...,max_length=65536),image:UploadFile|None=File(default=None),user=Depends(admin)):
    try:event=EventInput.model_validate_json(event_json)
    except ValidationError:raise HTTPException(422,'Invalid event JSON')
    content=None
    if image:
        content=await image.read(MAX_IMAGE_BYTES+1)
        await image.close()
        if not content:raise HTTPException(422,'Image is empty')
    result=await persist_event(event,content)
    await app.state.db.request('rest/v1/audit_log','POST',{'actor_id':user['id'],'action':'event.test_submitted','details':{'event_id':event.event_id}})
    return result


class LoginInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    login_id: str=Field(min_length=3,max_length=64,pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$')
    password: str=Field(min_length=1,max_length=128)

@app.middleware('http')
async def no_store_private_responses(request: Request, call_next):
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='DENY'
    if os.environ.get('APP_ENV', 'production')=='production':
        response.headers['Strict-Transport-Security']='max-age=31536000'
    return response

@app.post('/api/v1/auth/login')
async def login(payload:LoginInput, request:Request):
    public_key=os.environ.get('SUPABASE_PUBLISHABLE_KEY','')
    if not public_key.startswith('sb_publishable_'):
        raise HTTPException(503,'Authentication service is not configured')
    login_id=payload.login_id.lower()
    # Persisted limiter shared across restarts. Trust only the address resolved by the server,
    # never a client-provided X-Forwarded-For header. Configure trusted proxies at deployment.
    ip=request.client.host if request.client else 'unknown'
    for raw,limit,seconds in [('ip:'+ip,20,60),('id:'+login_id,10,300)]:
        key=hashlib.sha256(raw.encode()).hexdigest()
        allowed=await app.state.db.rpc('consume_login_attempt',{'p_key':key,'p_limit':limit,'p_seconds':seconds})
        if allowed is not True:raise HTTPException(429,'Too many attempts; try again later')
    rows=await app.state.db.request('rest/v1/login_identities',params={'login_id':'eq.'+login_id,'select':'user_id,email','limit':'1'})
    identity=rows[0] if rows else None
    email=identity['email'] if identity else secrets.token_hex(16)+'@invalid.local'
    try:
        response=await app.state.db.client.post(app.state.db.url+'/auth/v1/token?grant_type=password',
            headers={'apikey':public_key,'Content-Type':'application/json'},
            json={'email':email,'password':payload.password})
    except httpx.RequestError:
        raise HTTPException(503,'Authentication service is unavailable')
    if response.status_code==429:raise HTTPException(429,'Too many attempts; try again later')
    if response.status_code>=500:raise HTTPException(503,'Authentication service is unavailable')
    if response.status_code!=200 or not identity:
        raise HTTPException(401,'Invalid ID or password')
    data=response.json()
    if data.get('user',{}).get('id')!=identity['user_id']:
        raise HTTPException(401,'Invalid ID or password')
    try:await app.state.db.member(identity['user_id'])
    except HTTPException:raise HTTPException(401,'Invalid ID or password')
    # Password-only session is AAL1: every operational API/RLS gate requires AAL2.
    return {k:data[k] for k in ('access_token','refresh_token','expires_in','token_type','user') if k in data}

@app.get('/api/v1/telemetry')
async def telemetry(user=Depends(member)):
    return {'items':await app.state.db.request('rest/v1/drone_state',params={'select':'*','order':'updated_at.desc','limit':'20'})}

@app.get('/api/v1/telemetry/{drone_id}/history')
async def telemetry_history(drone_id:str,mission_id:str|None=Query(default=None,max_length=160),user=Depends(member)):
    params={'drone_id':'eq.'+drone_id,'select':'*','order':'updated_at.desc','limit':'600'}
    if mission_id is not None:params['mission_id']='eq.'+mission_id
    return {'items':await app.state.db.request('rest/v1/telemetry_history',params=params)}


# Password and TOTP stay with Supabase Auth; the browser only talks to FastAPI.
async def auth_exchange(path, method='POST', body=None, token=None):
    key = os.environ.get('SUPABASE_PUBLISHABLE_KEY', '')
    if not key.startswith('sb_publishable_'):
        raise HTTPException(503, 'Authentication service is not configured')
    headers = {'apikey': key, 'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        r = await app.state.db.client.request(method, app.state.db.url + '/auth/v1/' + path,
            headers=headers, json=body)
    except httpx.RequestError:
        raise HTTPException(503, 'Authentication service is unavailable')
    if r.status_code >= 400:
        code = r.status_code if r.status_code in (400,401,403,404,422,429) else 503
        raise HTTPException(code, 'Authentication request could not be completed')
    return r.json() if r.content else {}

async def pre_mfa(credentials: HTTPAuthorizationCredentials | None = Depends(auth)):
    if not credentials:
        raise HTTPException(401, 'A bearer session is required')
    user = await app.state.db.request('auth/v1/user', token=credentials.credentials)
    if not user or not user.get('id'):
        raise HTTPException(401, 'Invalid session')
    await app.state.db.member(user['id'])
    key = hashlib.sha256(('mfa:' + user['id']).encode()).hexdigest()
    if await app.state.db.rpc('consume_login_attempt', {'p_key':key,'p_limit':30,'p_seconds':60}) is not True:
        raise HTTPException(429, 'Too many authentication attempts')
    return credentials.credentials

class RefreshInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    refresh_token: str=Field(min_length=1,max_length=8192)

class FactorInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    factor_type: Literal['totp']='totp'
    friendly_name: str=Field(default='Maritime Authenticator',min_length=1,max_length=100)
    issuer: Literal['Maritime Operations']='Maritime Operations'

class VerifyInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    challenge_id: UUID
    code: str=Field(pattern=r'^\d{6}$')

@app.post('/api/v1/auth/refresh')
async def refresh_auth(payload:RefreshInput, request:Request):
    ip=request.client.host if request.client else 'unknown'
    key=hashlib.sha256(('refresh:'+ip).encode()).hexdigest()
    if await app.state.db.rpc('consume_login_attempt', {'p_key':key,'p_limit':60,'p_seconds':60}) is not True:
        raise HTTPException(429, 'Too many refresh attempts')
    return await auth_exchange('token?grant_type=refresh_token', body=payload.model_dump())

@app.get('/api/v1/auth/user')
async def auth_user(token=Depends(pre_mfa)):
    return await auth_exchange('user', 'GET', token=token)

@app.post('/api/v1/auth/factors')
async def enroll_factor(payload:FactorInput, token=Depends(pre_mfa)):
    return await auth_exchange('factors', body=payload.model_dump(), token=token)

@app.delete('/api/v1/auth/factors/{factor_id}')
async def delete_incomplete_factor(factor_id:UUID, token=Depends(pre_mfa)):
    user=await auth_exchange('user', 'GET', token=token)
    factor=next((f for f in user.get('factors',[]) if f['id']==str(factor_id)),None)
    if not factor or factor.get('status')!='unverified':
        raise HTTPException(403, 'Only incomplete enrollment can be removed here')
    return await auth_exchange('factors/'+str(factor_id), 'DELETE', token=token)

@app.post('/api/v1/auth/factors/{factor_id}/challenge')
async def challenge_factor(factor_id:UUID, token=Depends(pre_mfa)):
    return await auth_exchange('factors/'+str(factor_id)+'/challenge', body={}, token=token)

@app.post('/api/v1/auth/factors/{factor_id}/verify')
async def verify_factor(factor_id:UUID, payload:VerifyInput, token=Depends(pre_mfa)):
    return await auth_exchange('factors/'+str(factor_id)+'/verify', body=payload.model_dump(mode='json'), token=token)

@app.post('/api/v1/auth/logout')
async def logout_auth(credentials: HTTPAuthorizationCredentials | None=Depends(auth)):
    if not credentials: raise HTTPException(401, 'A bearer session is required')
    return await auth_exchange('logout?scope=local', token=credentials.credentials)

@app.get('/api/v1/summary')
async def summary(user=Depends(member),credentials:HTTPAuthorizationCredentials=Depends(auth)):
    return await app.state.db.request('rest/v1/rpc/workspace_summary','POST',{},token=credentials.credentials)

@app.get('/api/v1/archive')
async def archive(event_id:str|None=Query(None,max_length=160),
    status:Literal['pending','accepted','rejected','timeout']|None=None,
    object:str|None=Query(None,max_length=100),from_date:date|None=None,to_date:date|None=None,
    offset:int=Query(0,ge=0,le=1000000),limit:int=Query(20,ge=1,le=100),user=Depends(member)):
    if from_date and to_date and from_date>to_date:
        raise HTTPException(422,'Invalid date range')
    params=[('select','*'),('order','timestamp.desc,event_id.asc'),('limit',str(limit)),('offset',str(offset))]
    for key,value in [('event_id',event_id),('status',status),('object',object)]:
        if value is not None: params.append((key,'eq.'+value))
    if from_date:params.append(('timestamp','gte.'+from_date.isoformat()+'T00:00:00Z'))
    if to_date:
        if to_date==date.max:raise HTTPException(422,'End date out of range')
        params.append(('timestamp','lt.'+(to_date+timedelta(days=1)).isoformat()+'T00:00:00Z'))
    return await app.state.db.request('rest/v1/events',params=params,prefer='count=exact',include_count=True)

@app.get('/',response_class=HTMLResponse,include_in_schema=False)
@app.get('/index.html',response_class=HTMLResponse,include_in_schema=False)
async def website():
    html=(Path(__file__).resolve().parents[1]/'index.html').read_text(encoding='utf-8')
    if os.environ.get('APP_ENV')=='development':
        html=html.replace('allowLocalApi: false','allowLocalApi: true')
    return HTMLResponse(html)
