"""Command-line interface for AutoNovelClaw.

Usage:
    novelclaw run --topic "Your story idea" --auto-approve
    novelclaw run --config config.novelclaw.yaml
    novelclaw status --run-dir artifacts/nc-20260317-...
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler

console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_time=False, show_path=False)],
    )


@click.group()
@click.version_option(package_name="autonovelclaw")
def main() -> None:
    """AutoNovelClaw — From Idea to Published Novel, Fully Autonomous."""


@main.command()
@click.option("--topic", "-t", default="", help="Your story idea (any length, any specificity).")
@click.option("--config", "-c", "config_path", default=None, help="Path to config YAML.")
@click.option("--auto-approve", is_flag=True, help="Skip all human gates (fully autonomous).")
@click.option("--verbose", "-v", is_flag=True, help="Verbose logging.")
def run(topic: str, config_path: str | None, auto_approve: bool, verbose: bool) -> None:
    """Run the full novel-creation pipeline."""
    _setup_logging(verbose)

    from autonovelclaw.config import load_config
    from autonovelclaw.pipeline.runner import PipelineRunner

    config = load_config(config_path)

    if not topic and not config.novel.title:
        # Interactive mode: ask for the idea
        console.print("\n[bold cyan]╔══════════════════════════════════════════╗[/]")
        console.print("[bold cyan]║        AutoNovelClaw v0.1.0              ║[/]")
        console.print("[bold cyan]║  From Idea to Published Novel            ║[/]")
        console.print("[bold cyan]╚══════════════════════════════════════════╝[/]\n")
        console.print("[yellow]What's your story idea? (Be as vague or specific as you like)[/]\n")
        topic = input("  > ").strip()
        if not topic:
            console.print("[red]No idea provided. Exiting.[/]")
            sys.exit(1)

    runner = PipelineRunner(config, auto_approve=auto_approve, topic=topic)

    try:
        deliverables = runner.run()
        console.print(f"\n[bold green]🎉 Done! Your novel is at: {deliverables}[/]\n")
    except KeyboardInterrupt:
        console.print("\n[yellow]Pipeline paused. Resume with the same command.[/]")
        sys.exit(0)
    except Exception as exc:
        console.print(f"\n[bold red]Pipeline failed: {exc}[/]")
        logging.getLogger(__name__).exception("Pipeline error")
        sys.exit(1)


@main.command()
@click.option("--run-dir", "-d", required=True, help="Path to the artifact directory.")
def status(run_dir: str) -> None:
    """Show the status of a pipeline run."""
    _setup_logging(False)

    import json
    state_path = Path(run_dir) / "pipeline_state.json"
    if not state_path.exists():
        console.print(f"[red]No pipeline state found at {state_path}[/]")
        return

    data = json.loads(state_path.read_text())

    console.print(f"\n[bold cyan]Pipeline Status: {run_dir}[/]\n")
    console.print(f"  Started: {data.get('started_at', 'N/A')}")
    console.print(f"  Updated: {data.get('updated_at', 'N/A')}")
    console.print(f"  Current stage: {data.get('current_stage', 'N/A')}")
    console.print(f"  Current chapter: {data.get('current_chapter', 0)}/{data.get('total_chapters', 0)}")

    stages = data.get("stages", {})
    completed = sum(1 for v in stages.values() if v == "completed")
    failed = sum(1 for v in stages.values() if v == "failed")

    console.print(f"\n  Stages: {completed} completed, {failed} failed, {len(stages)} total")

    decisions = data.get("decisions", [])
    if decisions:
        console.print(f"\n  [bold]Decisions:[/]")
        for d in decisions[-5:]:
            console.print(f"    {d['stage']}: {d['decision']} — {d['rationale'][:80]}")


@main.command()
def init() -> None:
    """Create a default configuration file."""
    _setup_logging(False)

    config_path = Path("config.novelclaw.yaml")
    if config_path.exists():
        console.print(f"[yellow]{config_path} already exists. Skipping.[/]")
        return

    import importlib.resources
    example = Path(__file__).parent.parent / "configs" / "config.novelclaw.example.yaml"
    if example.exists():
        config_path.write_text(example.read_text())
    else:
        from autonovelclaw.config import NovelClawConfig
        import yaml
        config = NovelClawConfig()
        config_path.write_text(yaml.dump(config.model_dump(), default_flow_style=False, sort_keys=False))

    console.print(f"[green]Created {config_path}[/]")
    console.print("[yellow]Edit it with your API key and preferences, then run:[/]")
    console.print('  [cyan]novelclaw run --topic "Your story idea"[/]')


@main.command()
@click.option("--config", "-c", "config_path", default=None, help="Path to config YAML.")
def doctor(config_path: str | None) -> None:
    """Run pre-flight health checks."""
    _setup_logging(False)

    from autonovelclaw.config import load_config
    from autonovelclaw.health import run_doctor

    config = load_config(config_path)
    report = run_doctor(config)

    console.print(report.to_markdown())

    if report.actionable_fixes:
        console.print("\n[bold yellow]Fixes needed:[/]")
        for fix in report.actionable_fixes:
            console.print(f"  → {fix}")

    if report.overall == "fail":
        console.print("\n[bold red]Health check FAILED — fix issues before running.[/]")
        sys.exit(1)
    elif report.overall == "warn":
        console.print("\n[yellow]Warnings present — pipeline may still work.[/]")
    else:
        console.print("\n[bold green]All checks passed! Ready to run.[/]")


if __name__ == "__main__":
    main()
