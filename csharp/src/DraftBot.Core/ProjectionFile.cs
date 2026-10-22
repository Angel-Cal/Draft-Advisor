using System.Text.Json;
using System.Text.Json.Serialization;

namespace DraftBot.Core;

public sealed record ProjectionFile(
    string SchemaVersion,
    string Kind,
    int Season,
    string AdpSource,
    Dictionary<Position, double> PositionRmse,
    List<Player> Players)
{
    public const string SupportedSchema = "v1";

    static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        Converters = { new JsonStringEnumConverter() },
    };

    public static ProjectionFile Load(string path) => Parse(File.ReadAllText(path));

    public static ProjectionFile Parse(string json)
    {
        var file = JsonSerializer.Deserialize<ProjectionFile>(json, Options)
                   ?? throw new InvalidDataException("projection file is empty");
        if (file.SchemaVersion != SupportedSchema)
            throw new InvalidDataException($"unsupported schema_version '{file.SchemaVersion}' (this build reads '{SupportedSchema}')");
        if (file.Players is null || file.Players.Count == 0)
            throw new InvalidDataException("projection file has no players");
        var missing = Positions.All.Where(p => file.PositionRmse is null || !file.PositionRmse.ContainsKey(p)).ToList();
        if (missing.Count > 0)
            throw new InvalidDataException($"position_rmse is missing {string.Join(", ", missing)}");
        return file;
    }
}
