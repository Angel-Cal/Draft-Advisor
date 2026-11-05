using DraftBot.Core;
using DraftBot.Sim;
using static DraftBot.Tests.TestData;

namespace DraftBot.Tests;

public class CardChoiceTests
{
    static readonly LeagueSettings League = new();
    static readonly SimSettings Settings = new(League);

    static DraftState MidDraft()
    {
        var state = new DraftState(Valuator.Value(BacktestFile().Players, BacktestFile().PositionRmse, League), League);
        foreach (var p in state.Available.OrderBy(p => p.Player.Adp).Take(40).ToList()) state.Draft(p.Id);
        return state;
    }

    [Fact]
    public void Every_choice_is_one_of_the_shown_cards_and_the_rules_differ_as_described()
    {
        var state = MidDraft();
        var team = state.CurrentTeam;
        var legal = DraftRules.LegalPicks(state, team, Settings);
        var cards = DraftAdvisor.Advise(state, team, confidenceSamples: 0).Recommended.Take(CardChoiceStrategy.ShownCards).Select(r => r.Candidate.Player).ToList();

        Assert.Equal(cards[0].Id, new CardChoiceStrategy("first", CardChoice.First).Pick(state, team, legal).Id);
        Assert.Equal(cards.MinBy(p => p.Player.Adp)!.Id, new CardChoiceStrategy("adp", CardChoice.LowestAdp).Pick(state, team, legal).Id);
        var random = new CardChoiceStrategy("random", CardChoice.Random);
        var pick = random.Pick(state, team, legal);
        Assert.Contains(cards, c => c.Id == pick.Id);
        Assert.Equal(pick.Id, random.Pick(state, team, legal).Id);                  // the same draft gives the same choice
    }

    [Fact]
    public void Random_choices_fill_the_roster_and_depart_from_the_first_card()
    {
        var pool = Valuator.Value(BacktestFile().Players, BacktestFile().PositionRmse, League);
        var differs = false;
        foreach (var seed in Enumerable.Range(0, 4))
        {
            var random = DraftSimulator.Run(pool, Settings, 4, new CardChoiceStrategy("random", CardChoice.Random), seed: seed).MyPicks;
            var first = DraftSimulator.Run(pool, Settings, 4, new CardChoiceStrategy("first", CardChoice.First), seed: seed).MyPicks;
            Assert.Equal(League.RosterSize, random.Count);
            differs |= !random.Select(p => p.Id).SequenceEqual(first.Select(p => p.Id));
        }
        Assert.True(differs);
    }
}
