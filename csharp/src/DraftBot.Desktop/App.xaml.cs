using System.Windows;
using DraftBot.App.Services;
using DraftBot.Core;

namespace DraftBot.Desktop;

public partial class App : Application
{
    /// <summary>The user's slot in the practice draft (0-based, so 4 is pick 5 of 12).</summary>
    const int PracticeSlot = 4;

    /// <summary>Opens the practice draft before any window exists: the main window when it opens, otherwise the reason in a message box and exit code 1.</summary>
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        var (draft, error) = PracticeStartup.Open(ProjectionLocator.Find(), new LeagueSettings(), PracticeSlot, Random.Shared.Next());
        if (draft is null)
        {
            MessageBox.Show(error, "DraftBot");
            Shutdown(1);
            return;
        }
        new MainWindow(draft).Show();
    }
}
