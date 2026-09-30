"""Run once locally/server-side to provision the first administrator."""
import asyncio
import getpass
import os
import httpx
if __package__:
    from .app import SupabaseGateway, NewUser
else:
    from app import SupabaseGateway, NewUser

async def main():
    login_id=input('Login ID (letters/numbers/dot/dash/underscore): ').strip().lower()
    email=input('Administrator email: ').strip()
    name=input('Display name: ').strip()
    password=getpass.getpass('Initial password (12+ characters): ')
    payload=NewUser(login_id=login_id,email=email,display_name=name,password=password,role='admin')
    async with httpx.AsyncClient(timeout=15) as client:
        db=SupabaseGateway(client,os.environ['SUPABASE_URL'],os.environ['SUPABASE_SECRET_KEY'])
        existing=await db.request('rest/v1/login_identities',params={'login_id':'eq.'+payload.login_id,'select':'user_id'})
        if existing:raise RuntimeError('Login ID is already assigned')
        account=await db.request('auth/v1/admin/users','POST',{'email':payload.email,'password':payload.password,'email_confirm':True})
        uid=account.get('id') or account.get('user',{}).get('id')
        if not uid:raise RuntimeError('No user identity returned')
        try:
            await db.request('rest/v1/profiles','POST',{'id':uid,'display_name':payload.display_name,'role':'admin','active':True})
            await db.request('rest/v1/login_identities','POST',{'login_id':payload.login_id,'email':payload.email,'user_id':uid})
        except Exception:
            print('Auth user exists but the profile could not be created. Finish profile and login identity provisioning in Supabase using ID:',uid)
            raise
    print('Administrator provisioned. Sign in through the website.')

if __name__=='__main__':asyncio.run(main())
