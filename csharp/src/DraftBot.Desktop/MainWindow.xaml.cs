using System.Windows;
using DraftBot.App.Services;
using DraftBot.Core;
using Microsoft.Extensions.DependencyInjection;

namespace DraftBot.Desktop;

public partial class MainWindow : Window
{
    /// <summary>The user's slot in the practice draft (0-based, so 4 is pick 5 of 12).</summary>
    const int PracticeSlot = 4;

    public MainWindow()
    {
        var services = new ServiceCollection();
        services.AddWpfBlazorWebView();
        if (CreatePracticeDraft() is { } draft) services.AddSingleton(draft);
        else
        {
            MessageBox.Show("Could not find the projections file (projections_2026_v1.json). Set DRAFTBOT_PROJECTIONS to its path.", "DraftBot");
            Application.Current.Shutdown();
            return;
        }
        Resources.Add("services", services.BuildServiceProvider());
        InitializeComponent();
    }

    static PracticeDraft? CreatePracticeDraft() =>
        ProjectionLocator.Find() is { } path
            ? new PracticeDraft(ProjectionFile.Load(path), new LeagueSettings(), PracticeSlot, Random.Shared.Next())
            : null;
}
