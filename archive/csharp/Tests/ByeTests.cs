using DraftBot.Core;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class ByeTests
{
    // 2 teams, 1 starter each at QB/RB/WR/TE and no FLEX, so a second RB is pure bench; replacement points: QB 200, RB 100, WR 100, TE 50
    static readonly LeagueSettings NoFlex = new(Teams: 2, Qb: 1, Rb: 1, Wr: 1, Te: 1, Flex: 0, Bench: 3);
    static readonly Dictionary<Position, double> Replacement = new()
        { [Position.QB] = 200, [Position.RB] = 100, [Position.WR] = 100, [Position.TE] = 50 };

    static IReadOnlyList<double?> Weekly(int? byeWeek) => Enumerable.Range(1, 18).Select(w => w == byeWeek ? (double?)null : 5.0).ToList();

    static ValuedPlayer V(string id, Position position, double projected, string team, int? byeWeek = null, double adp = 1) =>
        new(Player(id, position, projected, adp: adp) with { Team = team, WeeklyPpr = byeWeek is null ? null : Weekly(byeWeek) },
            projected - Replacement[position], 0, 0, false, 1, 0, 1, 50);

    [Fact]
    public void A_teams_bye_is_the_unique_week_in_the_window_with_the_fewest_scorers()
    {
        var players = new[]
        {
            Player("a1", Position.RB, 100) with { Team = "AAA", WeeklyPpr = Weekly(7) },
            Player("a2", Position.WR, 100) with { Team = "AAA", WeeklyPpr = Weekly(7) },
            Player("a3", Position.QB, 100) with { Team = "AAA", WeeklyPpr = Weekly(7) },
            Player("b1", Position.RB, 100) with { Team = "BBB", WeeklyPpr = Weekly(10) },
            Player("b2", Position.WR, 100) with { Team = "BBB", WeeklyPpr = Weekly(10) },
        };

        var schedule = ByeSchedule.Infer(players);

        Assert.Equal(7, schedule.WeekOf("AAA"));
        Assert.Null(schedule.WeekOf("BBB"));          // two players say too little
        Assert.Null(schedule.WeekOf("CCC"));
        Assert.Equal(1, schedule.Count);
    }

    [Fact]
    public void One_stray_scorer_in_the_bye_week_does_not_hide_it_but_an_ambiguous_team_is_left_out()
    {
        IReadOnlyList<double?> straggler = Enumerable.Range(1, 18).Select(w => (double?)5.0).ToList();    // played every week, e.g. traded in mid-season
        var six = Enumerable.Range(0, 6).Select(i => Player($"a{i}", Position.WR, 100) with { Team = "AAA", WeeklyPpr = i == 0 ? straggler : Weekly(9) });
        var ambiguous = new[]
        {
            Player("c1", Position.RB, 100) with { Team = "CCC", WeeklyPpr = Weekly(6) },
            Player("c2", Position.RB, 100) with { Team = "CCC", WeeklyPpr = Weekly(6) },
            Player("c3", Position.RB, 100) with { Team = "CCC", WeeklyPpr = Weekly(8) },
            Player("c4", Position.RB, 100) with { Team = "CCC", WeeklyPpr = Weekly(8) },
        };

        var schedule = ByeSchedule.Infer(six.Concat(ambiguous));

        Assert.Equal(9, schedule.WeekOf("AAA"));
        Assert.Null(schedule.WeekOf("CCC"));          // weeks 6 and 8 each have two missing players: no unique week
    }

    [Fact]
    public void A_backup_with_a_different_bye_covers_the_starters_bye_week_and_one_with_the_same_bye_covers_nothing()
    {
        var byes = new ByeSchedule(new Dictionary<string, int> { ["AAA"] = 5, ["BBB"] = 7, ["CCC"] = 5 });
        var starter = V("rb1", Position.RB, 170, "AAA");
        var other = V("rb2", Position.RB, 130, "BBB");
        var same = V("rb3", Position.RB, 130, "CCC");
        IReadOnlyList<ValuedPlayer> roster = [starter];

        var before = LineupValue.ByeCover(roster, NoFlex, Replacement, byes);
        var withOther = LineupValue.ByeCover([starter, other], NoFlex, Replacement, byes) - before;
        var withSame = LineupValue.ByeCover([starter, same], NoFlex, Replacement, byes) - before;

        Assert.Equal((130 - 100) / 17.0, withOther, 9);       // in week 5 he plays instead of a replacement-level pickup, scoring 1/17 of his projection per week
        Assert.Equal(0, withSame, 9);
    }

    [Fact]
    public void Without_known_byes_the_cover_of_adding_a_player_is_zero()
    {
        IReadOnlyList<ValuedPlayer> roster = [V("rb1", Position.RB, 170, "AAA")];

        var change = LineupValue.ByeCover([.. roster, V("rb2", Position.RB, 130, "BBB")], NoFlex, Replacement, ByeSchedule.Empty)
                     - LineupValue.ByeCover(roster, NoFlex, Replacement, ByeSchedule.Empty);

        Assert.Equal(0, change, 9);
    }

    [Fact]
    public void The_recommender_adds_the_cover_to_the_score_only_when_asked_and_prefers_the_backup_with_the_other_bye()
    {
        var pool = new List<ValuedPlayer>
        {
            V("rbA", Position.RB, 170, "AAA", 5), V("wrA", Position.WR, 150, "AAA", 5), V("qbA", Position.QB, 300, "AAA", 5),
            V("rbB", Position.RB, 130, "BBB", 7), V("wrB", Position.WR, 90, "BBB", 7), V("teB", Position.TE, 80, "BBB", 7),
            V("rbC", Position.RB, 130, "CCC", 5), V("wrC", Position.WR, 90, "CCC", 5), V("teC", Position.TE, 80, "CCC", 5),
        };
        var state = new DraftState(pool, NoFlex);
        state.Draft("rbA");           // team 0
        state.Draft("wrA");           // team 1
        state.Draft("qbA");           // team 1 (snake: the second round starts with team 1)
        var reach = new ReachSettings(0, 100);

        var plain = ValueRecommender.Rank(state, reach, NeedSettings.Option, teamIndex: 0).ToDictionary(c => c.Player.Id);
        var cover = ValueRecommender.Rank(state, reach, NeedSettings.WithByes, teamIndex: 0).ToDictionary(c => c.Player.Id);

        Assert.All(plain.Values, c => Assert.Null(c.ByeCover));
        Assert.Equal((130 - 100) / 17.0, cover["rbB"].ByeCover!.Value, 9);
        Assert.Equal(0, cover["rbC"].ByeCover!.Value, 9);
        Assert.Equal(plain["rbB"].Score + cover["rbB"].ByeCover!.Value, cover["rbB"].Score, 9);
        Assert.Equal(plain["rbC"].Score, cover["rbC"].Score, 9);
    }
}
