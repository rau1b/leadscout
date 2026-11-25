"""`leadscout demo <business_id>`: build one concept page. Registered on the main app in leadscout/cli.py."""

import typer

from leadscout import config, db


def demo(business_id: str = typer.Argument(..., help="The business id, as shown on the lead page.")):
    """Build a concept page for one business in data/demos/<slug>/index.html (not hosted yet)."""
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
