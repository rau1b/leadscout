-- Contract C3: Overture's plain category label (basic_category) and its other taxonomy categories.
alter table businesses add column basic_category text;
alter table businesses add column category_alternates text default '[]';

-- Where each business came from: one row per source, ids and dates only, never a raw payload.
-- Cascades, so forget and the retention purge remove it with the business.
create table if not exists source_records (
    business_id text not null references businesses(id) on delete cascade,
    source text not null,
    source_id text,
    fetched_at text not null,
    release text,
    unique (business_id, source)
);

-- Businesses stored before this migration: their source is known, the Overture release isn't.
insert or ignore into source_records (business_id, source, source_id, fetched_at)
select id, source, case when source = 'overture' then id end, fetched_at from businesses;
