using System.ComponentModel;
using System.Diagnostics;
using System.Text;
using Microsoft.Extensions.Options;
using static AlkoCop.Agent.Service.NativeMethods;

namespace AlkoCop.Agent.Service;

/// <summary>
/// Следит, чтобы в каждой активной сессии (локальной и RDP) работал сборщик,
/// и перезапускает его, если процесс был завершён.
/// </summary>
public sealed class CollectorLauncherWorker(IOptions<AgentOptions> options, ILogger<CollectorLauncherWorker> logger) : BackgroundService
{
    private static readonly TimeSpan CheckInterval = TimeSpan.FromSeconds(10);

    private string CollectorPath =>
        options.Value.CollectorPath ?? Path.Combine(AppContext.BaseDirectory, "AlkoCopCollector.exe");

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var timer = new PeriodicTimer(CheckInterval);
        try
        {
            do
            {
                try
                {
                    EnsureCollectors();
                }
                catch (Exception ex)
                {
                    logger.LogError(ex, "Failed to check collectors");
                }
            }
            while (await timer.WaitForNextTickAsync(stoppingToken));
        }
        catch (OperationCanceledException)
        {
        }
    }

    private void EnsureCollectors()
    {
        var name = Path.GetFileNameWithoutExtension(CollectorPath);
        var running = Process.GetProcessesByName(name)
            .Select(p =>
            {
                using (p)
                {
                    return p.SessionId;
                }
            })
            .ToHashSet();

        foreach (var sessionId in GetActiveSessions())
        {
            if (!running.Contains(sessionId))
            {
                Launch(sessionId);
            }
        }
    }

    private void Launch(int sessionId)
    {
        var userToken = IntPtr.Zero;
        var primaryToken = IntPtr.Zero;
        var environment = IntPtr.Zero;
        try
        {
            if (!WTSQueryUserToken(sessionId, out userToken))
            {
                throw new Win32Exception();
            }
            if (!DuplicateTokenEx(userToken, MaximumAllowed, IntPtr.Zero, SecurityImpersonation, TokenPrimary, out primaryToken))
            {
                throw new Win32Exception();
            }
            if (!CreateEnvironmentBlock(out environment, primaryToken, false))
            {
                environment = IntPtr.Zero;
            }

            var startup = new STARTUPINFO
            {
                cb = System.Runtime.InteropServices.Marshal.SizeOf<STARTUPINFO>(),
                lpDesktop = @"winsta0\default",
            };
            var commandLine = new StringBuilder($"\"{CollectorPath}\"");
            if (!CreateProcessAsUser(
                    primaryToken,
                    CollectorPath,
                    commandLine,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    false,
                    CreateUnicodeEnvironment | CreateNoWindow,
                    environment,
                    Path.GetDirectoryName(CollectorPath),
                    ref startup,
                    out var process))
            {
                throw new Win32Exception();
            }
            CloseHandle(process.hThread);
            CloseHandle(process.hProcess);
            logger.LogInformation("Started collector in session {SessionId} (pid {Pid})", sessionId, process.dwProcessId);
        }
        catch (Win32Exception ex)
        {
            logger.LogWarning("Cannot start collector in session {SessionId}: {Message}", sessionId, ex.Message);
        }
        finally
        {
            if (environment != IntPtr.Zero)
            {
                DestroyEnvironmentBlock(environment);
            }
            if (primaryToken != IntPtr.Zero)
            {
                CloseHandle(primaryToken);
            }
            if (userToken != IntPtr.Zero)
            {
                CloseHandle(userToken);
            }
        }
    }
}
