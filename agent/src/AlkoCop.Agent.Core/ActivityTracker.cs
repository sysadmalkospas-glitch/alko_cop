namespace AlkoCop.Agent.Core;

/// <summary>Один замер состояния сессии: активное окно и время без ввода.</summary>
public sealed record WindowSample(
    DateTimeOffset At,
    string Login,
    int SessionId,
    string? ProcessName,
    string? WindowTitle,
    string? Url,
    TimeSpan IdleFor);

/// <summary>
/// Превращает поток замеров (раз в секунду) в отрезки активности.
/// Отрезок закрывается при смене окна, переходе в простой и обратно,
/// при разрыве в замерах (сон, выключение) и по достижении максимальной длины,
/// чтобы данные уходили на сервер регулярно. Простой засчитывается задним числом
/// с момента последнего ввода, поэтому отрезок не режется внутри периода без ввода.
/// </summary>
public sealed class ActivityTracker
{
    private readonly Func<string> _newId;
    private OpenSpan? _current;

    public ActivityTracker(TimeSpan idleThreshold, TimeSpan maxSpanLength, TimeSpan maxSampleGap, Func<string>? newId = null)
    {
        IdleThreshold = idleThreshold;
        MaxSpanLength = maxSpanLength;
        MaxSampleGap = maxSampleGap;
        _newId = newId ?? (() => Guid.NewGuid().ToString("N"));
    }

    public TimeSpan IdleThreshold { get; set; }
    public TimeSpan MaxSpanLength { get; }
    public TimeSpan MaxSampleGap { get; }

    public IReadOnlyList<ActivitySpanDto> Add(WindowSample sample)
    {
        var closed = new List<ActivitySpanDto>(2);
        var idle = sample.IdleFor >= IdleThreshold;
        var key = idle
            ? new SpanKey(sample.Login, sample.SessionId, true, null, null, null)
            : new SpanKey(sample.Login, sample.SessionId, false, sample.ProcessName, sample.WindowTitle, sample.Url);

        if (_current is { } cur && sample.At - cur.LastSeen > MaxSampleGap)
        {
            // Замеров долго не было (сон, зависание): закрываем отрезок там, где видели его последний раз.
            Close(cur, cur.LastSeen, closed);
            _current = null;
        }

        if (_current is null)
        {
            _current = new OpenSpan(_newId(), key, sample.At);
            return closed;
        }

        var current = _current;
        if (current.Key == key)
        {
            current.LastSeen = sample.At;
            if (sample.At - current.Start >= MaxSpanLength)
            {
                // Режем только по моменту последнего ввода: хвост без ввода остаётся
                // в открытом отрезке и может позже превратиться в простой.
                var lastInput = sample.At - sample.IdleFor;
                if (lastInput > current.Start)
                {
                    Close(current, lastInput, closed);
                    _current = new OpenSpan(_newId(), key, lastInput) { LastSeen = sample.At };
                }
            }
            return closed;
        }

        var boundary = sample.At;
        if (idle && !current.Key.IsIdle)
        {
            // Простой начался раньше, чем мы его заметили: последний ввод был IdleFor назад.
            var idleStart = sample.At - sample.IdleFor;
            if (idleStart >= current.Start)
            {
                boundary = idleStart;
            }
        }

        Close(current, boundary, closed);
        _current = new OpenSpan(_newId(), key, boundary) { LastSeen = sample.At };
        return closed;
    }

    /// <summary>Закрыть текущий отрезок (выход из системы, остановка агента).</summary>
    public IReadOnlyList<ActivitySpanDto> Flush(DateTimeOffset at)
    {
        var closed = new List<ActivitySpanDto>(1);
        if (_current is { } cur)
        {
            var end = at - cur.LastSeen > MaxSampleGap ? cur.LastSeen : at;
            Close(cur, end, closed);
            _current = null;
        }
        return closed;
    }

    private static void Close(OpenSpan span, DateTimeOffset end, List<ActivitySpanDto> output)
    {
        if (end <= span.Start)
        {
            return;
        }
        var k = span.Key;
        output.Add(new ActivitySpanDto(span.Id, k.Login, k.SessionId, span.Start, end, k.IsIdle, k.ProcessName, k.WindowTitle, k.Url));
    }

    private sealed record SpanKey(string Login, int SessionId, bool IsIdle, string? ProcessName, string? WindowTitle, string? Url);

    private sealed class OpenSpan(string id, SpanKey key, DateTimeOffset start)
    {
        public string Id { get; } = id;
        public SpanKey Key { get; } = key;
        public DateTimeOffset Start { get; } = start;
        public DateTimeOffset LastSeen { get; set; } = start;
    }
}
