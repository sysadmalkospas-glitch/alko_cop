using System.ServiceProcess;
using AlkoCop.Agent.Core;
using Microsoft.Extensions.Hosting.WindowsServices;
using Microsoft.Extensions.Options;

namespace AlkoCop.Agent.Service;

/// <summary>Жизненный цикл службы Windows с записью событий сессий: вход, выход, блокировка.</summary>
public sealed class AgentServiceLifetime : WindowsServiceLifetime
{
    private readonly AgentRuntime _runtime;

    public AgentServiceLifetime(
        IHostEnvironment environment,
        IHostApplicationLifetime applicationLifetime,
        ILoggerFactory loggerFactory,
        IOptions<HostOptions> optionsAccessor,
        IOptions<WindowsServiceLifetimeOptions> windowsServiceOptionsAccessor,
        AgentRuntime runtime)
        : base(environment, applicationLifetime, loggerFactory, optionsAccessor, windowsServiceOptionsAccessor)
    {
        _runtime = runtime;
        CanHandleSessionChangeEvent = true;
        CanShutdown = true;
    }

    protected override void OnSessionChange(SessionChangeDescription changeDescription)
    {
        var kind = changeDescription.Reason switch
        {
            SessionChangeReason.SessionLogon => SystemEventKinds.Logon,
            SessionChangeReason.SessionLogoff => SystemEventKinds.Logoff,
            SessionChangeReason.SessionLock => SystemEventKinds.Lock,
            SessionChangeReason.SessionUnlock => SystemEventKinds.Unlock,
            _ => null,
        };
        if (kind is not null)
        {
            _runtime.RecordEvent(kind, NativeMethods.GetSessionLogin(changeDescription.SessionId));
        }
        base.OnSessionChange(changeDescription);
    }
}
