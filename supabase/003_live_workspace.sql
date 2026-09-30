-- V3: execute ONCE after 001 + 002. Existing passwords/events are preserved.
-- Existing accounts require a login_identities row provisioned by the system owner.
begin;
create table public.login_identities (
 login_id text primary key check (login_id=lower(login_id) and login_id ~ '^[a-z0-9][a-z0-9_.-]{2,63}$'),
 user_id uuid unique not null references auth.users(id) on delete cascade,
 email text not null
);
create table public.login_attempts(key_hash text primary key, window_start timestamptz not null, attempts integer not null);
alter table public.login_identities enable row level security;
alter table public.login_attempts enable row level security;
revoke all on public.login_identities,public.login_attempts from public,anon,authenticated;
grant all on public.login_identities,public.login_attempts to service_role;
create function public.consume_login_attempt(p_key text,p_limit integer,p_seconds integer) returns boolean
language plpgsql security definer set search_path='' as $$
declare n integer;
begin
 delete from public.login_attempts where window_start<clock_timestamp()-interval '1 day';
 insert into public.login_attempts values(p_key,clock_timestamp(),1)
 on conflict(key_hash) do update set
 attempts=case when public.login_attempts.window_start<clock_timestamp()-make_interval(secs=>p_seconds) then 1 else public.login_attempts.attempts+1 end,
 window_start=case when public.login_attempts.window_start<clock_timestamp()-make_interval(secs=>p_seconds) then clock_timestamp() else public.login_attempts.window_start end
 returning attempts into n;
 return n<=p_limit;
end; $$;
revoke all on function public.consume_login_attempt(text,integer,integer) from public,anon,authenticated;
grant execute on function public.consume_login_attempt(text,integer,integer) to service_role;
create function public.current_session_security() returns jsonb
language sql stable security invoker set search_path='' as $$
 select jsonb_build_object('user_id',auth.uid(),'aal',auth.jwt()->>'aal');
$$;
revoke all on function public.current_session_security() from public,anon;
grant execute on function public.current_session_security() to authenticated,service_role;
-- Verified JWT context from Supabase, never from a browser-supplied role/flag.
create or replace function public.has_workspace_access() returns boolean
language sql stable security definer set search_path='' as $$
 select coalesce(auth.jwt()->>'aal'='aal2',false) and exists(select 1 from public.profiles where id=auth.uid() and active);
$$;
create or replace function public.is_workspace_admin() returns boolean
language sql stable security definer set search_path='' as $$
 select public.has_workspace_access() and exists(select 1 from public.profiles where id=auth.uid() and role='admin');
$$;
do $$ declare t text; begin
 foreach t in array array['profiles','missions','tracks','events','drone_state','audit_log','command_capabilities','command_requests'] loop
 execute format('create policy require_mfa on public.%I as restrictive for select to authenticated using (public.has_workspace_access())',t);
 end loop;
end; $$;
-- Preserve other buckets: the additional restriction is scoped to event-images.
create policy require_event_image_mfa on storage.objects as restrictive for select to authenticated
 using(bucket_id<>'event-images' or public.has_workspace_access());
alter table public.drone_state add column heading_deg double precision check (heading_deg>=0 and heading_deg<360);
alter table public.drone_state add column distance_to_home_m double precision check (distance_to_home_m>=0);
alter table public.drone_state add column distance_travelled_m double precision check (distance_travelled_m>=0);
alter table public.drone_state add column home_latitude double precision check(home_latitude between -90 and 90);
alter table public.drone_state add column home_longitude double precision check(home_longitude between -180 and 180);
alter table public.drone_state add column gps_satellites integer check(gps_satellites between 0 and 255);
alter table public.drone_state add column gps_hdop double precision check(gps_hdop>=0);
alter table public.drone_state add column gps_fix_type text check(gps_fix_type in ('no_fix','2d','3d','dgps','rtk_float','rtk_fixed'));
alter table public.drone_state add column battery_voltage_v double precision check(battery_voltage_v>=0);
alter table public.drone_state add column vertical_speed_mps double precision;
alter table public.drone_state add column armed boolean;
alter table public.drone_state add column flight_time_s integer check(flight_time_s>=0);
alter table public.drone_state add column connection_type text;
alter table public.drone_state add column signal_dbm double precision check(signal_dbm<=0);
create table public.telemetry_history (
 drone_id text not null, mission_id text, updated_at timestamptz not null,
 snapshot jsonb not null, primary key(drone_id,updated_at)
);
create index telemetry_mission_time on public.telemetry_history(drone_id,mission_id,updated_at desc);
alter table public.telemetry_history enable row level security;
revoke all on public.telemetry_history from public,anon,authenticated;
grant select on public.telemetry_history to authenticated;
grant all on public.telemetry_history to service_role;
create policy telemetry_history_read on public.telemetry_history for select to authenticated using(public.has_workspace_access());
alter function public.upsert_telemetry(jsonb) rename to upsert_telemetry_v2;
create function public.upsert_telemetry(p_state jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; d public.drone_state;
begin
 result:=public.upsert_telemetry_v2(p_state);
 if (result->>'code')::integer<>200 then return result; end if;
 update public.drone_state set
 heading_deg=(p_state->>'heading_deg')::double precision,
 distance_to_home_m=(p_state->>'distance_to_home_m')::double precision,
 distance_travelled_m=(p_state->>'distance_travelled_m')::double precision,
 home_latitude=(p_state->>'home_latitude')::double precision,
 home_longitude=(p_state->>'home_longitude')::double precision,
 gps_satellites=(p_state->>'gps_satellites')::integer,
 gps_hdop=(p_state->>'gps_hdop')::double precision,
 gps_fix_type=(p_state->>'gps_fix_type')::text,
 battery_voltage_v=(p_state->>'battery_voltage_v')::double precision,
 vertical_speed_mps=(p_state->>'vertical_speed_mps')::double precision,
 armed=(p_state->>'armed')::boolean,
 flight_time_s=(p_state->>'flight_time_s')::integer,
 connection_type=(p_state->>'connection_type')::text,
 signal_dbm=(p_state->>'signal_dbm')::double precision where drone_id=p_state->>'drone_id' returning * into d;
 insert into public.telemetry_history(drone_id,mission_id,updated_at,snapshot) values(d.drone_id,d.mission_id,d.updated_at,to_jsonb(d));
 return jsonb_build_object('code',200,'state',to_jsonb(d));
end; $$;
alter table public.events add column drone_id text;
alter table public.events add column drone_latitude double precision check(drone_latitude between -90 and 90);
alter table public.events add column drone_longitude double precision check(drone_longitude between -180 and 180);
alter table public.events add column target_accuracy_m double precision check(target_accuracy_m>=0);
alter table public.events add column location_source text not null default 'unknown' check(location_source in ('unknown','target_gps','image_projection','manual'));
alter function public.ingest_event(jsonb,text) rename to ingest_event_v2;
create function public.ingest_event(p_event jsonb,p_fingerprint text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; e public.events;
begin
 result:=public.ingest_event_v2(p_event,p_fingerprint);
 if (result->>'code')::integer<>201 then return result; end if;
 update public.events set drone_id=p_event->>'drone_id',drone_latitude=(p_event->>'drone_latitude')::double precision,
 drone_longitude=(p_event->>'drone_longitude')::double precision,target_accuracy_m=(p_event->>'target_accuracy_m')::double precision,
 location_source=coalesce(p_event->>'location_source','unknown') where event_id=p_event->>'event_id' returning * into e;
 return jsonb_build_object('code',201,'event',to_jsonb(e),'duplicate',false);
end; $$;
revoke all on function public.upsert_telemetry(jsonb),public.ingest_event(jsonb,text) from public,anon,authenticated;
grant execute on function public.upsert_telemetry(jsonb),public.ingest_event(jsonb,text) to service_role;
-- Internal V2 implementations cannot bypass V3 via a client.
revoke all on function public.upsert_telemetry_v2(jsonb),public.ingest_event_v2(jsonb,text) from public,anon,authenticated,service_role;
commit;
