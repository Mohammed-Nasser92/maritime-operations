# Maritime Operations API v3 — implemented contract

This is the standalone server in `server/app.py`. The friend's Phase 2 can connect later; its source files are not a prerequisite to run this application. No flight-control code is implemented here.

## Access classes

- Browser/user: `Authorization: Bearer <Supabase user JWT>`. Server verifies through Auth /user and current_session_security RPC, requires matching auth.uid() plus aal2, then checks active membership and role. A password-only AAL1 session cannot access any operational endpoint.
- Producer/external system: `Authorization: Bearer <INGEST_API_KEY>` (32+ random characters). Never expose this in the website.
- Server: Supabase secret held only in environment; SQL mutations are service-only.

## Event input — existing names preserved

```json
{
 "event_id":"EVT-001", "mission_id":"MIS-001", "track_id":7,
 "object":"floating_mine_candidate", "person_visible":null,
 "confidence":0.87, "latitude":17.123, "longitude":42.456,
 "location_validity":"Approximate", "timestamp":"2026-09-28T03:00:00Z",
 "image_path":null, "status":"pending",
 "bbox":[0.1,0.2,0.5,0.7], "model_version":"V8.2",
 "delivery_status":"delivered"
}
```

All timestamps timezone-aware. confidence 0..1. bbox normalized xmin,ymin,xmax,ymax with positive extent. person_visible null = unknown, false = no person visible. Unavailable locations must not be treated as object GPS. A path, when supplied in JSON, is an already uploaded private Storage object key; no external URL or Windows path.

Classification labels stay unchanged. Candidate/possible is never confirmed merely because review is accepted. Boat, swimmer, buoy, floating_mine_candidate and person_in_water? have explicit display labels.

## Producer API

| Method | Path | Input/result |
|---|---|---|
| POST | /api/v1/events | JSON above; legacy /events aliases this protected ingest route |
| POST | /api/v1/events/upload | multipart event_json string + image file |
| POST | /api/v1/ingest/telemetry | Telemetry JSON below |
| PUT | /api/v1/ingest/capabilities | Array of code,label,description,enabled,reason; upserts supplied codes |
| POST | /api/v1/ingest/commands/claim?drone_id=...&limit=10 | Atomically claims queued requests once |
| POST | /api/v1/ingest/commands/{command_id}/ack | `{status:"sent"/"acknowledged"/"rejected"/"failed", acknowledgement:"..."}` |

Event ingest validates image bytes, size10MiB and pixel limits. Stores content-addressed objects in private event-images bucket, then inserts mission/track/event in one SQL transaction. Same event_id + same normalized payload returns existing record without a new deadline. Different payload with same ID returns409. A failed/ambiguous commit can be retried; orphan image objects remain private until reviewed for cleanup.

review_started_at is database receipt time; review_expires_at = +20 seconds. Agree how old buffered events should be treated before UAV integration. No delayed flight commands are inferred automatically from stale detections.

## User API

| Method | Path | Purpose |
|---|---|---|
| GET | /api/v1/me | Active profile |
| GET | /api/v1/events?limit=25&offset=0&status=pending | Paginated records |
| GET | /api/v1/events/{id} | Complete record |
| GET | /api/v1/events/{id}/image | Temporary signed URL60 seconds |
| GET | /api/v1/capabilities | Permitted external commands |
| POST | /api/v1/events/{id}/decision | `{decision:"accepted"/"rejected",expected_version:0}` |
| POST | /api/v1/commands | Request command with UUID Idempotency-Key |
| GET | /api/v1/commands?limit=25 | Own requests; admin all |
| POST | /api/v1/ws-ticket | Single-use ticket30 seconds |
| WS | /api/v1/ws?ticket=... | Origin checked, active-user notifications |

Browser reads Supabase REST under AAL2 RLS for archive search/counts; telemetry/history and signed event images are read through the authenticated API. No browser mutation grants. Decision handler derives actor_id from the verified token, locks the event row, checks the deadline and version, and writes the result + audit transactionally. Background expiry sweep runs every second. Late conflicting writes cannot replace a final decision.

## Admin API

| Method | Path | Purpose |
|---|---|---|
| GET / POST | /api/v1/admin/users | List or create accounts |
| PATCH | /api/v1/admin/users/{id} | `{active:false}`; no self-disable/admin-disable |
| PATCH | /api/v1/admin/users/{id}/role | `{role:"admin"}`; no self-change/admin-demotion |
| GET | /api/v1/admin/audit?limit=30 | Activity log |
| POST | /api/v1/admin/events/upload | multipart event_json + optional image; test records |

Create body: `{login_id,email,display_name,password,role}`. login_id is required (3–64 ASCII letters/digits/dot/dash/underscore, starts alphanumeric), case-insensitive and privately maps to a real Auth email. Role defaults to admin for the new unified user/admin workflow. Existing users keep their roles. Password minimum12 characters, sent only to Supabase Auth. Administrator attests email identity for provisioned accounts. If profile creation fails, server attempts to delete the newly created Auth account; otherwise it has no workspace access and the owner must resolve it. No plaintext password in profiles/audit/API response.

Bootstrap first administrator with `server/bootstrap_admin.py`, not a public signup page.

## Command lifecycle

Request body:

```json
{"command":"a_code_from_capabilities","drone_id":"UAV-01","mission_id":"MIS-001","telemetry_timestamp":"2026-09-28T03:00:00Z","reason":"Operator reason"}
```

- Active membership, allowlist, mission and telemetry freshness are checked in SQL.
- Same Idempotency-Key + exact payload returns the same request. Different payload conflicts.
- queued is stored, not executed. A producer claims a fresh queued request once; it becomes validated, meaning initial API validation/claim only, not flight-safety confirmation.
- Before actuation the external system must independently validate safety/geofence/energy, then report sent followed by acknowledged or rejected/failed. No UI state alone authorizes an aircraft.
- Requests queued longer than30 seconds are expired when the consumer polls. Claimed/sent requests without confirmation must be reconciled externally; they are not automatically re-dispatched, avoiding duplicate actions.
- Capability rows start empty. The external producer must explicitly register supported commands. To withdraw a code, send it again with enabled:false. An omitted code is not automatically removed.
- No YOLO/tracking/autopilot/4G implementation is included.

## Telemetry input

```json
{"drone_id":"UAV-01","mission_id":"MIS-001","flight_mode":"Patrol","mission_state":"Patrolling","battery_percent":76,"altitude_m":42,"speed_mps":6.4,"latitude":17.1262,"longitude":42.4591,"link_quality_percent":92,"updated_at":"2026-09-28T03:00:00Z","latest_image_path":null,"stream_url":null}
```

Older/equal timestamp cannot overwrite a newer row. Future timestamp >5 seconds rejected. UI uses15-second freshness and also disables on connection errors. stream_url is retained for protocol compatibility but v3 focuses on event photos and does not render a live video feed. Coordinates in this record belong to the aircraft, not the event target.

## WebSocket and deployment

Actual mutations publish event.created / event.updated / telemetry.updated / command.updated / access.updated immediately to connected clients in the same server process. Expiry sweep publishes when it changes records. Clients refetch authorized data. Heartbeat10 seconds; connection rotates after5 minutes; disabled membership is checked each time. Tickets hashed in PostgreSQL, consumed atomically once, no user JWT in URL. Redact ticket query strings from logs.

Run one Uvicorn worker for immediate in-process notifications. Before multi-worker scaling, replace Hub with a shared bus. Browser polling5 seconds restores missed data; changes written directly in Supabase outside this server are seen on that polling interval.

GET /health reports expiry-worker health. HTTP201 new record,200 successful/idempotent,202 command queued,400 invalid operation,401 unauthorized,403 forbidden,404 missing,409 conflict,413 oversize,422 invalid input,503 dependency unavailable.


## V3 password + Authenticator flow

- `POST /api/v1/auth/login` accepts `{login_id,password}` without a bearer token. It exchanges credentials with Supabase, returns access/refresh tokens with a password-only AAL1 session, and is rate limited in PostgreSQL.
- ID/email mapping and rate counters are service-only tables. Passwords are never stored in those tables or audit records. Unknown ID, wrong password and inactive account return the same generic401 error.
- `SUPABASE_PUBLISHABLE_KEY` is required server-side for password exchange. No secret key is sent to the browser.
- The frontend uses official Supabase Auth routes: GET /auth/v1/user for factors, POST /auth/v1/factors to enroll TOTP, POST /auth/v1/factors/{id}/challenge then /verify. It sends public apikey and the user's token only.
- Verified factor returns AAL2 tokens. The frontend then calls /api/v1/me; only success reveals the workspace.
- SQL003 hardens existing table/image RLS for AAL2. An attacker cannot bypass MFA by reading the data API directly.
- Existing accounts need server/assign_login_id.py after SQL003. This does not promote their roles.
- List users returns login_id as well as profile fields to an authorized admin; it does not return the private email mapping.
- Refresh token remains in memory only. Logout clears local state and requests local-session revocation. Refreshing the document requires signing in again.
- Recovery is an owner-provisioned process; no public MFA bypass or self-service recovery UI is provided.

## V3 GPS and telemetry extensions

`GET /api/v1/telemetry` returns up to20 latest drone states. `GET /api/v1/telemetry/{drone_id}/history?mission_id=...` returns the most recent600 samples, newest first, shaped as `{items:[{drone_id,mission_id,updated_at,snapshot:{...telemetry}}]}`. Both require active AAL2 membership.

Optional added telemetry fields (unknown remains null):

| Field | Meaning / validation |
|---|---|
| heading_deg | heading in degrees, 0 inclusive to360 exclusive |
| distance_to_home_m | source distance to home in metres, nonnegative |
| distance_travelled_m | accumulated distance from the vehicle, metres, nonnegative |
| home_latitude / home_longitude | paired WGS84 home coordinates |
| gps_satellites | satellite count, integer0..255 |
| gps_hdop | horizontal dilution of precision, dimensionless; not metres |
| gps_fix_type | no_fix / 2d / 3d / dgps / rtk_float / rtk_fixed |
| battery_voltage_v | volts, nonnegative |
| vertical_speed_mps | signed vertical speed, m/s; agree positive-axis convention with source |
| armed | boolean or null |
| flight_time_s | flight time in seconds, nonnegative integer |
| connection_type | connection label, max60 characters |
| signal_dbm | received signal in dBm, nonpositive |

Current latitude/longitude must be supplied together or both null. `gps_fix_type=no_fix` prevents the frontend from plotting coordinates as a valid drone fix. All samples go through the same strict timestamp ordering; a rejected stale sample is not added to history. Distances are not calculated by summing sparse route samples. If source distance_to_home_m is absent and both vehicle/home GPS exist, UI derives a clearly labelled horizontal Haversine distance.

Optional added event fields:

```json
{"drone_id":"UAV-01","drone_latitude":17.123,"drone_longitude":42.456,"target_accuracy_m":25,"location_source":"image_projection"}
```

- Event `latitude/longitude` continue to mean TARGET location. They are never replaced with drone GPS by the UI.
- drone_latitude/drone_longitude are paired vehicle coordinates at detection, not live aircraft state.
- target_accuracy_m is an optional nonnegative source-provided accuracy radius, not a guarantee calculated by the UI.
- location_source = unknown / target_gps / image_projection / manual. No inference is made from missing values.
- GPS attached to the aircraft does not by itself locate a distant target. That estimate belongs to the perception/localization stage, and validity must be included.
- altitude_m and vertical_speed_mps reference/sign conventions must be agreed before field integration; the UI does not transform reference frames.

## Stored artifacts and verification limits

Use /docs/openapi.json generated from this version of app.py for exact request schemas. tests use mocked hosted transport and a local PostgreSQL engine, not an active Supabase project or UAV. Authenticator phone setup, live maps, network restrictions and end-to-end GPS/image accuracy are deployment acceptance items.


## إضافات 3.1 المتوافقة

- نجاح POST events وevents/upload يضيف `received: true` و`event_id`، مع الإبقاء على `event` و`duplicate`. لا يعاد received=true عند الرفض أو فشل الحفظ.
- GET `/api/v1/archive`: event_id, status, object, from_date, to_date (YYYY-MM-DD UTC؛ تاريخ النهاية شامل)، offset, limit. الناتج `{items: [...], total: n}`. AAL2 وعضوية فعالة مطلوبان.
- GET `/api/v1/summary`: counts وserver_time من PostgreSQL في سياق المستخدم.
- Auth على FastAPI: GET auth/user، POST auth/refresh `{refresh_token}`، POST auth/logout، POST auth/factors (TOTP فقط)، DELETE auth/factors/{uuid} للتسجيل غير المكتمل فقط، POST auth/factors/{uuid}/challenge، POST auth/factors/{uuid}/verify `{challenge_id, code}`.
- هذه المسارات تحت `/api/v1`؛ FastAPI يتصل بـSupabase، ولا يحتاج المتصفح apikey. Session bearer بالذاكرة فقط. تعليمات تشغيل الواجهة القديمة التي تطلب مفتاح Supabase غير سارية في 3.1.
- WSS المتصفح لا يمثل WSS المنتج Jetson؛ الأخير لم يطبق بعد. عقود follow/resume وربط القرار بالأمر تحتاج تثبيتًا مع فريق Level 2.
