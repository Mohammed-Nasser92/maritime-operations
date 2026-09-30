-- Maritime Phase 3 / Supabase baseline, v1.
-- Apply ONCE to a NEW Supabase project after Phase 2 agrees to this contract.
-- This does not migrate or delete the existing SQLite database.
-- Actual image bytes live in a PRIVATE Storage bucket; rows retain the object key.
begin;
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null check (length(display_name) between 1 and 120),
  role text not null default 'operator' check (role in ('admin','operator')),
  active boolean not null default true,
  created_at timestamptz not null default now()
);
create or replace function public.has_workspace_access()
returns boolean language sql stable security definer set search_path = '' as $$
  select exists(select 1 from public.profiles where id = auth.uid() and active);
$$;
create or replace function public.is_workspace_admin()
returns boolean language sql stable security definer set search_path = '' as $$
  select exists(select 1 from public.profiles where id = auth.uid() and active and role = 'admin');
$$;
revoke all on function public.has_workspace_access() from public, anon;
revoke all on function public.is_workspace_admin() from public, anon;
grant execute on function public.has_workspace_access(), public.is_workspace_admin() to authenticated, service_role;

create table public.missions (
  mission_id text primary key,
  state text not null default 'unknown',
  created_at timestamptz not null default now()
);
create table public.tracks (
  mission_id text not null references public.missions(mission_id),
  track_id bigint not null,
  object text not null,
  updated_at timestamptz not null default now(),
  primary key(mission_id,track_id)
);
create table public.events (
  event_id text primary key check (length(event_id) between 1 and 160),
  mission_id text not null references public.missions(mission_id),
  track_id bigint,
  object text not null check (length(object) between 1 and 100),
  person_visible boolean,
  confidence double precision check (confidence between 0 and 1),
  latitude double precision check (latitude between -90 and 90),
  longitude double precision check (longitude between -180 and 180),
  location_validity text not null default 'Unavailable'
    check (location_validity in ('Valid','Approximate','Unavailable')),
  timestamp timestamptz not null,
  received_at timestamptz not null default now(),
  review_started_at timestamptz not null default now(),
  review_expires_at timestamptz not null default (now() + interval '20 seconds'),
  image_path text,
  status text not null default 'pending' check (status in ('pending','accepted','rejected','timeout')),
  decision text check (decision in ('accepted','rejected','timeout')),
  decision_time timestamptz,
  operator_id uuid references public.profiles(id),
  version bigint not null default 0 check (version >= 0),
  bbox jsonb check (bbox is null or (jsonb_typeof(bbox)='array' and jsonb_array_length(bbox)=4)),
  model_version text,
  delivery_status text not null default 'delivered',
  foreign key (mission_id,track_id) references public.tracks(mission_id,track_id),
  check ((status='pending' and decision is null and decision_time is null and operator_id is null)
    or (status in ('accepted','rejected') and decision=status and decision_time is not null and operator_id is not null)
    or (status='timeout' and decision='timeout' and decision_time is not null and operator_id is null)),
  check (location_validity='Unavailable' or (latitude is not null and longitude is not null))
);
create index events_timestamp_idx on public.events(timestamp desc,event_id);
create index events_status_timestamp_idx on public.events(status,timestamp desc);
create index events_expiry_idx on public.events(review_expires_at) where status='pending';
create table public.drone_state (
  drone_id text primary key,
  mission_id text references public.missions(mission_id),
  flight_mode text,
  mission_state text,
  battery_percent double precision check (battery_percent between 0 and 100),
  altitude_m double precision,
  speed_mps double precision check (speed_mps >= 0),
  latitude double precision check (latitude between -90 and 90),
  longitude double precision check (longitude between -180 and 180),
  link_quality_percent double precision check (link_quality_percent between 0 and 100),
  updated_at timestamptz not null,
  latest_image_path text,
  stream_url text
);
create table public.audit_log (
  id bigint generated always as identity primary key,
  actor_id uuid references public.profiles(id),
  action text not null,
  event_id text references public.events(event_id),
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index audit_created_idx on public.audit_log(created_at desc);
create table public.command_capabilities (
  code text primary key,
  label text not null,
  description text,
  enabled boolean not null default false,
  reason text default 'Phase 2 command dispatcher is not connected'
);
-- No commands are enabled by default. Phase 2 owns the allowlist.
create table public.command_requests (
  command_id uuid primary key default gen_random_uuid(),
  request_key uuid not null,
  actor_id uuid not null references public.profiles(id),
  command text not null references public.command_capabilities(code),
  drone_id text not null references public.drone_state(drone_id),
  mission_id text,
  telemetry_timestamp timestamptz not null,
  reason text not null check (length(reason) between 1 and 300),
  status text not null default 'queued' check (status in ('queued','validated','sent','acknowledged','rejected','failed','expired')),
  acknowledgement text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(actor_id,request_key)
);

-- No client can promote itself, insert events, edit decisions, or issue commands directly.
alter table public.profiles enable row level security;
alter table public.missions enable row level security;
alter table public.tracks enable row level security;
alter table public.events enable row level security;
alter table public.drone_state enable row level security;
alter table public.audit_log enable row level security;
alter table public.command_capabilities enable row level security;
alter table public.command_requests enable row level security;
revoke all on public.profiles,public.missions,public.tracks,public.events,public.drone_state,public.audit_log,public.command_capabilities,public.command_requests from anon,authenticated;
grant select on public.profiles,public.missions,public.tracks,public.events,public.drone_state,public.audit_log,public.command_capabilities,public.command_requests to authenticated;
grant all on public.profiles,public.missions,public.tracks,public.events,public.drone_state,public.audit_log,public.command_capabilities,public.command_requests to service_role;
grant usage,select on all sequences in schema public to service_role;
create policy profiles_read on public.profiles for select to authenticated
  using ((id=auth.uid()) or public.is_workspace_admin());
create policy missions_read on public.missions for select to authenticated using (public.has_workspace_access());
create policy tracks_read on public.tracks for select to authenticated using (public.has_workspace_access());
create policy events_read on public.events for select to authenticated using (public.has_workspace_access());
create policy drone_read on public.drone_state for select to authenticated using (public.has_workspace_access());
create policy audit_read on public.audit_log for select to authenticated using (public.is_workspace_admin());
create policy capabilities_read on public.command_capabilities for select to authenticated using (public.has_workspace_access());
create policy commands_read on public.command_requests for select to authenticated
  using (public.has_workspace_access() and (actor_id=auth.uid() or public.is_workspace_admin()));

create function public.workspace_summary() returns jsonb
language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object('server_time',now(),'counts',jsonb_build_object(
    'pending',count(*) filter(where status='pending'),
    'accepted',count(*) filter(where status='accepted'),
    'rejected',count(*) filter(where status='rejected'),
    'timeout',count(*) filter(where status='timeout')))
  from public.events;
$$;
revoke all on function public.workspace_summary() from public,anon;
grant execute on function public.workspace_summary() to authenticated,service_role;

-- Protect final states even from accidental backend UPDATE calls.
create function public.protect_event_state() returns trigger
language plpgsql set search_path = '' as $$
begin
  if TG_OP='INSERT' then
    if NEW.status <> 'pending' then raise exception 'New events must begin pending'; end if;
    NEW.received_at := clock_timestamp();
    NEW.review_started_at := NEW.received_at;
    NEW.review_expires_at := NEW.review_started_at + interval '20 seconds';
    NEW.version := 0;
  else
    if OLD.status <> 'pending' and
      (NEW.status,NEW.decision,NEW.decision_time,NEW.operator_id) is distinct from
      (OLD.status,OLD.decision,OLD.decision_time,OLD.operator_id) then
      raise exception 'Final event decision is immutable';
    end if;
    if (NEW.review_started_at,NEW.review_expires_at) is distinct from
      (OLD.review_started_at,OLD.review_expires_at) then raise exception 'Review window is immutable'; end if;
    if OLD.status='pending' and NEW.status in ('accepted','rejected') and clock_timestamp() >= OLD.review_expires_at then
      raise exception 'Review window expired' using errcode='P2001';
    end if;
    if OLD.status='pending' and NEW.status='timeout' and clock_timestamp() < OLD.review_expires_at then
      raise exception 'Cannot timeout before deadline';
    end if;
  end if;
  return NEW;
end;
$$;
create trigger protect_event_state before insert or update on public.events
for each row execute function public.protect_event_state();

-- Service-only: Phase 2 verifies JWT and derives actor_id from that verified identity.
create function public.review_event(p_event_id text,p_actor_id uuid,p_decision text,p_expected_version bigint)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare e public.events; t timestamptz;
begin
  if not exists(select 1 from public.profiles where id=p_actor_id and active) then
    return jsonb_build_object('code',403,'detail','Active operator account required');
  end if;
  if p_decision not in ('accepted','rejected') then return jsonb_build_object('code',400,'detail','Invalid decision'); end if;
  select * into e from public.events where event_id=p_event_id for update;
  if not found then return jsonb_build_object('code',404,'detail','Event not found'); end if;
  if e.status <> 'pending' then
    if e.status=p_decision and e.operator_id=p_actor_id then return jsonb_build_object('code',200,'event',to_jsonb(e)); end if;
    return jsonb_build_object('code',409,'detail','Final decision is already recorded','event',to_jsonb(e));
  end if;
  t := clock_timestamp();
  if t >= e.review_expires_at then
    update public.events set status='timeout',decision='timeout',decision_time=e.review_expires_at,operator_id=null,version=version+1 where event_id=p_event_id returning * into e;
    insert into public.audit_log(action,event_id) values('event.timeout',p_event_id);
    return jsonb_build_object('code',409,'detail','Review window expired','event',to_jsonb(e));
  end if;
  if e.version<>p_expected_version then return jsonb_build_object('code',409,'detail','Event version changed','event',to_jsonb(e)); end if;
  begin
    update public.events set status=p_decision,decision=p_decision,decision_time=t,operator_id=p_actor_id,version=version+1 where event_id=p_event_id returning * into e;
  exception when sqlstate 'P2001' then
    -- Deadline may pass between the check and the trigger. Persist timeout,
    -- return a conflict, and never turn this boundary into an ambiguous 500.
    update public.events set status='timeout',decision='timeout',decision_time=review_expires_at,operator_id=null,version=version+1 where event_id=p_event_id returning * into e;
    insert into public.audit_log(action,event_id) values('event.timeout',p_event_id);
    return jsonb_build_object('code',409,'detail','Review window expired','event',to_jsonb(e));
  end;
  insert into public.audit_log(actor_id,action,event_id) values(p_actor_id,'event.'||p_decision,p_event_id);
  return jsonb_build_object('code',200,'event',to_jsonb(e));
end;
$$;
create function public.expire_pending_events() returns integer
language plpgsql security definer set search_path = '' as $$
declare affected integer;
begin
  with due as (select event_id from public.events where status='pending' and review_expires_at<=clock_timestamp() order by review_expires_at limit 500 for update skip locked),
  changed as (update public.events e set status='timeout',decision='timeout',decision_time=e.review_expires_at,operator_id=null,version=e.version+1 from due where e.event_id=due.event_id and e.status='pending' returning e.event_id)
  insert into public.audit_log(action,event_id) select 'event.timeout',event_id from changed;
  get diagnostics affected = row_count;
  return affected;
end;
$$;
create function public.set_member_access(p_actor_id uuid,p_user_id uuid,p_active boolean) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare u public.profiles;
begin
  if not exists(select 1 from public.profiles where id=p_actor_id and active and role='admin') then return jsonb_build_object('code',403,'detail','Administrator role required'); end if;
  if p_actor_id=p_user_id then return jsonb_build_object('code',400,'detail','Self access changes are not allowed'); end if;
  select * into u from public.profiles where id=p_user_id for update;
  if not found then return jsonb_build_object('code',404,'detail','User not found'); end if;
  -- Admin-to-admin removal is deliberately outside this UI to prevent lockouts.
  if u.role='admin' then return jsonb_build_object('code',400,'detail','Administrator access must be managed through the provisioning process'); end if;
  update public.profiles set active=p_active where id=p_user_id returning * into u;
  insert into public.audit_log(actor_id,action,details) values(p_actor_id,'user.access_changed',jsonb_build_object('user_id',p_user_id,'active',p_active));
  return jsonb_build_object('code',200,'user',to_jsonb(u));
end;
$$;
create function public.request_command(p_actor_id uuid,p_request_key uuid,p_command text,p_drone_id text,p_mission_id text,p_telemetry_timestamp timestamptz,p_reason text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare c public.command_requests; d public.drone_state;
begin
  if not exists(select 1 from public.profiles where id=p_actor_id and active) then return jsonb_build_object('code',403,'detail','Active operator account required'); end if;
  -- Serialize retries sharing one idempotency key, including simultaneous retries.
  perform pg_advisory_xact_lock(hashtextextended(p_actor_id::text||p_request_key::text,0));
  select * into c from public.command_requests where actor_id=p_actor_id and request_key=p_request_key;
  if found then
    if (c.command,c.drone_id,c.mission_id,c.telemetry_timestamp,c.reason) is distinct from (p_command,p_drone_id,p_mission_id,p_telemetry_timestamp,p_reason) then
      return jsonb_build_object('code',409,'detail','Request identifier was already used with a different payload');
    end if;
    return jsonb_build_object('code',200,'command',to_jsonb(c));
  end if;
  if not exists(select 1 from public.command_capabilities where code=p_command and enabled) then return jsonb_build_object('code',403,'detail','Command is not currently permitted'); end if;
  select * into d from public.drone_state where drone_id=p_drone_id for share;
  if not found or d.updated_at < clock_timestamp()-interval '15 seconds' or d.updated_at > clock_timestamp()+interval '5 seconds' then return jsonb_build_object('code',409,'detail','Fresh telemetry is required'); end if;
  if d.mission_id is distinct from p_mission_id or p_telemetry_timestamp < clock_timestamp()-interval '15 seconds' or p_telemetry_timestamp > d.updated_at then return jsonb_build_object('code',409,'detail','Mission or telemetry changed; refresh before retrying'); end if;
  insert into public.command_requests(actor_id,request_key,command,drone_id,mission_id,telemetry_timestamp,reason)
    values(p_actor_id,p_request_key,p_command,p_drone_id,p_mission_id,p_telemetry_timestamp,p_reason) returning * into c;
  insert into public.audit_log(actor_id,action,details) values(p_actor_id,'command.requested',jsonb_build_object('command_id',c.command_id,'command',p_command));
  return jsonb_build_object('code',202,'command',to_jsonb(c));
end;
$$;
revoke all on function public.review_event(text,uuid,text,bigint), public.expire_pending_events(),public.set_member_access(uuid,uuid,boolean),public.request_command(uuid,uuid,text,text,text,timestamptz,text) from public,anon,authenticated;
grant execute on function public.review_event(text,uuid,text,bigint), public.expire_pending_events(),public.set_member_access(uuid,uuid,boolean),public.request_command(uuid,uuid,text,text,text,timestamptz,text) to service_role;

insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('event-images','event-images',false,10485760,array['image/jpeg','image/png','image/webp']);
-- Only authenticated active members may sign image links. Uploads are server-only.
create policy event_images_read on storage.objects for select to authenticated
using(bucket_id='event-images' and public.has_workspace_access() and
  (exists(select 1 from public.events e where e.image_path=name)
   or exists(select 1 from public.drone_state d where d.latest_image_path=name)));
commit;
