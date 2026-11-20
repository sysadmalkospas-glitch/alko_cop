using System.Text.Json;
using AlkoCop.Agent.Core;

namespace AlkoCop.Agent.Service;

/// <summary>Общее состояние службы: очередь, текущие настройки мониторинга, запись событий.</summary>
public sealed class AgentRuntime : IDisposable
{
    public AgentRuntime(AgentOptions options)
    {
        Directory.CreateDirectory(options.DataDirectory);
        Queue = new OutboxQueue(Path.Combine(options.DataDirectory, "outbox.db"));
        State = new AgentStateStore(Path.Combine(options.DataDirectory, "state.json"));
    }

    public OutboxQueue Queue { get; }
    public AgentStateStore State { get; }

    /// <summary>Настройки с сервера; до первого ответа — значения по умолчанию.</summary>
    public AgentConfigDto Config { get; set; } = AgentConfigDto.Default;

    public void RecordEvent(string kind, string? login)
    {
        var ev = new SystemEventDto(Guid.NewGuid().ToString("N"), login, DateTimeOffset.UtcNow, kind);
        Queue.Enqueue(OutboxQueue.KindEvent, ev.Id, JsonSerializer.Serialize(ev, AgentJson.Options));
    }

    public void RecordSpan(ActivitySpanDto span) =>
        Queue.Enqueue(OutboxQueue.KindSpan, span.Id, JsonSerializer.Serialize(span, AgentJson.Options));

    public void Dispose() => Queue.Dispose();
}
