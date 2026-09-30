"""Production boundaries with an HTTP Supabase stub, not a hosted integration test."""
import asyncio
import importlib.util
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient

spec=importlib.util.spec_from_file_location('production',Path(__file__).resolve().parents[1]/'server/app.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
UID='11111111-1111-1111-1111-111111111111'
FID='22222222-2222-2222-2222-222222222222'
AUTH={'Authorization':'Bearer verified-token'}

@pytest.fixture
def api(monkeypatch):
    for key,value in {'APP_ENV':'production','SUPABASE_URL':'https://unit.supabase.co','SUPABASE_SECRET_KEY':'sb_secret_test','SUPABASE_PUBLISHABLE_KEY':'sb_publishable_test','INGEST_API_KEY':'x'*32,'ALLOWED_ORIGINS':'https://operations.example.com'}.items():monkeypatch.setenv(key,value)
    calls=[];state={'aal':'aal2','verified':False,'error':None}
    def handle(req):
        calls.append(req)
        if state['error']:return httpx.Response(state['error'],json={'sensitive':'must-not-leak'})
        p=req.url.path
        if p.endswith('/auth/v1/user'):return httpx.Response(200,json={'id':UID,'factors':[{'id':FID,'status':'verified' if state['verified'] else 'unverified'}]})
        if p.endswith('current_session_security'):return httpx.Response(200,json={'user_id':UID,'aal':state['aal']})
        if p.endswith('consume_login_attempt'):return httpx.Response(200,json=True)
        if p.endswith('/profiles'):return httpx.Response(200,json=[{'id':UID,'role':'admin','active':True}])
        if p.endswith('/events'):return httpx.Response(200,json=[{'event_id':'E'}],headers={'content-range':'20-20/21'})
        if p.endswith('/logout'):return httpx.Response(204)
        return httpx.Response(200,json={'ok':True})
    transport=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    g.app.state.db=g.SupabaseGateway(transport,'https://unit.supabase.co','sb_secret_test')
    c=TestClient(g.app);yield c,calls,state;c.close();asyncio.run(transport.aclose())

def test_valid_environment(api):g.validate_environment()

@pytest.mark.parametrize('key,value',[
    ('APP_ENV','debug'),('INGEST_API_KEY','short'),('SUPABASE_SECRET_KEY',''),
    ('SUPABASE_PUBLISHABLE_KEY','secret'),('SUPABASE_URL','http://unit.supabase.co'),
    ('ALLOWED_ORIGINS','*'),('ALLOWED_ORIGINS','http://localhost:8000'),
    ('ALLOWED_ORIGINS','https://localhost:8000'),('ALLOWED_ORIGINS','https://example.com/path'),
    ('ALLOWED_ORIGINS','https://u:p@example.com'),('ALLOWED_ORIGINS','https://example.com?key=secret')])
def test_invalid_environment_fails_before_start(api,monkeypatch,key,value):
    monkeypatch.setenv(key,value)
    with pytest.raises(RuntimeError):g.validate_environment()

def test_development_allows_only_loopback_http(api,monkeypatch):
    monkeypatch.setenv('APP_ENV','development');monkeypatch.setenv('ALLOWED_ORIGINS','http://127.0.0.1:8000')
    g.validate_environment()
    monkeypatch.setenv('ALLOWED_ORIGINS','http://remote.example.com')
    with pytest.raises(RuntimeError):g.validate_environment()

def test_served_frontend_has_no_api_key_and_dev_is_explicit(api,monkeypatch):
    c,_,_=api;r=c.get('/')
    assert r.status_code==200 and 'text/html' in r.headers['content-type']
    assert 'sb_secret_test' not in r.text and 'supabasePublishableKey' not in r.text
    assert 'allowLocalApi: false' in r.text
    assert r.headers['x-frame-options']=='DENY'
    monkeypatch.setenv('APP_ENV','development')
    assert 'allowLocalApi: true' in c.get('/').text
    assert c.get('/server/app.py').status_code==404

@pytest.mark.parametrize('path',['/api/v1/auth/user','/api/v1/archive','/api/v1/summary'])
def test_new_read_routes_require_session(api,path):assert api[0].get(path).status_code==401

@pytest.mark.parametrize('path',['/api/v1/archive','/api/v1/summary'])
def test_new_data_routes_require_aal2(api,path):
    api[2]['aal']='aal1';assert api[0].get(path,headers=AUTH).status_code==403

def test_mfa_proxy_uses_public_key_and_user_token_only(api):
    c,calls,_=api;r=c.post(f'/api/v1/auth/factors/{FID}/challenge',json={},headers=AUTH)
    assert r.status_code==200
    req=calls[-1]
    assert req.headers['apikey']=='sb_publishable_test' and req.headers['authorization']=='Bearer verified-token'
    assert 'sb_secret_test' not in r.text

def test_mfa_verified_factor_cannot_be_removed(api):
    c,calls,state=api;state['verified']=True
    assert c.delete(f'/api/v1/auth/factors/{FID}',headers=AUTH).status_code==403
    assert not any(r.method=='DELETE' for r in calls)

def test_mfa_incomplete_factor_can_be_removed(api):
    assert api[0].delete(f'/api/v1/auth/factors/{FID}',headers=AUTH).status_code==200

def test_auth_proxy_is_not_general_admin_proxy(api):
    assert api[0].post('/api/v1/auth/admin/users',headers=AUTH,json={}).status_code==404
    assert api[0].post('/api/v1/auth/factors',headers=AUTH,json={'factor_type':'phone'}).status_code==422

def test_refresh_uses_fixed_grant_and_does_not_accept_password(api):
    c,calls,_=api
    assert c.post('/api/v1/auth/refresh',json={'refresh_token':'test-refresh'}).status_code==200
    assert calls[-1].url.params['grant_type']=='refresh_token'
    assert c.post('/api/v1/auth/refresh',json={'refresh_token':'test-refresh','password':'p'}).status_code==422

def test_auth_error_sanitized(api):
    api[2]['error']=422
    # Call transport helper directly so upstream error isn't intercepted by identity lookup.
    with pytest.raises(g.HTTPException) as e:asyncio.run(g.auth_exchange('factors',body={}))
    assert e.value.status_code==422 and 'sensitive' not in e.value.detail

def test_logout_accepts_empty_success_response(api):
    assert api[0].post('/api/v1/auth/logout',headers=AUTH).json()=={}

def test_archive_filters_count_and_inclusive_utc_end_date(api):
    c,calls,_=api;r=c.get('/api/v1/archive',params={'event_id':'E','status':'accepted','from_date':'2026-01-01','to_date':'2026-01-02','offset':20},headers=AUTH)
    assert r.status_code==200 and r.json()=={'items':[{'event_id':'E'}],'total':21}
    req=calls[-1]
    assert req.url.params.get_list('timestamp')==['gte.2026-01-01T00:00:00Z','lt.2026-01-03T00:00:00Z']
    assert req.headers['prefer']=='count=exact'
    assert c.get('/api/v1/archive?from_date=2026-02-01&to_date=2026-01-01',headers=AUTH).status_code==422
    assert c.get('/api/v1/archive?to_date=9999-12-31',headers=AUTH).status_code==422

def test_summary_forwards_verified_user_for_rls(api):
    c,calls,_=api;assert c.get('/api/v1/summary',headers=AUTH).status_code==200
    assert calls[-1].headers['authorization']=='Bearer verified-token'
