using System.Text.Json;
using System.Text.Json.Serialization;

namespace AlkoCop.Agent.Core;

/// <summary>Форматы данных, которыми агент обменивается с сервером (API v1).</summary>
public static class AgentJson
{
    public static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };
}

public sealed record ActivitySpanDto(
    string Id,
    string Login,
    int SessionId,
    DateTimeOffset StartedAt,
    DateTimeOffset EndedAt,
    bool IsIdle,
    string? ProcessName,
    string? WindowTitle,
    string? Url);

public static class SystemEventKinds
{
    public const string AgentStart = "agent_start";
    public const string AgentStop = "agent_stop";
    public const string Logon = "logon";
    public const string Logoff = "logoff";
    public const string Lock = "lock";
    public const string Unlock = "unlock";
}

public sealed record SystemEventDto(string Id, string? Login, DateTimeOffset OccurredAt, string Kind);

public sealed record ActivityBatch(IReadOnlyList<ActivitySpanDto> Spans, IReadOnlyList<SystemEventDto> Events);

public sealed record BatchResult(int AcceptedSpans, int AcceptedEvents);

public sealed record EnrollRequest(
    string EnrollKey,
    string MachineId,
    string Hostname,
    string? OsVersion,
    string? AgentVersion);

public sealed record EnrollResponse(int ComputerId, string Token);

public sealed record AgentConfigDto(
    int IdleThresholdSec,
    bool ScreenshotsEnabled,
    int ScreenshotIntervalSec,
    int ScreenshotQuality,
    string ScreenshotFormat,
    int ScreenshotMaxWidth,
    bool ScreenshotSkipUnchanged,
    int UploadIntervalSec)
{
    public static AgentConfigDto Default { get; } = new(300, true, 5, 75, "webp", 0, true, 30);
}

/// <summary>
/// Сообщение между сборщиком в сессии пользователя и службой (именованный канал,
/// одна JSON-строка на сообщение).
/// </summary>
public sealed record PipeMessage(
    string Type,
    ActivitySpanDto? Span = null,
    SystemEventDto? Event = null,
    AgentConfigDto? Config = null,
    ScreenshotFrame? Frame = null,
    LiveSample? LiveSample = null)
{
    public const string PipeName = "AlkoCopAgent";
    public const string TypeSpan = "span";
    public const string TypeEvent = "event";
    public const string TypeConfig = "config";
    public const string TypeScreenshot = "screenshot";
    public const string TypeLiveSample = "live_sample";

    public string ToLine() => JsonSerializer.Serialize(this, AgentJson.Options);

    public static PipeMessage? FromLine(string line)
    {
        try
        {
            return JsonSerializer.Deserialize<PipeMessage>(line, AgentJson.Options);
        }
        catch (JsonException)
        {
            return null;
        }
    }
}
