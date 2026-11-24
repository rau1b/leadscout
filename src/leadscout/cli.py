"""leadscout command line. Run `leadscout --help`."""

import csv
import shutil
from pathlib import Path

import typer

from leadscout import config, db

app = typer.Typer(help="Find, audit and pitch Indian local businesses with weak or missing websites.", no_args_is_help=True)


def _ctx():
    return config.load(), db.connect()


@app.command()
def init():
    """Create config.toml from the example. Edit it with your details afterwards."""
    target = config.home() / "config.toml"
    if target.exists():
        typer.echo("config.toml already exists.")
        return
    shutil.copy(Path(__file__).resolve().parents[2] / "config.example.toml", target)
    config.data_dir()
    typer.echo(f"Created {target}. Fill in the [sender] section before sending anything.")


@app.command()
def find(
    category: str = typer.Argument(..., help='What to look for, e.g. "dentist" or "interior design". Use "all" for everything.'),
    area: str = typer.Option(None, help='Area name, e.g. "Kukatpally, Hyderabad".'),
    bbox: str = typer.Option(None, help="Or a box: west,south,east,north"),
    min_confidence: float = typer.Option(0.5, help="Skip places Overture is unsure exist (0-1)."),
):
    """Download businesses from Overture Maps (free) into the local database."""
    from leadscout.sources import geo, overture

    if not (area or bbox):
        raise typer.BadParameter("Give --area or --bbox.")
    box = geo.parse_bbox(bbox) if bbox else geo.area_bbox(area)
    typer.echo(f"Downloading places in {box} from Overture Maps...")
    _, con = _ctx()
    total, stored = overture.ingest(con, box, category.split(","), area or bbox, min_confidence)
    typer.echo(f"{total} places in the area, {stored} matched '{category}' and were saved.")


@app.command("import-csv")
def import_csv(path: str, area: str = typer.Option("manual", help="Label for this batch.")):
    """Import businesses you collected yourself (columns: name, phone, website, email, category, address, locality)."""
    from leadscout.sources import csv_import

    _, con = _ctx()
    typer.echo(f"Imported {csv_import.ingest(con, path, area)} businesses.")


@app.command()
def audit(
    pagespeed: bool = typer.Option(True, help="Run Google PageSpeed on working sites (slower, but gives real numbers)."),
    limit: int = typer.Option(None, help="Audit at most this many businesses."),
):
    """Check every new business's website."""
    from leadscout.audit import audit_pending

    cfg, con = _ctx()
    done = {"n": 0}

    def progress(name, site_class):
        done["n"] += 1
        typer.echo(f"  {done['n']:>4}  {site_class:<17} {name[:60]}")

    if pagespeed and not cfg.google_api_key:
        typer.echo("No GOOGLE_API_KEY in .env: PageSpeed will mostly be refused. Add a free key (see .env.example), or use --no-pagespeed.")
    n = audit_pending(con, cfg.google_api_key, pagespeed, limit, progress)
    typer.echo(f"Audited {n} businesses.")


@app.command("pagespeed")
def pagespeed_retry():
    """Run PageSpeed for working sites that don't have a score yet."""
    from leadscout.audit import retry_pagespeed

    cfg, con = _ctx()
    n = retry_pagespeed(con, cfg.google_api_key, lambda url, res: typer.echo(f"  {res:<12} {url[:70]}"))
    typer.echo(f"Checked {n} sites. Run `leadscout score` again to update scores.")


@app.command()
def score():
    """Score every audited business and pick out the leads."""
    from leadscout.scoring import score_all

    cfg, con = _ctx()
    typer.echo("Scoring (checking email domains can receive mail)...")
    stats = score_all(con, cfg)
    typer.echo(f"Done: {stats}")


@app.command()
def run(category: str, area: str = typer.Option(None), bbox: str = typer.Option(None), pagespeed: bool = typer.Option(True)):
    """find + audit + score in one go."""
    find(category, area, bbox, 0.5)
    audit(pagespeed, None)
    score()


@app.command()
def pitch(
    templates: int = typer.Option(0, help="Draft this many pitches now with the free built-in templates."),
    prepare: int = typer.Option(0, help="Prepare this many leads for Claude Code (/pitch-today) to write."),
    import_: bool = typer.Option(False, "--import", help="Import pitches Claude Code wrote to data/pitch_results.json."),
):
    """Draft pitches for the best new leads (emailable leads first)."""
    from leadscout.pitch import jobs

    cfg, con = _ctx()
    if templates:
        typer.echo(f"Drafted {jobs.draft_with_templates(con, cfg, templates)} pitches from templates.")
    elif prepare:
        n = jobs.prepare_jobs(con, cfg, prepare)
        typer.echo(f"Prepared {n} leads in {jobs.jobs_path()}. Now run /pitch-today in Claude Code.")
    elif import_:
        n, rejected = jobs.import_results(con, cfg)
        typer.echo(f"Imported {n} pitches.")
        if rejected:
            typer.echo(f"Set aside {len(rejected)} that cite numbers LeadScout never measured (see {jobs.rejected_path()}):")
            for r in rejected:
                typer.echo(f"  {r['id']}: {', '.join(r['unmeasured_numbers'])}")
    else:
        raise typer.BadParameter("Use --templates N, --prepare N or --import.")


@app.command("gmail-login")
def gmail_login():
    """Connect your Gmail account (one time). See src/leadscout/mailer/gmail.py for the 4 setup steps."""
    from leadscout.mailer import gmail

    typer.echo(f"Logged in as {gmail.login()}.")


@app.command()
def send(dry_run: bool = typer.Option(False, help="Show what would be sent without sending."), once: bool = typer.Option(False, help="Send one email and stop.")):
    """Send approved pitches through Gmail, respecting warm-up caps and the IST sending window."""
    from leadscout.mailer import sender

    cfg, con = _ctx()
    gm = None
    if not dry_run:
        from leadscout.mailer.gmail import Gmail

        gm = Gmail()
    sender.run(con, cfg, gm, dry_run=dry_run, once=once, log=typer.echo)


@app.command("check-replies")
def check_replies():
    """Check Gmail for replies, opt-outs and bounces."""
    from leadscout.mailer import sender
    from leadscout.mailer.gmail import Gmail

    cfg, con = _ctx()
    typer.echo(sender.check_replies(con, cfg, Gmail()))


@app.command()
def optout(value: str):
    """Never contact this email or phone again."""
    from leadscout.compliance import opt_out

    _, con = _ctx()
    n = opt_out(con, value, "manual")
    typer.echo(f"Added to the opt-out list ({n} lead(s) marked opted out).")


@app.command()
def forget(value: str):
    """Delete everything stored about this email or phone (DPDP deletion request)."""
    from leadscout.compliance import forget as do_forget

    _, con = _ctx()
    typer.echo(f"Deleted {do_forget(con, value)} business record(s). Kept a hashed opt-out entry so they're never contacted again.")


@app.command()
def purge():
    """Delete businesses you never contacted whose data is older than the retention limit."""
    from leadscout.compliance import purge_stale

    cfg, con = _ctx()
    typer.echo(f"Purged {purge_stale(con, cfg.retention['purge_uncontacted_after_days'])} stale records.")


@app.command()
def export(path: str = typer.Argument("leads.csv"), min_score: int = typer.Option(0)):
    """Export leads to CSV (opens in Google Sheets or Excel). Opted-out, bounced and hidden leads are left out."""
    from leadscout.compliance import is_suppressed

    _, con = _ctx()
    rows = con.execute(
        """select b.name, b.category, b.locality, b.phone, b.phone_type, l.email, b.website, a.site_class,
                  a.perf_score, a.lcp_s, l.score, l.status, l.reasons
           from leads l join businesses b on b.id = l.business_id join audits a on a.business_id = b.id
           where l.score >= ? and l.status not in ('excluded', 'opted_out', 'bounced', 'hidden') order by l.score desc""",
        (min_score,),
    ).fetchall()
    # Status can lag behind the opt-out list (e.g. the same phone on another listing), so check the list itself.
    rows = [r for r in rows if not is_suppressed(con, r["email"], r["phone"])]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(rows[0].keys() if rows else ["name"])
        w.writerows([tuple(r) for r in rows])
    typer.echo(f"Wrote {len(rows)} leads to {path}.")


@app.command()
def stats():
    """Pipeline counts."""
    from leadscout.mailer.sender import daily_cap, sent_today

    cfg, con = _ctx()
    q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    typer.echo(f"Businesses: {q('select count(*) from businesses')}")
    typer.echo(f"Audited:    {q('select count(*) from audits')}")
    for r in con.execute("select status, count(*) n from leads group by status order by n desc"):
        typer.echo(f"  {r['status']:<10} {r['n']}")
    typer.echo(f"Emails today: {sent_today(con)}/{daily_cap(con, cfg)}")


@app.command()
def shortcut():
    """Put a LeadScout icon on your desktop that opens the dashboard. Run again after moving or renaming the folder."""
    from leadscout import launch

    typer.echo(f"Created {launch.make_shortcut()}. Double-click it to open the dashboard.")


@app.command()
def stop():
    """Stop the dashboard that the desktop icon started."""
    from leadscout import launch

    typer.echo("Dashboard stopped." if launch.stop() else "The desktop dashboard isn't running.")


@app.command()
def serve(port: int = 8000):
    """Open the dashboard at http://127.0.0.1:8000"""
    import uvicorn

    typer.echo(f"Dashboard: http://127.0.0.1:{port}")
    uvicorn.run("leadscout.web.app:app", host="127.0.0.1", port=port)


if __name__ == "__main__":
    app()
