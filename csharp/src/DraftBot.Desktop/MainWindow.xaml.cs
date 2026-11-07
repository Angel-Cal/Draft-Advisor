using System.Windows;
using DraftBot.App.Services;
using Microsoft.Extensions.DependencyInjection;

namespace DraftBot.Desktop;

public partial class MainWindow : Window
{
    /// <summary>The window hosting the app's screens over an opened practice draft (see App.OnStartup).</summary>
    public MainWindow(PracticeDraft draft)
    {
        var services = new ServiceCollection();
        services.AddWpfBlazorWebView();
        services.AddSingleton(draft);
        Resources.Add("services", services.BuildServiceProvider());
        InitializeComponent();
    }
}
