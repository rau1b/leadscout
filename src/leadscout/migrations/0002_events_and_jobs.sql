-- What happened to each business, and background work the dashboard runs.
-- events cascade with businesses: forget() deletes a business, and its events must not keep that person's data.
create table if not exists events (
    id integer primary key,
    at text not null,
    business_id text references businesses(id) on delete cascade,
    type text not null,
    actor text not null,
    data_json text
);
create index if not exists idx_events_business on events(business_id, at);
create index if not exists idx_events_type on events(type, at);

create table if not exists jobs (
    id integer primary key,
    type text not null,
    args_json text,
    status text not null default 'queued' check (status in ('queued', 'running', 'done', 'failed', 'cancelled')),
    progress real default 0,
    attempts integer default 0,
    error text,
    created_at text not null,
    started_at text,
    finished_at text
);
create index if not exists idx_jobs_status on jobs(status, created_at);
