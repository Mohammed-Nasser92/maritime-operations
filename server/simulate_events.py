"""Standalone removable test producer. Never sends commands to a UAV."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4
import httpx

async def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--count',type=int,default=1)
    p.add_argument('--interval',type=float,default=3)
    p.add_argument('--image',type=Path)
    p.add_argument('--object',default='boat',choices=['boat','swimmer','buoy','floating_mine_candidate','person_in_water?'])
    args=p.parse_args()
    if not 1<=args.count<=100 or args.interval<0:p.error('count must be 1..100; interval must be nonnegative')
    url=os.environ.get('OPERATIONS_API_URL','http://127.0.0.1:8000').rstrip('/')
    key=os.environ['INGEST_API_KEY']
    async with httpx.AsyncClient(timeout=30,headers={'Authorization':'Bearer '+key}) as client:
        for i in range(args.count):
            event={'event_id':'TEST-'+uuid4().hex[:16],'mission_id':'MIS-TEST','track_id':i+1,'object':args.object,
                'person_visible':None,'confidence':0.87,'latitude':None,'longitude':None,'location_validity':'Unavailable',
                'timestamp':datetime.now(timezone.utc).isoformat(),'image_path':None,'status':'pending'}
            if args.image:
                with args.image.open('rb') as file:
                    response=await client.post(url+'/api/v1/events/upload',data={'event_json':json.dumps(event)},files={'image':(args.image.name,file)})
            else:response=await client.post(url+'/api/v1/events',json=event)
            response.raise_for_status()
            print(event['event_id'],response.status_code)
            if i<args.count-1:await asyncio.sleep(args.interval)

if __name__=='__main__':asyncio.run(main())
