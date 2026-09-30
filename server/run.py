"""One worker: browser notification queues are process-local."""
import os
import uvicorn

if __name__ == '__main__':
    uvicorn.run('app:app', host='0.0.0.0', port=int(os.environ.get('PORT', '8000')),
        workers=1, access_log=False, proxy_headers=True,
        forwarded_allow_ips=os.environ.get('FORWARDED_ALLOW_IPS', '127.0.0.1'),
        ws_max_size=65536, ws_ping_interval=20, ws_ping_timeout=20)
