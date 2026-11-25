-- Baseline: the schema as it was before numbered migrations (db.SCHEMA plus every column db._migrate() added).
-- "if not exists" lets databases made before migrations existed pick up any table they lack.
create table if not exists businesses (
    id text primary key,
    source text not null,
    name text not null,
    category text,
    category_path text,
    address text,
    locality text,
    postcode text,
    lat real,
    lon real,
    phone text,
    phone_type text,
    website text,
    emails text default '[]',
    socials text default '[]',
    confidence real,
    brand text,
    area text,
    city text,
    fetched_at text not null
);
create table if not exists searches (
    id integer primary key autoincrement,
    city text not null,
    neighbourhood text,
    label text not null,
    categories text not null,
    status text not null default 'queued',
    message text,
    places integer,
    stored integer,
    created_at text not null,
    finished_at text,
    lat real,
    lon real,
    state text,
    population integer,
    resolved text
);
create table if not exists audits (
    business_id text primary key references businesses(id) on delete cascade,
    site_class text not null,
    final_url text,
    status_code integer,
    https integer,
    viewport integer,
    copyright_year integer,
    generator text,
    has_whatsapp integer,
    has_tel integer,
    has_maps integer,
    has_form integer,
    found_emails text default '[]',
    perf_score integer,
    lcp_s real,
    cls real,
    tbt_ms integer,
    psi_error text,
    fetch_error text,
    audited_at text not null
);
create table if not exists leads (
    business_id text primary key references businesses(id) on delete cascade,
    score integer not null,
    reasons text not null default '[]',
    status text not null default 'new',
    email text,
    email_ok integer,
    quote_inr integer,
    paid_inr integer,
    deal_note text,
    won_at text,
    updated_at text not null
);
create table if not exists pitches (
    business_id text primary key references businesses(id) on delete cascade,
    subject text not null,
    body text not null,
    whatsapp text,
    source text not null,
    approved integer not null default 0,
    created_at text not null,
    updated_at text not null
);
create table if not exists outreach (
    id integer primary key autoincrement,
    business_id text references businesses(id) on delete cascade,
    channel text not null,
    kind text not null,
    to_addr text,
    gmail_id text,
    thread_id text,
    sent_at text not null
);
create table if not exists suppression (
    value_hash text primary key,
    reason text,
    added_at text not null
);
create table if not exists replies (
    gmail_id text primary key,
    business_id text references businesses(id) on delete cascade,
    thread_id text,
    from_addr text,
    subject text,
    body text,
    received_at text,
    kind text
);
create table if not exists meta (key text primary key, value text);
create index if not exists idx_leads_status on leads(status);
create index if not exists idx_outreach_sent on outreach(sent_at);
