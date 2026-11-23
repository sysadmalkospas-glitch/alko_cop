namespace AlkoCop.Agent.Core;

/// <summary>Schedule for one user's session. Call only when the capture worker is available.</summary>
public sealed class ScreenshotSchedule
{
    private AgentConfigDto? _previousConfig;
    private string? _previousProcess;
    private TimeSpan? _lastCapture;

    public bool IsDue(AgentConfigDto? config, string? foregroundProcess, TimeSpan elapsed)
    {
        if (config?.ScreenshotsEnabled != true)
        {
            Reset();
            return false;
        }

        var processChanged = foregroundProcess is not null
            && !string.Equals(_previousProcess, foregroundProcess, StringComparison.OrdinalIgnoreCase);
        var profileChanged = _previousConfig != config;
        if (!profileChanged && !processChanged && _lastCapture is { } last
            && elapsed - last < TimeSpan.FromSeconds(Math.Max(1, config.ScreenshotIntervalSec)))
        {
            return false;
        }

        _previousConfig = config;
        _previousProcess = foregroundProcess;
        _lastCapture = elapsed;
        return true;
    }

    public void Reset()
    {
        _previousConfig = null;
        _previousProcess = null;
        _lastCapture = null;
    }
}
