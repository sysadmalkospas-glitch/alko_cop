using System.Diagnostics;
using AlkoCop.Agent.Core;

namespace AlkoCop.Agent.Collector;

/// <summary>Снимает состояние текущей сессии: активное окно, процесс, время простоя.</summary>
internal sealed class WindowSampler
{
    private readonly string _login = $"{Environment.UserDomainName}\\{Environment.UserName}";
    private readonly int _sessionId = Process.GetCurrentProcess().SessionId;
    private readonly Dictionary<uint, string?> _processNames = [];

    public WindowSample Sample()
    {
        var idle = NativeMethods.GetIdleTime();
        var hwnd = NativeMethods.GetForegroundWindow();
        string? process = null;
        string? title = null;
        if (hwnd != IntPtr.Zero)
        {
            title = NativeMethods.GetWindowTitle(hwnd);
            NativeMethods.GetWindowThreadProcessId(hwnd, out var pid);
            process = GetProcessName(pid);
        }
        return new WindowSample(DateTimeOffset.UtcNow, _login, _sessionId, process, title, Url: null, idle);
    }

    private string? GetProcessName(uint pid)
    {
        if (pid == 0)
        {
            return null;
        }
        if (_processNames.TryGetValue(pid, out var cached))
        {
            return cached;
        }
        string? name;
        try
        {
            using var p = Process.GetProcessById((int)pid);
            name = p.ProcessName + ".exe";
        }
        catch (ArgumentException)
        {
            name = null;
        }
        catch (InvalidOperationException)
        {
            name = null;
        }
        if (_processNames.Count > 2000)
        {
            _processNames.Clear();
        }
        _processNames[pid] = name;
        return name;
    }
}
