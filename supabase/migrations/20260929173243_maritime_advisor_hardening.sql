-- Apply after 001_workspace.sql, 002_complete_server.sql and 003_live_workspace.sql.
begin;

-- Policy helpers need profile lookup without recursive RLS, but are not Data API RPCs.
create schema maritime_private;
revoke all on schema maritime_private from public, anon;
grant usage on schema maritime_private to authenticated, service_role;
alter function public.has_workspace_access() set schema maritime_private;
alter function public.is_workspace_admin() set schema maritime_private;
create or replace function maritime_private.is_workspace_admin() returns boolean
language sql stable security definer set search_path='' as $$
 select maritime_private.has_workspace_access() and exists(
   select 1 from public.profiles where id=auth.uid() and role='admin'
 );
$$;
revoke all on function maritime_private.has_workspace_access(), maritime_private.is_workspace_admin() from public, anon;
grant execute on function maritime_private.has_workspace_access(), maritime_private.is_workspace_admin() to authenticated, service_role;

-- Existing policies retain function OID dependencies after SET SCHEMA.
-- Cache per-request auth lookups in the two policies flagged by the advisor.
alter policy profiles_read on public.profiles
 using (id=(select auth.uid()) or (select maritime_private.is_workspace_admin()));
alter policy commands_read on public.command_requests
 using ((select maritime_private.has_workspace_access()) and
        (actor_id=(select auth.uid()) or (select maritime_private.is_workspace_admin())));

create index audit_log_actor_id_idx on public.audit_log(actor_id);
create index audit_log_event_id_idx on public.audit_log(event_id);
create index command_requests_command_idx on public.command_requests(command);
create index command_requests_drone_id_idx on public.command_requests(drone_id);
create index drone_state_mission_id_idx on public.drone_state(mission_id);
create index events_mission_track_idx on public.events(mission_id,track_id);
create index events_operator_id_idx on public.events(operator_id);
create index ws_tickets_user_id_idx on public.ws_tickets(user_id);

-- login_attempts, login_identities and ws_tickets deliberately have no client policy.
-- They are server-only; RLS and revoked client privileges must remain in place.
commit;
