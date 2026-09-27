"""Visualizations and tabular reporting for airline route economics."""

from pathlib import Path
from typing import Optional
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for headless rendering
import matplotlib.pyplot as plt
import pandas as pd
from tabulate import tabulate


class EconomicsVisualizer:
    """Renders charts and terminal tables for route economics analysis."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or Path("reports")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def format_table(self, df: pd.DataFrame, headers: Optional[list] = None) -> str:
        """Formats DataFrame as a clean ASCII/Markdown table."""
        if df.empty:
            return "No data found for given criteria."
        return tabulate(df, headers=headers or "keys", tablefmt="fancy_grid", showindex=False)

    def plot_price_vs_true_cost_bar(self, df: pd.DataFrame, title: str = "Ticket Price vs True Cost Per Seat", filename: str = "true_cost_bar.png") -> Path:
        """Renders stacked/grouped bar chart of Ticket Price + Passenger Delay Cost = True Cost."""
        if df.empty:
            raise ValueError("Cannot plot empty DataFrame")

        fig, ax = plt.subplots(figsize=(10, 6))

        # Sort by true cost
        plot_df = df.sort_values(by="true_cost_per_seat", ascending=False).head(15).copy()
        
        # Label could be carrier or carrier+route
        if "origin" in plot_df.columns and "dest" in plot_df.columns:
            labels = plot_df["carrier"] + " (" + plot_df["origin"] + "-" + plot_df["dest"] + ")"
        else:
            labels = plot_df["carrier"] + " - " + plot_df["carrier_name"]

        base_prices = plot_df["avg_ticket_price"]
        delay_costs = plot_df["passenger_delay_cost_per_seat"]

        # Stacked bar
        ax.bar(labels, base_prices, label="Base Ticket Price ($)", color="#1f77b4", alpha=0.85)
        ax.bar(labels, delay_costs, bottom=base_prices, label="Allocated Passenger Delay Cost ($)", color="#ff7f0e", alpha=0.85)

        ax.set_ylabel("Cost ($ USD)", fontsize=12)
        ax.set_title(title, fontsize=14, fontweight="bold")
        ax.legend(loc="upper right")
        plt.xticks(rotation=45, ha="right", fontsize=10)
        plt.tight_layout()

        out_path = self.output_dir / filename
        plt.savefig(out_path, dpi=300)
        plt.close()
        return out_path

    def plot_scatter_load_vs_delay(self, df: pd.DataFrame, title: str = "Load Factor vs. Delay Minutes vs. Price", filename: str = "load_vs_delay_scatter.png") -> Path:
        """Renders scatter plot of Load Factor vs Average Delay with ticket price encoded by bubble size."""
        if df.empty:
            raise ValueError("Cannot plot empty DataFrame")

        fig, ax = plt.subplots(figsize=(10, 6))
        plot_df = df.copy()

        x = plot_df["avg_load_factor"] * 100.0  # percentage
        y = plot_df["avg_arr_delay_min"]
        sizes = plot_df["avg_ticket_price"].clip(lower=50.0) * 0.7

        scatter = ax.scatter(x, y, s=sizes, c=plot_df["true_cost_per_seat"], cmap="viridis", alpha=0.75, edgecolors="black", linewidth=1.2)
        cbar = plt.colorbar(scatter, ax=ax)
        cbar.set_label("Composite True Cost ($)", fontsize=11)

        for _, row in plot_df.iterrows():
            lbl = f"{row['carrier']}"
            if "origin" in row and "dest" in row:
                lbl += f" ({row['origin']}-{row['dest']})"
            ax.annotate(lbl, (row["avg_load_factor"] * 100.0, row["avg_arr_delay_min"]), fontsize=8, xytext=(4, 4), textcoords="offset points")

        ax.set_xlabel("Average Load Factor (%)", fontsize=12)
        ax.set_ylabel("Average Arrival Delay (Minutes)", fontsize=12)
        ax.set_title(title, fontsize=14, fontweight="bold")
        ax.grid(True, linestyle="--", alpha=0.5)
        plt.tight_layout()

        out_path = self.output_dir / filename
        plt.savefig(out_path, dpi=300)
        plt.close()
        return out_path
