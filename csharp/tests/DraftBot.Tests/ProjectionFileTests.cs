using DraftBot.Core;

namespace DraftBot.Tests;

public class ProjectionFileTests
{
    [Fact]
    public void Parses_header_players_and_nulls()
    {
        var file = ProjectionFile.Parse(TestData.ProjectionJson());

        Assert.Equal(2024, file.Season);
        Assert.Equal("fantasypros", file.AdpSource);
        Assert.Equal(58.86, file.PositionRmse[Position.RB]);
        Assert.Equal(2, file.Players.Count);

        var first = file.Players[0];
        Assert.Equal(("00-1", Position.RB, "SF"), (first.PlayerId, first.Position, first.Team));
        Assert.Equal(229.12, first.ProjectedPpr);
        Assert.Equal(-1, first.GamesDelta);
        Assert.Equal(47.8, first.ActualPpr);

        var market = file.Players[1];
        Assert.Null(market.Adp);
        Assert.Null(market.ActualPpr);
        Assert.True(market.InjuryFlag && market.MarketEstimate);
    }

    [Fact]
    public void Rejects_an_unknown_schema_version()
    {
        var error = Assert.Throws<InvalidDataException>(() => ProjectionFile.Parse(TestData.ProjectionJson(schema: "v2")));
        Assert.Contains("v2", error.Message);
    }

    [Fact]
    public void Rejects_missing_position_rmse()
    {
        var error = Assert.Throws<InvalidDataException>(() =>
            ProjectionFile.Parse(TestData.ProjectionJson(rmse: """{"QB":84.28,"RB":58.86}""")));
        Assert.Contains("WR", error.Message);
    }

    [Fact]
    public void Loads_a_file_from_disk()
    {
        var path = Path.GetTempFileName();
        try
        {
            File.WriteAllText(path, TestData.ProjectionJson());
            Assert.Equal(2, ProjectionFile.Load(path).Players.Count);
        }
        finally { File.Delete(path); }
    }

    [Fact]
    public void Optional_role_context_fields_load_when_present_and_are_null_when_absent()
    {
        var json = TestData.ProjectionJson().Replace("\"actual_ppr\": null}", "\"actual_ppr\": null, \"absence_share_prev\": 0.81, \"team_changed\": true, \"rookie_r1_teammate\": null}");

        var players = ProjectionFile.Parse(json).Players;

        Assert.Equal(0.81, players[1].AbsenceSharePrev);
        Assert.True(players[1].TeamChanged);
        Assert.Null(players[1].RookieR1Teammate);
        Assert.Null(players[0].AbsenceSharePrev);          // files written before the fields existed still load
        Assert.Null(players[0].TeamChanged);
    }
}
