-- Apply after 001_workspace.sql. Service-only mutations for independent server.
begin;
alter table public.events add column ingest_fingerprint text;
create table public.ws_tickets (
  ticket_hash text primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  expires_at timestamptz not null
);
alter table public.ws_tickets enable row level security;
revoke all on public.ws_tickets from public,anon,authenticated;
grant all on public.ws_tickets to service_role;
create function public.consume_ws_ticket(p_hash text) returns uuid
language plpgsql security definer set search_path='' as $$
declare v_user uuid;
begin
  delete from public.ws_tickets where ticket_hash=p_hash and expires_at>clock_timestamp() returning user_id into v_user;
  delete from public.ws_tickets where expires_at<=clock_timestamp();
  return v_user;
end;
$$;
create function public.ingest_event(p_event jsonb,p_fingerprint text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare e public.events;
begin
  perform pg_advisory_xact_lock(hashtextextended(p_event->>'event_id',0));
  select * into e from public.events where event_id=p_event->>'event_id';
  if found then
    if e.ingest_fingerprint=p_fingerprint then return jsonb_build_object('code',200,'event',to_jsonb(e),'duplicate',true); end if;
    return jsonb_build_object('code',409,'detail','Event ID already belongs to a different payload');
  end if;
  insert into public.missions(mission_id) values(p_event->>'mission_id') on conflict do nothing;
  if p_event->>'track_id' is not null then
    insert into public.tracks(mission_id,track_id,object)
    values(p_event->>'mission_id',(p_event->>'track_id')::bigint,p_event->>'object')
    on conflict(mission_id,track_id) do update set updated_at=clock_timestamp();
  end if;
  insert into public.events(event_id,mission_id,track_id,object,person_visible,confidence,latitude,longitude,location_validity,timestamp,image_path,bbox,model_version,delivery_status,ingest_fingerprint)
  values(p_event->>'event_id',p_event->>'mission_id',(p_event->>'track_id')::bigint,p_event->>'object',
    (p_event->>'person_visible')::boolean,(p_event->>'confidence')::double precision,
    (p_event->>'latitude')::double precision,(p_event->>'longitude')::double precision,
    p_event->>'location_validity',(p_event->>'timestamp')::timestamptz,p_event->>'image_path',
    nullif(p_event->'bbox','null'::jsonb),p_event->>'model_version',coalesce(p_event->>'delivery_status','delivered'),p_fingerprint)
  returning * into e;
  insert into public.audit_log(action,event_id) values('event.created',e.event_id);
  return jsonb_build_object('code',201,'event',to_jsonb(e),'duplicate',false);
end;
$$;
create function public.upsert_telemetry(p_state jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare d public.drone_state;
begin
  if p_state->>'mission_id' is not null then
    insert into public.missions(mission_id) values(p_state->>'mission_id') on conflict do nothing;
  end if;
  insert into public.drone_state(drone_id,mission_id,flight_mode,mission_state,battery_percent,altitude_m,speed_mps,latitude,longitude,link_quality_percent,updated_at,latest_image_path,stream_url)
  values(p_state->>'drone_id',p_state->>'mission_id',p_state->>'flight_mode',p_state->>'mission_state',
    (p_state->>'battery_percent')::double precision,(p_state->>'altitude_m')::double precision,
    (p_state->>'speed_mps')::double precision,(p_state->>'latitude')::double precision,(p_state->>'longitude')::double precision,
    (p_state->>'link_quality_percent')::double precision,(p_state->>'updated_at')::timestamptz,p_state->>'latest_image_path',p_state->>'stream_url')
  on conflict(drone_id) do update set mission_id=excluded.mission_id,flight_mode=excluded.flight_mode,
    mission_state=excluded.mission_state,battery_percent=excluded.battery_percent,altitude_m=excluded.altitude_m,
    speed_mps=excluded.speed_mps,latitude=excluded.latitude,longitude=excluded.longitude,
    link_quality_percent=excluded.link_quality_percent,updated_at=excluded.updated_at,
    latest_image_path=excluded.latest_image_path,stream_url=excluded.stream_url
  where excluded.updated_at>public.drone_state.updated_at returning * into d;
  if not found then return jsonb_build_object('code',409,'detail','Telemetry is older than the stored state'); end if;
  return jsonb_build_object('code',200,'state',to_jsonb(d));
end;
$$;
create function public.set_member_role(p_actor_id uuid,p_user_id uuid,p_role text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare u public.profiles;
begin
  if not exists(select 1 from public.profiles where id=p_actor_id and active and role='admin') then return jsonb_build_object('code',403,'detail','Administrator role required'); end if;
  if p_role not in ('admin','operator') then return jsonb_build_object('code',400,'detail','Invalid role'); end if;
  if p_actor_id=p_user_id then return jsonb_build_object('code',400,'detail','Self role changes are not allowed'); end if;
  select * into u from public.profiles where id=p_user_id for update;
  if not found then return jsonb_build_object('code',404,'detail','User not found'); end if;
  if u.role='admin' then return jsonb_build_object('code',400,'detail','Demoting administrators requires the owner provisioning process'); end if;
  update public.profiles set role=p_role where id=p_user_id returning * into u;
  insert into public.audit_log(actor_id,action,details) values(p_actor_id,'user.role_changed',jsonb_build_object('user_id',p_user_id,'role',p_role));
  return jsonb_build_object('code',200,'user',to_jsonb(u));
end;
$$;
-- The UI can configure a command as available only after the external consumer is connected.
-- Server-side machine API updates capability availability; UI cannot enable arbitrary flight actions.
create function public.claim_commands(p_drone_id text,p_limit integer default 10) returns setof public.command_requests
language plpgsql security definer set search_path='' as $$
begin
  update public.command_requests set status='expired',acknowledgement='Request expired before dispatch',updated_at=clock_timestamp()
    where drone_id=p_drone_id and status='queued' and created_at<clock_timestamp()-interval '30 seconds';
  return query with selected as (
    select c.command_id from public.command_requests c
    join public.drone_state d on d.drone_id=c.drone_id
    join public.command_capabilities k on k.code=c.command and k.enabled
    join public.profiles u on u.id=c.actor_id and u.active
    where c.drone_id=p_drone_id and c.status='queued'
      and d.updated_at>clock_timestamp()-interval '15 seconds'
      and d.updated_at<=clock_timestamp()+interval '5 seconds'
      and d.mission_id is not distinct from c.mission_id
    order by c.created_at limit least(greatest(p_limit,1),20) for update of c skip locked
  ) update public.command_requests c set status='validated',updated_at=clock_timestamp()
    from selected where c.command_id=selected.command_id returning c.*;
end;
$$;
create function public.acknowledge_command(p_command_id uuid,p_status text,p_ack text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare c public.command_requests;
begin
  if p_status not in ('sent','acknowledged','rejected','failed') then return jsonb_build_object('code',400,'detail','Invalid acknowledgement status'); end if;
  select * into c from public.command_requests where command_id=p_command_id for update;
  if not found then return jsonb_build_object('code',404,'detail','Command not found'); end if;
  if c.status=p_status then return jsonb_build_object('code',200,'command',to_jsonb(c)); end if;
  if c.status in ('acknowledged','rejected','failed','expired') then return jsonb_build_object('code',409,'detail','Command already has a final result'); end if;
  if not ((c.status='validated' and p_status in ('sent','rejected','failed')) or (c.status='sent' and p_status in ('acknowledged','rejected','failed'))) then return jsonb_build_object('code',409,'detail','Invalid command transition'); end if;
  update public.command_requests set status=p_status,acknowledgement=p_ack,updated_at=clock_timestamp() where command_id=p_command_id returning * into c;
  insert into public.audit_log(action,details) values('command.'||p_status,jsonb_build_object('command_id',p_command_id));
  return jsonb_build_object('code',200,'command',to_jsonb(c));
end;
$$;
revoke all on function public.consume_ws_ticket(text),public.ingest_event(jsonb,text),public.upsert_telemetry(jsonb),public.set_member_role(uuid,uuid,text),public.claim_commands(text,integer),public.acknowledge_command(uuid,text,text) from public,anon,authenticated;
grant execute on function public.consume_ws_ticket(text),public.ingest_event(jsonb,text),public.upsert_telemetry(jsonb),public.set_member_role(uuid,uuid,text),public.claim_commands(text,integer),public.acknowledge_command(uuid,text,text) to service_role;
commit;
