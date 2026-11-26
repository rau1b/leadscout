"""`leadscout demo <business_id>` builds one concept page; `leadscout demos publish|sync|secret` run the preview host.
Both are registered on the main app in leadscout/cli.py."""

import typer

from leadscout import config, db


def demo(business_id: str = typer.Argument(..., help="The business id, as shown on the lead page.")):
    """Build a concept page for one business in data/demos/<slug>/index.html. `leadscout demos publish` puts it online."""
    from leadscout import demos

    cfg = config.load()
    problem = config.sender_problem(cfg)
    if problem:  # the banner and enquiry section would say "Your Studio"
        typer.echo(problem, err=True)
        raise typer.Exit(1)
    con = db.connect()
    demos.remove_orphans(con)
    try:
        d = demos.build(con, business_id, cfg.sender)
    except demos.Refused as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Built a {d.template} demo, expires {d.expires_at[:10]}:")
    typer.echo(str(d.path))


demos_app = typer.Typer(help="The preview host: publish demo pages and sync views and unsubscribes back.", no_args_is_help=True)


@demos_app.command()
def publish():
    """Deploy every live demo to the preview host; expired and forgotten ones come down."""
    from leadscout.demos import preview

    try:
        n = preview.publish(db.connect(), config.load())
    except preview.PreviewError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Published: {n['live']} demo(s) online ({n['published']} new), {n['expired']} expired and taken down, "
               f"{n['blocked']} left out because the business opted out.")


@demos_app.command()
def sync():
    """Pull views and unsubscribes from the preview host."""
    from leadscout.demos import preview

    try:
        n = preview.sync(db.connect(), config.load())
    except preview.PreviewError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Synced: {n['views']} view(s), {n['opted_out']} unsubscribe(s) applied"
               + (f", {n['queued']} waiting for the unsubscribe code (contract C4)" if n["queued"] else "") + ".")


@demos_app.command()
def secret():
    """Print a new random sync secret to put in .env as PREVIEW_SYNC_SECRET."""
    from leadscout.demos import preview

    typer.echo(preview.new_secret())
