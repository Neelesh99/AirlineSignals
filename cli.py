"""Command-Line Interface for Airline Route Economics Analyzer."""

from pathlib import Path
from typing import Optional
import click
import pandas as pd

from analysis.query_service import AnalysisQueryService
from analysis.visualizer import EconomicsVisualizer
from pipeline import RouteEconomicsPipeline


@click.group()
def cli():
    """Airline Route Economics Analyzer CLI."""
    pass


@cli.command("ingest")
@click.option("--stage", type=click.Choice(["all", "load_factors", "delays", "delay_costs", "pricing"]), default="all",
              help="Pipeline stage to run.")
@click.option("--provider", type=click.Choice(["zenodo", "trino"]), default="zenodo",
              help="Delay data provider for OpenSky.")
@click.option("--t100", type=click.Path(exists=True), default=None, help="Custom BTS T-100 CSV path.")
@click.option("--zenodo-csv", type=click.Path(exists=True), default=None, help="Custom Zenodo CSV path.")
def ingest_cmd(stage, provider, t100, zenodo_csv):
    """Run data ingestion and cost modeling pipelines."""
    pipeline = RouteEconomicsPipeline()
    click.echo(f"Running pipeline stage: {stage} (delay provider: {provider})...")
    
    if stage == "all":
        pipeline.run_full_pipeline(delay_provider=provider, t100_file=t100, zenodo_file=zenodo_csv)
    elif stage == "load_factors":
        pipeline.run_stage_load_factors(t100_file=t100)
    elif stage == "delays":
        pipeline.run_stage_delays(provider=provider, zenodo_file=zenodo_csv)
    elif stage == "delay_costs":
        pipeline.run_stage_delay_costs()
    elif stage == "pricing":
        pipeline.run_stage_pricing()

    click.echo("Ingestion finished successfully.")


@cli.command("analyze-airline")
@click.option("--carrier", "-c", help="Carrier code (e.g. AA, DL, UA, BA) or leave blank for all.")
@click.option("--quarter", "-q", help="Quarter filter (e.g. 2024Q3).")
@click.option("--csv", "export_csv", type=click.Path(), help="Export output to CSV file path.")
@click.option("--plot/--no-plot", default=False, help="Generate and save comparison charts.")
def analyze_airline_cmd(carrier, quarter, export_csv, plot):
    """Query economics at the airline level (single carrier or carrier comparison)."""
    service = AnalysisQueryService()
    vis = EconomicsVisualizer()

    df = service.query_by_airline(carrier_code=carrier, quarter=quarter)
    if df.empty:
        click.echo("No data found. Ensure pipeline ingestion has been executed.")
        return

    click.echo("\n=== AIRLINE-LEVEL ROUTE ECONOMICS SUMMARY ===")
    click.echo(vis.format_table(df))

    if export_csv:
        df.to_csv(export_csv, index=False)
        click.echo(f"Results exported to {export_csv}")

    if plot:
        bar_path = vis.plot_price_vs_true_cost_bar(df, title="Carrier Comparison: Base Price vs True Cost", filename="airline_true_cost.png")
        click.echo(f"Saved visualization to {bar_path}")


@cli.command("analyze-sector")
@click.option("--sector", "-s", help="Sector name (e.g. 'US Domestic Transcon', 'Transatlantic', 'Intra-Europe').")
@click.option("--quarter", "-q", help="Quarter filter.")
@click.option("--csv", "export_csv", type=click.Path(), help="Export output to CSV file path.")
@click.option("--plot/--no-plot", default=False, help="Generate and save comparison charts.")
def analyze_sector_cmd(sector, quarter, export_csv, plot):
    """Query economics aggregated by sector."""
    service = AnalysisQueryService()
    vis = EconomicsVisualizer()

    df = service.query_by_sector(sector_name=sector, quarter=quarter)
    if df.empty:
        click.echo("No data found for sector.")
        return

    click.echo(f"\n=== SECTOR ECONOMICS SUMMARY ({sector or 'All Sectors'}) ===")
    click.echo(vis.format_table(df))

    if export_csv:
        df.to_csv(export_csv, index=False)
        click.echo(f"Results exported to {export_csv}")

    if plot:
        bar_path = vis.plot_price_vs_true_cost_bar(df, title=f"Sector: {sector or 'All'} - Price vs True Cost", filename="sector_true_cost.png")
        click.echo(f"Saved visualization to {bar_path}")


@cli.command("analyze-route")
@click.argument("origin")
@click.argument("dest")
@click.option("--quarter", "-q", help="Quarter filter.")
@click.option("--csv", "export_csv", type=click.Path(), help="Export output to CSV file path.")
@click.option("--plot/--no-plot", default=False, help="Generate and save comparison charts.")
def analyze_route_cmd(origin, dest, quarter, export_csv, plot):
    """Query economics for a specific origin-destination airport pair across airlines."""
    service = AnalysisQueryService()
    vis = EconomicsVisualizer()

    df = service.query_by_od_pair(origin=origin, dest=dest, quarter=quarter)
    if df.empty:
        click.echo(f"No data found for route {origin.upper()}-{dest.upper()}.")
        return

    click.echo(f"\n=== ROUTE ECONOMICS: {origin.upper()} -> {dest.upper()} ===")
    click.echo(vis.format_table(df))

    if export_csv:
        df.to_csv(export_csv, index=False)
        click.echo(f"Results exported to {export_csv}")

    if plot:
        bar_path = vis.plot_price_vs_true_cost_bar(
            df,
            title=f"Route {origin.upper()}-{dest.upper()}: Carrier Ticket Price vs True Cost",
            filename=f"route_{origin.lower()}_{dest.lower()}_cost.png"
        )
        scatter_path = vis.plot_scatter_load_vs_delay(
            df,
            title=f"Route {origin.upper()}-{dest.upper()}: Load Factor vs Arrival Delay",
            filename=f"route_{origin.lower()}_{dest.lower()}_scatter.png"
        )
        click.echo(f"Saved visualizations to {bar_path} and {scatter_path}")


@cli.command("demo")
def demo_cmd():
    """Runs a complete end-to-end demo seeding all sources and executing queries across all 3 granularities."""
    click.echo("=====================================================================")
    click.echo("       AIRLINE ROUTE ECONOMICS ANALYZER — END-TO-END DEMO            ")
    click.echo("=====================================================================\n")

    pipeline = RouteEconomicsPipeline()
    pipeline.run_full_pipeline(delay_provider="zenodo")

    service = AnalysisQueryService()
    vis = EconomicsVisualizer()

    click.echo("\n>>> 1. AIRLINE-LEVEL ANALYSIS (Carrier Network Comparison):")
    df_carrier = service.query_by_airline()
    click.echo(vis.format_table(df_carrier))

    click.echo("\n>>> 2. SECTOR-LEVEL ANALYSIS (Transatlantic Corridor):")
    df_sector = service.query_by_sector(sector_name="Transatlantic")
    click.echo(vis.format_table(df_sector))

    click.echo("\n>>> 3. ORIGIN-DESTINATION PAIR ANALYSIS (JFK -> LAX Transcon):")
    df_route = service.query_by_od_pair(origin="JFK", dest="LAX")
    click.echo(vis.format_table(df_route))

    # Generate sample charts
    b_path = vis.plot_price_vs_true_cost_bar(df_carrier, title="Carrier Comparison: Ticket Price vs True Cost Per Seat", filename="demo_carrier_bar.png")
    s_path = vis.plot_scatter_load_vs_delay(df_carrier, title="Carrier Fleet: Load Factor vs Delay vs True Cost", filename="demo_carrier_scatter.png")
    click.echo(f"\nGenerated demo charts in {b_path.parent}/: [demo_carrier_bar.png, demo_carrier_scatter.png]")
    click.echo("\nDemo completed successfully!")


if __name__ == "__main__":
    cli()
