# Contracts between the tracks

What one track writes and the other reads. The owner may add fields. Renaming or removing one, or changing what it means, needs the other person's OK and an update to this file in the same PR. Tracks are described in [TRACKS.md](TRACKS.md).

## `demos` table (owned by rau1b, Show & close)

Planned; not in the schema yet. It arrives as a migration from the Show & close track.

| Column | Meaning |
|---|---|
| `business_id` | `references businesses(id) on delete cascade`, so `forget` and the retention purge remove demos too |
| `slug` | the demo's path on the preview host |
| `template` | which demo template was used |
| `url` | the full preview link put in a pitch |
| `built_at` | when it was built (ISO time, IST) |
| `expires_at` | when the preview host takes it down |
| `first_viewed_at` | first time the business opened it, or null |
| `view_count` | how many times it was opened |

- **Readers:** Jason's pitch and scoring code may use a demo's `url` and views, but only if the table exists. Check with `select 1 from sqlite_master where type = 'table' and name = 'demos'`. Find & qualify must keep working without it.
- **Privacy:** a demo page holds the business's details on the preview host. When `leadscout forget` deletes a business, its demo pages must come off the preview host too, not only out of the table. Show & close provides that.

## `audits.screenshot_path` (owned by Jason, Find & qualify)

Planned; not in the schema yet. It arrives as a migration from the Find & qualify track.

- The mobile "before" screenshot of the business's current site: a path under `data/`, or null when there's no site or the capture failed. Readers must handle null.
- It goes when the business goes: the audit row is cascade-deleted, and the file is deleted with it.

## Preview host → LeadScout (the demos sync)

Unsubscribes and views recorded on the preview host come back through one demos sync function, owned by Show & close. For each item it:

- **Unsubscribe:** calls `compliance.opt_out(con, value, "unsubscribe link")`. This is the only way it records an opt-out. It never writes to `suppression` or `leads.status` directly, so the strongest-reason rule and the opt-out marking stay in one place (Find & qualify).
- **View:** updates `demos.first_viewed_at` and `view_count`, and logs `demo_viewed`.
- Logs every change with `db.log_event(con, type, business_id, actor="preview-host", ...)`.

## Events

Written with `db.log_event(con, type, business_id=None, actor="system", **data)`.

- **Names** are snake_case, in the past tense.
- **`data`** never holds contact details (emails, phone numbers) or message text. Use ids and counts. Events tied to a business are deleted with it, but events with no business are kept.
- **`actor`** is one of `system`, `dashboard`, `cli`, `preview-host`.

| Writer | Event types |
|---|---|
| Find & qualify (Jason) | `audit_done`, `pitch_drafted`, `pitch_sent`, `reply_received`, `reply_labelled`, `opted_out` |
| Show & close (rau1b) | `demo_built`, `demo_viewed`, `demo_expired`, `proposal_sent`, `invoice_sent`, `invoice_paid` |
| Shared | `settings_changed` (the Settings page; data: the changed key names only) |

Only `settings_changed` is written today. To add a type, add it to this table in the same PR.
