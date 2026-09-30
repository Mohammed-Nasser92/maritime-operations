"""Gateway route tests with a fake data service; no claim of live Supabase connectivity."""
import importlib.util
import pathlib
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

path=pathlib.Path(__file__).resolve().parents[1]/'server'/'app.py'
spec=importlib.util.spec_from_file_location('gateway',path)
g=importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

class FakeDB:
    def __init__(self):
        self.calls=[]
        self.role='operator'
        self.result={'code':200,'event':{'event_id':'EVT-1','status':'accepted'}}
    async def request(self,path,method='GET',body=None,token=None,params=None):
        self.calls.append((path,method,body,token,params))
        if path=='rest/v1/rpc/current_session_security':return {'aal':'aal2','user_id':'11111111-1111-1111-1111-111111111111'}
        if path=='auth/v1/user':
            if token!='valid': raise HTTPException(401,'Invalid token')
            return {'id':'11111111-1111-1111-1111-111111111111'}
        return []
    async def member(self,user_id):
        return {'id':user_id,'active':True,'role':self.role}
    async def rpc(self,name,body):
        self.calls.append((name,body))
        return self.result

# Construct the non-context-managed client to bypass production lifespan.
@pytest.fixture
def api():
    g.app.state.db=FakeDB()
    c=TestClient(g.app)
    yield c
    c.close()

AUTH={'Authorization':'Bearer valid'}

def test_no_auth_is_denied(api):
    assert api.get('/api/v1/me').status_code==401

def test_invalid_token_denied(api):
    assert api.get('/api/v1/me',headers={'Authorization':'Bearer invalid'}).status_code==401

def test_operator_admin_denied(api):
    assert api.get('/api/v1/admin/users',headers=AUTH).status_code==403

def test_admin_allowed(api):
    g.app.state.db.role='admin'
    assert api.get('/api/v1/admin/users',headers=AUTH).status_code==200

def test_decision_actor_comes_from_verified_token(api):
    r=api.post('/api/v1/events/EVT-1/decision',headers=AUTH,json={'decision':'accepted','expected_version':0})
    assert r.status_code==200
    name,payload=g.app.state.db.calls[-1]
    assert name=='review_event'
    assert payload['p_actor_id']=='11111111-1111-1111-1111-111111111111'

def test_client_actor_spoof_is_rejected(api):
    r=api.post('/api/v1/events/EVT-1/decision',headers=AUTH,json={'decision':'accepted','expected_version':0,'actor_id':'someone'})
    assert r.status_code==422

def test_browser_cannot_set_timeout(api):
    r=api.post('/api/v1/events/EVT-1/decision',headers=AUTH,json={'decision':'timeout','expected_version':0})
    assert r.status_code==422

def test_rpc_conflict_propagates(api):
    g.app.state.db.result={'code':409,'detail':'Window expired'}
    r=api.post('/api/v1/events/EVT-1/decision',headers=AUTH,json={'decision':'accepted','expected_version':0})
    assert r.status_code==409

def test_commands_require_uuid_idempotency_key(api):
    body={'command':'hold','drone_id':'UAV-1','mission_id':'M','telemetry_timestamp':'2026-09-28T03:00:00Z','reason':'Testing'}
    assert api.post('/api/v1/commands',headers=AUTH,json=body).status_code==422
    g.app.state.db.result={'code':202,'command':{'status':'queued'}}
    h={**AUTH,'Idempotency-Key':'22222222-2222-2222-2222-222222222222'}
    assert api.post('/api/v1/commands',headers=h,json=body).status_code==202

def test_operator_command_history_is_scoped(api):
    assert api.get('/api/v1/commands',headers=AUTH).status_code==200
    assert g.app.state.db.calls[-1][-1]['actor_id']=='eq.11111111-1111-1111-1111-111111111111'

def test_negative_limit_is_rejected(api):
    assert api.get('/api/v1/commands?limit=-1',headers=AUTH).status_code==422

def test_disabled_membership_denied(api):
    async def disabled(user_id):raise HTTPException(403,'Disabled')
    g.app.state.db.member=disabled
    assert api.get('/api/v1/me',headers=AUTH).status_code==403
