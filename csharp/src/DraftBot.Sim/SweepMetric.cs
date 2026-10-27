namespace DraftBot.Sim;

/// <summary>What a parameter sweep optimizes: mean starter points, or head-to-head season odds (see <see cref="LeagueSeason"/>).</summary>
public enum SweepMetric { Points, Wins, Playoffs, Title }

public static class SweepMetrics
{
    /// <summary>The run's value for the metric. Odds are in percentage points so a difference of 1 means one point of probability.</summary>
    public static Func<RunRow, double> Selector(this SweepMetric metric) => metric switch
    {
        SweepMetric.Points => r => r.Points,
        SweepMetric.Wins => r => 100 * r.WinPct,
        SweepMetric.Playoffs => r => 100 * r.Playoff,
        SweepMetric.Title => r => 100 * r.Title,
        _ => throw new ArgumentOutOfRangeException(nameof(metric)),
    };

    public static string Label(this SweepMetric metric) => metric switch
    {
        SweepMetric.Points => "mean starter points",
        SweepMetric.Wins => "win % (percentage points)",
        SweepMetric.Playoffs => "playoff odds (percentage points)",
        SweepMetric.Title => "title odds (percentage points)",
        _ => throw new ArgumentOutOfRangeException(nameof(metric)),
    };

    /// <summary>Digits to show: points are whole numbers, odds need a decimal.</summary>
    public static string Format(this SweepMetric metric) => metric == SweepMetric.Points ? "F0" : "F1";

    public static SweepMetric Parse(string? text) => text is null ? SweepMetric.Points : Enum.Parse<SweepMetric>(text, ignoreCase: true);
}
