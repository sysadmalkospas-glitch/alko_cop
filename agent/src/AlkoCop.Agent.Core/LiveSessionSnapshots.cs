namespace AlkoCop.Agent.Core;

public sealed record LiveSample(string? ProcessName, string? WindowTitle, int IdleForSeconds);

public sealed record LiveSession(
    string Login, string? ProcessName, string? WindowTitle, int IdleForSeconds, int SampleAgeSeconds, bool IsIdle);

public sealed record HeartbeatRequest(LiveSession? Session);

/// <summary>Keeps only the latest in-memory observation per connected session.</summary>
public sealed class LiveSessionSnapshots(TimeProvider? clock = null)
{
    public const int MaxTitleLength = 1024;
    public const int MaxProcessLength = 260;
    public const int MaxIdleSeconds = 4_300_000;
    private const int MaxSampleAgeSeconds = 8;

    private readonly TimeProvider _clock = clock ?? TimeProvider.System;
    private readonly Lock _lock = new();
    private readonly Dictionary<int, Entry> _sessions = [];
    private readonly HashSet<int> _pausedSessions = [];

    public void Record(int sessionId, Guid connectionId, string login, LiveSample? sample)
    {
        lock (_lock)
        {
            if (sample is null)
            {
                ForgetConnection(sessionId, connectionId);
                return;
            }
            if (_pausedSessions.Contains(sessionId)
                || sample.IdleForSeconds is < 0 or > MaxIdleSeconds
                || login.Length > 300
                || sample.ProcessName?.Length > MaxProcessLength
                || sample.WindowTitle?.Length > MaxTitleLength)
            {
                return;
            }
            _sessions[sessionId] = new Entry(connectionId, login, sample, _clock.GetTimestamp());
        }
    }

    public void ForgetConnection(int sessionId, Guid connectionId)
    {
        lock (_lock)
        {
            if (_sessions.TryGetValue(sessionId, out var entry) && entry.ConnectionId == connectionId)
            {
                _sessions.Remove(sessionId);
            }
        }
    }

    public void SetPaused(int sessionId, bool paused)
    {
        lock (_lock)
        {
            _sessions.Remove(sessionId);
            if (paused)
            {
                _pausedSessions.Add(sessionId);
            }
            else
            {
                _pausedSessions.Remove(sessionId);
            }
        }
    }

    public LiveSession? MostRecentInput(IEnumerable<int> activeSessions, int idleThresholdSeconds)
    {
        lock (_lock)
        {
            var now = _clock.GetTimestamp();
            LiveSession? best = null;
            var bestId = int.MaxValue;
            foreach (var id in activeSessions)
            {
                if (!_sessions.TryGetValue(id, out var entry))
                {
                    continue;
                }
                var elapsed = _clock.GetElapsedTime(entry.Received, now);
                if (elapsed >= TimeSpan.FromSeconds(MaxSampleAgeSeconds))
                {
                    continue;
                }
                var sampleAge = (int)elapsed.TotalSeconds;
                var idle = Math.Min(MaxIdleSeconds, entry.Sample.IdleForSeconds + sampleAge);
                if (best is null || idle < best.IdleForSeconds || idle == best.IdleForSeconds && id < bestId)
                {
                    best = new LiveSession(entry.Login, entry.Sample.ProcessName, entry.Sample.WindowTitle,
                        idle, sampleAge, idle >= idleThresholdSeconds);
                    bestId = id;
                }
            }
            return best;
        }
    }

    private sealed record Entry(Guid ConnectionId, string Login, LiveSample Sample, long Received);
}
