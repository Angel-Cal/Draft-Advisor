"""Command-line interface for the Fantasy Football Draft Bot."""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.data.scraper import NFLDataScraper
from src.data.pipeline import DataPipeline
from src.features.build_features import FeatureBuilder
from src.models.train import ModelTrainer
from src.models.predict import PlayerPredictor
from src.draft.vbd import ValueBasedDrafter
from src.draft.recommender import DraftRecommender

console = Console()


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Fantasy Football Draft Bot - ML-powered draft assistant."""
    pass


@cli.command()
@click.option("--seasons", "-s", multiple=True, type=int, default=[2023, 2024],
              help="Seasons to scrape data for")
def collect(seasons):
    """Collect NFL fantasy data from web sources."""
    console.print(Panel("Collecting NFL Fantasy Data", style="bold blue"))

    scraper = NFLDataScraper()
    seasons_list = list(seasons)

    console.print(f"Scraping seasons: {seasons_list}")

    with console.status("Scraping data..."):
        data = scraper.scrape_multiple_seasons(seasons_list, save=True)

    if not data.empty:
        console.print(f"[green]Successfully collected {len(data)} player records[/green]")
    else:
        console.print("[red]No data collected. Check your internet connection.[/red]")


@cli.command()
def process():
    """Process raw data through the pipeline."""
    console.print(Panel("Processing Data", style="bold blue"))

    pipeline = DataPipeline()

    try:
        with console.status("Running pipeline..."):
            data = pipeline.run_pipeline()
        console.print(f"[green]Processed {len(data)} records[/green]")
    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("Run 'draftbot collect' first to gather raw data.")


@cli.command()
@click.option("--test-season", "-t", type=int, default=2024,
              help="Season to use for testing")
def train(test_season):
    """Train player projection models."""
    console.print(Panel("Training Models", style="bold blue"))

    # Load processed data
    pipeline = DataPipeline()
    try:
        data = pipeline.load_raw_data("fantasy_stats_processed.csv")
    except FileNotFoundError:
        console.print("[red]Processed data not found. Run 'draftbot process' first.[/red]")
        return

    # Build features
    feature_builder = FeatureBuilder()
    data = feature_builder.build_all_features(data)

    # Train models
    trainer = ModelTrainer()

    with console.status("Training models..."):
        X_train, X_test, y_train, y_test = trainer.train_test_split_by_season(
            data, test_season=test_season
        )
        results = trainer.train_and_evaluate(X_train, X_test, y_train, y_test)

    # Display results
    table = Table(title="Model Performance")
    table.add_column("Model", style="cyan")
    table.add_column("MAE", justify="right")
    table.add_column("RMSE", justify="right")
    table.add_column("R²", justify="right")

    for model_name, metrics in results.items():
        table.add_row(
            model_name,
            f"{metrics['mae']:.2f}",
            f"{metrics['rmse']:.2f}",
            f"{metrics['r2']:.3f}"
        )

    console.print(table)

    # Save best model
    trainer.save_model()
    console.print(f"[green]Saved best model: {trainer.best_model_name}[/green]")


@cli.command()
@click.option("--top", "-n", type=int, default=20, help="Number of players to show")
@click.option("--position", "-p", type=str, default=None, help="Filter by position")
def rankings(top, position):
    """Display player rankings based on projections."""
    console.print(Panel("Player Rankings", style="bold blue"))

    # Load data and model
    pipeline = DataPipeline()
    try:
        data = pipeline.load_raw_data("fantasy_stats_processed.csv")
    except FileNotFoundError:
        console.print("[red]Processed data not found. Run 'draftbot process' first.[/red]")
        return

    # Build features
    feature_builder = FeatureBuilder()
    data = feature_builder.build_all_features(data)

    # Load model and predict
    predictor = PlayerPredictor()
    try:
        predictor.load_model()
    except FileNotFoundError:
        console.print("[red]No trained model found. Run 'draftbot train' first.[/red]")
        return

    projections = predictor.generate_projections(data)

    # Apply VBD
    vbd = ValueBasedDrafter()
    projections = vbd.calculate_vbd(projections)

    # Filter by position if specified
    if position:
        projections = projections[projections["position"] == position.upper()]

    # Display top players
    table = Table(title=f"Top {top} Players" + (f" - {position.upper()}" if position else ""))
    table.add_column("Rank", justify="right", style="cyan")
    table.add_column("Player", style="white")
    table.add_column("Pos", justify="center")
    table.add_column("Projected", justify="right", style="green")
    table.add_column("VOR", justify="right", style="yellow")
    table.add_column("VBD Rank", justify="right")

    for _, row in projections.head(top).iterrows():
        table.add_row(
            str(int(row.get("position_rank", row.get("rank", 0)))),
            row["player"],
            row["position"],
            f"{row['projected_points']:.1f}",
            f"{row['vor']:.1f}",
            str(int(row["vbd_rank"]))
        )

    console.print(table)


@cli.command()
@click.option("--pick", "-p", type=int, required=True, help="Your draft position (1-12)")
@click.option("--teams", "-t", type=int, default=12, help="Number of teams")
def draft(pick, teams):
    """Start interactive draft assistant."""
    console.print(Panel(f"Draft Assistant - Pick #{pick} of {teams} teams", style="bold green"))

    # Load projections
    pipeline = DataPipeline()
    try:
        data = pipeline.load_raw_data("fantasy_stats_processed.csv")
    except FileNotFoundError:
        console.print("[red]Data not found. Run 'draftbot collect' and 'draftbot process' first.[/red]")
        return

    # Build features and predictions
    feature_builder = FeatureBuilder()
    data = feature_builder.build_all_features(data)

    predictor = PlayerPredictor()
    try:
        predictor.load_model()
        projections = predictor.generate_projections(data)
    except FileNotFoundError:
        console.print("[yellow]No model found. Using raw projections.[/yellow]")
        projections = data[["player", "position", "fantasy_points"]].copy()
        projections.columns = ["player", "position", "projected_points"]

    # Initialize VBD and recommender
    vbd = ValueBasedDrafter(team_count=teams)
    projections = vbd.calculate_vbd(projections)

    recommender = DraftRecommender()

    # Track draft state
    roster = {"QB": [], "RB": [], "WR": [], "TE": [], "K": [], "DST": []}
    available = projections.copy()
    current_round = 1
    total_picks = teams * 15

    console.print("\n[bold]Commands:[/bold] 'pick <player>', 'recommend', 'roster', 'quit'\n")

    while True:
        # Calculate current overall pick
        if current_round % 2 == 1:  # Odd round
            overall_pick = (current_round - 1) * teams + pick
        else:  # Even round (snake)
            overall_pick = (current_round - 1) * teams + (teams - pick + 1)

        console.print(f"\n[bold cyan]Round {current_round} - Overall Pick #{overall_pick}[/bold cyan]")

        # Show recommendations
        recommendations = recommender.get_recommendations(
            available, roster, overall_pick, total_picks
        )

        table = Table(title="Top Recommendations")
        table.add_column("#", justify="right")
        table.add_column("Player")
        table.add_column("Pos")
        table.add_column("Pts", justify="right")
        table.add_column("VOR", justify="right")
        table.add_column("Reason")

        for i, rec in enumerate(recommendations, 1):
            table.add_row(
                str(i),
                rec.player,
                rec.position,
                f"{rec.projected_points:.1f}",
                f"{rec.vor:.1f}",
                rec.reasoning
            )

        console.print(table)

        # Get user input
        user_input = console.input("\n[bold]Your pick:[/bold] ").strip().lower()

        if user_input == "quit":
            break
        elif user_input == "roster":
            console.print(Panel(str(roster), title="Your Roster"))
            continue
        elif user_input == "recommend":
            continue
        elif user_input.startswith("pick "):
            player_name = user_input[5:].strip()

            # Find matching player
            matches = available[available["player"].str.lower().str.contains(player_name)]

            if len(matches) == 0:
                console.print(f"[red]Player '{player_name}' not found[/red]")
                continue
            elif len(matches) > 1:
                console.print(f"[yellow]Multiple matches: {matches['player'].tolist()}[/yellow]")
                continue

            picked = matches.iloc[0]
            roster[picked["position"]].append(picked["player"])
            available = available[available["player"] != picked["player"]]

            console.print(f"[green]Drafted: {picked['player']} ({picked['position']})[/green]")
            current_round += 1

            if current_round > 15:
                console.print("\n[bold green]Draft complete![/bold green]")
                console.print(Panel(str(roster), title="Final Roster"))
                break
        else:
            console.print("[yellow]Unknown command. Use 'pick <player>', 'recommend', 'roster', or 'quit'[/yellow]")


@cli.command()
def info():
    """Display project information and setup status."""
    console.print(Panel("Fantasy Football Draft Bot", style="bold blue"))

    # Check data status
    raw_data = Path(__file__).parent.parent.parent / "data" / "raw" / "fantasy_stats_combined.csv"
    processed_data = Path(__file__).parent.parent.parent / "data" / "processed" / "fantasy_stats_processed.csv"
    model_dir = Path(__file__).parent.parent.parent / "models"

    table = Table(title="Setup Status")
    table.add_column("Component", style="cyan")
    table.add_column("Status", justify="center")

    table.add_row(
        "Raw Data",
        "[green]✓[/green]" if raw_data.exists() else "[red]✗[/red] Run 'draftbot collect'"
    )
    table.add_row(
        "Processed Data",
        "[green]✓[/green]" if processed_data.exists() else "[red]✗[/red] Run 'draftbot process'"
    )

    model_exists = any(model_dir.glob("*.joblib"))
    table.add_row(
        "Trained Model",
        "[green]✓[/green]" if model_exists else "[red]✗[/red] Run 'draftbot train'"
    )

    console.print(table)

    console.print("\n[bold]Available Commands:[/bold]")
    console.print("  collect  - Scrape NFL fantasy data")
    console.print("  process  - Process raw data")
    console.print("  train    - Train projection models")
    console.print("  rankings - View player rankings")
    console.print("  draft    - Start draft assistant")


if __name__ == "__main__":
    cli()
