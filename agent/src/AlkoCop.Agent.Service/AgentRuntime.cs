using System.Text.Json;
using AlkoCop.Agent.Core;

namespace AlkoCop.Agent.Service;

/// <summary>Общее состояние службы: очередь, текущие настройки мониторинга, запись событий.</summary>
public sealed class AgentRuntime : IDisposable
{
    private readonly Lock _configLock = new();
    private AgentConfigDto _config = AgentConfigDto.Default with { ScreenshotsEnabled = false };
    private TaskCompletionSource _configChanged = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private string? _serverToken;
    private string? _rejectedHeartbeatToken;

    public AgentRuntime(AgentOptions options)
    {
        Directory.CreateDirectory(options.DataDirectory);
        Queue = new OutboxQueue(Path.Combine(options.DataDirectory, "outbox.db"));
        Screenshots = new ScreenshotQueue(Path.Combine(options.DataDirectory, "pending-screenshots"));
        State = new AgentStateStore(Path.Combine(options.DataDirectory, "state.json"));
    }

    public OutboxQueue Queue { get; }
    public ScreenshotQueue Screenshots { get; }
    public AgentStateStore State { get; }
    internal LiveSessionSnapshots LiveSessions { get; } = new();

    internal string? ServerToken
    {
        get => Volatile.Read(ref _serverToken);
        set => Volatile.Write(ref _serverToken, value);
    }

    internal void RejectHeartbeatToken(string token) => Volatile.Write(ref _rejectedHeartbeatToken, token);

    internal bool IsHeartbeatTokenRejected(string token) => Volatile.Read(ref _rejectedHeartbeatToken) == token;

    /// <summary>Screenshots require a monitoring profile received from the server.</summary>
    public AgentConfigDto Config
    {
        get => SnapshotConfig().Config;
        set
        {
            lock (_configLock)
            {
                if (_config != value)
                {
                    _config = value;
                    _configChanged.SetResult();
                    _configChanged = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                }
            }
        }
    }

    internal (AgentConfigDto Config, Task Changed) SnapshotConfig()
    {
        lock (_configLock)
        {
            return (_config, _configChanged.Task);
        }
    }

    public void RecordEvent(string kind, string? login)
    {
        var ev = new SystemEventDto(Guid.NewGuid().ToString("N"), login, DateTimeOffset.UtcNow, kind);
        Queue.Enqueue(OutboxQueue.KindEvent, ev.Id, JsonSerializer.Serialize(ev, AgentJson.Options));
    }

    public void RecordSpan(ActivitySpanDto span) =>
        Queue.Enqueue(OutboxQueue.KindSpan, span.Id, JsonSerializer.Serialize(span, AgentJson.Options));

    internal void RecordScreenshot(string login, ScreenshotFrame frame)
    {
        lock (_configLock)
        {
            if (_config.ScreenshotsEnabled)
            {
                Screenshots.Enqueue(login, frame);
            }
        }
    }

    public void Dispose() => Queue.Dispose();
}
