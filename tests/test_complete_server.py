"""Independent backend tests using mocked Supabase transport."""
import asyncio
import importlib.util
import io
import json
import os
from pathlib import Path
from datetime import datetime,timezone
import httpx
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from fastapi import HTTPException

spec=importlib.util.spec_from_file_location('complete_server',Path(__file__).resolve().parents[1]/'server/app.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
ID='11111111-1111-1111-1111-111111111111'
KEY='x'*40
class UploadClient:
    def __init__(self):self.uploads=[]
    async def post(self,url,headers,content):
        self.uploads.append((url,headers,content))
        return httpx.Response(200,json={'Key':'test'})
class DB:
    def __init__(self):
        self.role='admin';self.calls=[];self.client=UploadClient();self.secret='sb_secret_private';self.url='https://test.supabase.co';self.profile_fail=False
    async def member(self,user_id):return {'id':user_id,'role':self.role,'active':True}
    async def request(self,path,method='GET',body=None,token=None,params=None,prefer=None):
        self.calls.append((path,method,body,params))
        if path=='rest/v1/rpc/current_session_security':return {'aal':'aal2','user_id':'11111111-1111-1111-1111-111111111111'}
        if path=='auth/v1/user':
            if token!='user-token':raise HTTPException(401,'Invalid')
            return {'id':ID}
        if path=='auth/v1/admin/users':return {'id':'22222222-2222-2222-2222-222222222222'}
        if path=='rest/v1/profiles' and self.profile_fail:raise HTTPException(503,'Profile failed')
        return []
    async def rpc(self,name,body):
        self.calls.append((name,'RPC',body,None))
        if name=='ingest_event':return {'code':201,'event':{**body['p_event'],'review_started_at':datetime.now(timezone.utc).isoformat()},'duplicate':False}
        if name=='upsert_telemetry':return {'code':200,'state':body['p_state']}
        return {'code':200}
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('INGEST_API_KEY',KEY)
    g.app.state.db=DB()
    c=TestClient(g.app)
    yield c
    c.close()
def event(**changes):
    value={'event_id':'EVT-TEST','mission_id':'MIS-TEST','track_id':1,'object':'floating_mine_candidate','person_visible':None,'confidence':.8,'latitude':None,'longitude':None,'location_validity':'Unavailable','timestamp':'2026-09-28T03:00:00Z','image_path':None,'status':'pending'}
    return {**value,**changes}
MACHINE={'Authorization':'Bearer '+KEY}
USER={'Authorization':'Bearer user-token'}

def test_ingestion_requires_machine_key(client):
    assert client.post('/api/v1/events',json=event()).status_code==401
    assert client.post('/api/v1/events',json=event(),headers=USER).status_code==401

def test_ingestion_preserves_candidate_and_unknown_person(client):
    r=client.post('/api/v1/events',json=event(),headers=MACHINE)
    assert r.status_code==201
    assert r.json()['received'] is True and r.json()['event_id']=='EVT-TEST'
    assert r.json()['event']['object']=='floating_mine_candidate'
    assert r.json()['event']['person_visible'] is None

def test_rejects_bad_coordinates_and_bbox(client):
    assert client.post('/api/v1/events',json=event(location_validity='Valid'),headers=MACHINE).status_code==422
    assert client.post('/api/v1/events',json=event(bbox=[.8,.1,.2,.7]),headers=MACHINE).status_code==422

def test_rejects_final_status_and_naive_timestamp(client):
    assert client.post('/api/v1/events',json=event(status='accepted'),headers=MACHINE).status_code==422
    assert client.post('/api/v1/events',json=event(timestamp='2026-09-28T03:00:00'),headers=MACHINE).status_code==422

def test_rejects_url_or_traversal_image_paths(client):
    for path in ['../secret','https://example.com/image.jpg','C:\\image.jpg']:
        assert client.post('/api/v1/events',json=event(image_path=path),headers=MACHINE).status_code==422

def test_upload_validates_actual_image_bytes_and_uses_private_storage(client):
    buf=io.BytesIO();Image.new('RGB',(4,4),(0,0,0)).save(buf,format='PNG');raw=buf.getvalue()
    r=client.post('/api/v1/events/upload',headers=MACHINE,data={'event_json':json.dumps(event())},files={'image':('x.png',raw,'image/png')})
    assert r.status_code==201
    assert r.json()['event']['image_path'].startswith('events/')
    url,headers,content=g.app.state.db.client.uploads[0]
    assert '/storage/v1/object/event-images/' in url
    assert headers['x-upsert']=='false'
    assert content==raw

def test_invalid_image_and_oversize_rejected(client):
    assert client.post('/api/v1/events/upload',headers=MACHINE,data={'event_json':json.dumps(event())},files={'image':('x.png',b'not an image','image/png')}).status_code==422
    assert client.post('/api/v1/events/upload',headers=MACHINE,data={'event_json':json.dumps(event())},files={'image':('x.png',b'x'*(g.MAX_IMAGE_BYTES+1),'image/png')}).status_code==413

def test_admin_can_create_test_event_without_producer_secret(client):
    r=client.post('/api/v1/admin/events/upload',headers=USER,data={'event_json':json.dumps(event())})
    assert r.status_code==201

def test_operator_cannot_create_accounts_or_test_events(client):
    g.app.state.db.role='operator'
    assert client.post('/api/v1/admin/users',headers=USER,json={'login_id':'test-admin','display_name':'A','email':'a@example.com','password':'long-password-test'}).status_code==403
    assert client.post('/api/v1/admin/events/upload',headers=USER,data={'event_json':json.dumps(event())}).status_code==403

def test_account_password_is_only_sent_to_auth(client):
    password='long-password-test'
    r=client.post('/api/v1/admin/users',headers=USER,json={'login_id':'test-admin','display_name':'A','email':'a@example.com','password':password})
    assert r.status_code==201
    for path,method,body,_ in g.app.state.db.calls:
        if path!='auth/v1/admin/users':assert password not in json.dumps(body)
    assert password not in r.text

def test_account_profile_failure_attempts_compensation(client):
    g.app.state.db.profile_fail=True
    r=client.post('/api/v1/admin/users',headers=USER,json={'login_id':'test-admin','display_name':'A','email':'a@example.com','password':'long-password-test'})
    assert r.status_code==503
    assert any(path.startswith('auth/v1/admin/users/') and method=='DELETE' for path,method,_,_ in g.app.state.db.calls)

def test_telemetry_rejects_out_of_range_and_accepts_valid(client):
    data={'drone_id':'UAV','updated_at':datetime.now(timezone.utc).isoformat(),'battery_percent':101}
    assert client.post('/api/v1/ingest/telemetry',headers=MACHINE,json=data).status_code==422
    data['battery_percent']=70
    assert client.post('/api/v1/ingest/telemetry',headers=MACHINE,json=data).status_code==200

def test_hub_sends_event_invalidation_and_coalesces_backlog():
    async def run():
        hub=g.NotificationHub();queue=asyncio.Queue(maxsize=1);hub.queues.add(queue)
        await hub.publish('event.created');await hub.publish('event.updated')
        assert queue.qsize()==1
        assert (await queue.get())['type']=='event.updated'
    asyncio.run(run())

def test_ws_ticket_stores_only_hash(client):
    r=client.post('/api/v1/ws-ticket',headers=USER)
    assert r.status_code==200
    ticket=r.json()['ticket']
    row=next(body for path,method,body,_ in g.app.state.db.calls if path=='rest/v1/ws_tickets')
    assert ticket not in json.dumps(row)
    assert len(row['ticket_hash'])==64

def test_websocket_rejects_untrusted_origin(client,monkeypatch):
    from starlette.websockets import WebSocketDisconnect
    monkeypatch.setenv('ALLOWED_ORIGINS','https://trusted.example')
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/v1/ws?ticket=abc',headers={'origin':'https://evil.example'}):pass

def test_websocket_accepts_one_use_ticket_and_sends_initial_refresh(client,monkeypatch):
    from starlette.websockets import WebSocketDisconnect
    monkeypatch.setenv('ALLOWED_ORIGINS','https://trusted.example')
    consumed=False
    original=g.app.state.db.rpc
    async def rpc(name,body):
        nonlocal consumed
        if name=='consume_ws_ticket':
            if consumed:return None
            consumed=True
            return ID
        return await original(name,body)
    g.app.state.db.rpc=rpc
    with client.websocket_connect('/api/v1/ws?ticket=valid',headers={'origin':'https://trusted.example'}) as ws:
        assert ws.receive_json()['type']=='event.updated'
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/v1/ws?ticket=valid',headers={'origin':'https://trusted.example'}):pass
