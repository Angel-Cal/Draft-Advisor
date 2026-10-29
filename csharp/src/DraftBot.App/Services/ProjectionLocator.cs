namespace DraftBot.App.Services;

/// <summary>Finds the live projections file during development: the DRAFTBOT_PROJECTIONS variable, else data/processed/projections_2026_v1.json in a parent folder.</summary>
public static class ProjectionLocator
{
    const string FileName = "projections_2026_v1.json";

    public static string? Find()
    {
        var fromEnvironment = Environment.GetEnvironmentVariable("DRAFTBOT_PROJECTIONS");
        if (!string.IsNullOrWhiteSpace(fromEnvironment) && File.Exists(fromEnvironment)) return fromEnvironment;

        for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir is not null; dir = dir.Parent)
        {
            var candidate = Path.Combine(dir.FullName, "data", "processed", FileName);
            if (File.Exists(candidate)) return candidate;
        }
        return null;
    }
}
