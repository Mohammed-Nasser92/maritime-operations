"""Local API security boundaries. Supabase transport is mocked, not hosted validation."""
import asyncio
import importlib.util
import os
from pathlib import Path
from datetime import datetime,timezone
import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
spec=importlib.util.spec_from_file_location('live',Path(__file__).resolve().parents[1]/'server/app.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
ID='11111111-1111-1111-1111-111111111111'
class DB:
    def __init__(self):
        self.aal='aal1';self.uid=ID;self.active=True;self.known=True;self.allowed=True;self.calls=[];self.url='https://unit.supabase.co';self.secret='sb_secret_test'
        self.client=httpx.AsyncClient(transport=httpx.MockTransport(self.handle))
    def handle(self,req):
        import json
        self.calls.append((str(req.url),json.loads(req.content)))
        data=json.loads(req.content)
        if data['password']!='correct-password':return httpx.Response(400,json={'error':'Invalid login credentials'})
        return httpx.Response(200,json={'access_token':'password-session','refresh_token':'refresh','expires_in':3600,'user':{'id':ID}})
    async def request(self,path,method='GET',body=None,token=None,params=None,prefer=None):
        if path=='auth/v1/user':
            if token!='valid':raise HTTPException(401,'Invalid token')
            return {'id':ID}
        if path=='rest/v1/rpc/current_session_security':return {'aal':self.aal,'user_id':self.uid}
        if path=='rest/v1/login_identities':return [{'user_id':ID,'email':'admin@example.com'}] if self.known else []
        return []
    async def member(self,uid):
        if not self.active:raise HTTPException(403,'Disabled')
        return {'id':uid,'role':'admin','active':True,'display_name':'Admin'}
    async def rpc(self,name,body):return self.allowed if name=='consume_login_attempt' else {'code':200}
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY','sb_publishable_test')
    g.app.state.db=DB();c=TestClient(g.app);yield c;c.close();asyncio.run(g.app.state.db.client.aclose())
AUTH={'Authorization':'Bearer valid'}
@pytest.mark.parametrize('path',['/api/v1/me','/api/v1/events','/api/v1/admin/users','/api/v1/telemetry','/api/v1/telemetry/U/history'])
def test_aal1_admin_cannot_read_operational_data(client,path):assert client.get(path,headers=AUTH).status_code==403

def test_aal1_cannot_review_or_request_websocket(client):
    assert client.post('/api/v1/ws-ticket',headers=AUTH,json={}).status_code==403
    assert client.post('/api/v1/events/E/decision',headers=AUTH,json={'decision':'accepted','expected_version':0}).status_code==403

def test_validated_user_and_rpc_identity_must_match(client):
    g.app.state.db.aal='aal2';g.app.state.db.uid='22222222-2222-2222-2222-222222222222'
    assert client.get('/api/v1/me',headers=AUTH).status_code==403

def test_only_verified_active_aal2_allowed(client):
    g.app.state.db.aal='aal2';assert client.get('/api/v1/me',headers=AUTH).status_code==200
    g.app.state.db.active=False;assert client.get('/api/v1/me',headers=AUTH).status_code==403

def test_id_password_login_returns_pre_mfa_session_and_no_email_map(client):
    r=client.post('/api/v1/auth/login',json={'login_id':'MAR-001','password':'correct-password'})
    assert r.status_code==200 and r.json()['access_token']=='password-session'
    assert r.headers['cache-control']=='no-store'
    assert 'correct-password' not in r.text and 'admin@example.com' not in r.text
    assert client.get('/api/v1/events',headers={'Authorization':'Bearer password-session'}).status_code==401

def test_unknown_id_wrong_password_and_disabled_account_use_same_error(client):
    payload={'login_id':'MAR-001','password':'wrong'};wrong=client.post('/api/v1/auth/login',json=payload)
    g.app.state.db.known=False;payload['password']='correct-password';unknown=client.post('/api/v1/auth/login',json=payload)
    g.app.state.db.known=True;g.app.state.db.active=False;disabled=client.post('/api/v1/auth/login',json=payload)
    assert wrong.status_code==unknown.status_code==disabled.status_code==401
    assert wrong.json()==unknown.json()==disabled.json()

def test_rate_limit_precedes_password_exchange(client):
    g.app.state.db.allowed=False
    assert client.post('/api/v1/auth/login',json={'login_id':'MAR-001','password':'p'}).status_code==429
    assert g.app.state.db.calls==[]

def test_missing_public_key_fails_closed(client,monkeypatch):
    monkeypatch.delenv('SUPABASE_PUBLISHABLE_KEY')
    assert client.post('/api/v1/auth/login',json={'login_id':'MAR-001','password':'p'}).status_code==503

def test_client_cannot_supply_aal_or_role(client):
    assert client.post('/api/v1/auth/login',json={'login_id':'MAR-001','password':'p','aal':'aal2','role':'admin'}).status_code==422

@pytest.mark.parametrize('change',[{'latitude':17},{'gps_satellites':-1},{'heading_deg':360},{'gps_fix_type':'perfect'},{'distance_travelled_m':-1},{'home_longitude':42}])
def test_invalid_extended_telemetry_is_rejected(change):
    with pytest.raises(ValueError):g.TelemetryInput(drone_id='U',updated_at=datetime.now(timezone.utc),**change)

def test_zero_coordinates_and_missing_battery_are_valid():
    t=g.TelemetryInput(drone_id='U',latitude=0,longitude=0,heading_deg=0,gps_fix_type='3d',updated_at=datetime.now(timezone.utc))
    assert t.latitude==0 and t.heading_deg==0 and t.battery_percent is None
