"""Owner-only provisioning for an existing account after migration 003; no role changes."""
import asyncio
import os
import re
from uuid import UUID
import httpx
if __package__:
    from .app import SupabaseGateway
else:
    from app import SupabaseGateway
async def main():
    uid=str(UUID(input('Existing Supabase Auth user UUID: ').strip()))
    login_id=input('New login ID: ').strip().lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{2,63}',login_id):raise ValueError('Invalid login ID')
    async with httpx.AsyncClient(timeout=15) as client:
        db=SupabaseGateway(client,os.environ['SUPABASE_URL'],os.environ['SUPABASE_SECRET_KEY'])
        user=await db.request('auth/v1/admin/users/'+uid)
        user=user.get('user',user)
        if user.get('id')!=uid or not user.get('email'):raise RuntimeError('Account email not available')
        await db.member(uid)
        existing=await db.request('rest/v1/login_identities',params={'login_id':'eq.'+login_id,'select':'user_id'})
        if existing:raise RuntimeError('Login ID is already in use')
        await db.request('rest/v1/login_identities','POST',{'login_id':login_id,'user_id':uid,'email':user['email']})
    print('Login ID assigned. Existing role and password were preserved. Authenticator is required.')
if __name__=='__main__':asyncio.run(main())
