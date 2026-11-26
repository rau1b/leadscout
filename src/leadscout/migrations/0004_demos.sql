-- Demo pages built for a business (Show & close track; see docs/CONTRACTS.md, "demos table").
-- Cascades with businesses, so forget() and the retention purge remove the rows too.
create table if not exists demos (
    slug text primary key,
    business_id text not null references businesses(id) on delete cascade,
    template text not null,
    url text,
    built_at text not null,
    expires_at text not null,
    first_viewed_at text,
    view_count integer not null default 0
);
create index if not exists idx_demos_business on demos(business_id);
