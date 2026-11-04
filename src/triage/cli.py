from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from triage.config import Settings
from triage.factory import make_agent
from triage.models import Lead

app = typer.Typer(help="Qualify, score and route inbound leads.", no_args_is_help=True)
console = Console()


@app.command()
def run(
    lead_file: Path = typer.Argument(..., exists=True, help="JSON file with one lead or a list of leads"),
    json_out: bool = typer.Option(False, "--json"),
    record: bool = typer.Option(False, help="Append decisions to the audit log"),
) -> None:
    """Triage one or many leads from a JSON file."""
    agent, audit, _ = make_agent(Settings())
    data = json.loads(lead_file.read_text(encoding="utf-8"))
    leads = [Lead.model_validate(x) for x in (data if isinstance(data, list) else [data])]
    decisions = [agent.decide(lead) for lead in leads]
    if record:
        for lead, d in zip(leads, decisions, strict=True):
            audit.record(lead, d)
    if json_out:
        typer.echo(json.dumps([d.model_dump(mode="json") for d in decisions], ensure_ascii=False, indent=2))
        return
    for lead, d in zip(leads, decisions, strict=True):
        color = {"escalate": "red", "auto_reply": "green", "assign": "cyan", "discard": "dim"}[d.action]
        console.print(
            f"[bold]{lead.name or lead.email or d.lead_id}[/] → [{color}]{d.action}[/]"
            f" · team [bold]{d.route.team}[/]"
            f" · SLA {d.route.sla_hours}h · score {d.score.total} ({d.score.tier})"
            + (" · [yellow]needs human[/]" if d.needs_human else "")
        )
        console.print(f"   {d.extraction.summary}")
        for f in d.score.factors:
            console.print(f"   [dim]{f.points:+4d}  {f.name}: {f.why}[/]")
        for r in d.reasons:
            console.print(f"   [dim]• {r}[/]")
        if d.reply_draft:
            console.print(f"   [green]draft:[/] {d.reply_draft[:160]}")
        console.print()


@app.command(name="eval")
def eval_cmd(
    cases: Path = typer.Argument(..., exists=True),
    min_pass_rate: float = typer.Option(0.0, help="Exit 1 below this pass rate"),
) -> None:
    """Replay labelled leads and report routing / action / escalation accuracy."""
    from triage.evaluate import evaluate, load_cases

    agent, _, _ = make_agent(Settings())
    report = evaluate(agent, load_cases(cases))
    s = report.summary()
    table = Table(title=f"Eval — {int(s['cases'])} cases")
    table.add_column("metric")
    table.add_column("value", justify="right")
    for k, v in s.items():
        table.add_row(k, f"{v:.0f}" if k == "cases" else f"{v:.0%}")
    console.print(table)
    for r in report.results:
        mark = "[green]✓[/]" if r.ok else "[red]✗[/]"
        label = r.case.note or (r.case.lead.message[:70] + "…")
        console.print(f"{mark} {label}" + ("" if r.ok else f"\n   [red]{'; '.join(r.failures)}[/]"))
    if s["pass_rate"] < min_pass_rate:
        raise typer.Exit(code=1)


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Start the webhook API."""
    import uvicorn

    uvicorn.run("triage.api:app", host=host, port=port)


if __name__ == "__main__":
    app()
