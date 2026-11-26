-- What `leadscout demos sync` pulled from the preview host (Show & close track).
-- One row per item the host handed over (its key), so a sync that's interrupted and run again never counts anything twice.
-- kind: 'view' (value = demo slug) or 'unsub' (value = unsubscribe token). No personal data: a slug or a token and a time.
-- done_at stays null while an item waits: an unsubscribe waits here until Find & qualify's resolve() exists (contract C4).
create table if not exists preview_items (
    key text primary key,
    kind text not null check (kind in ('view', 'unsub')),
    value text not null,
    at text not null,
    received_at text not null,
    done_at text,
    note text
);
create index if not exists idx_preview_items_pending on preview_items(done_at, kind);
