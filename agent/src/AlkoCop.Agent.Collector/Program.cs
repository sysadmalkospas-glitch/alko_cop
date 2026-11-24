using System.Diagnostics;
using AlkoCop.Agent.Core;

namespace AlkoCop.Agent.Collector;

/// <summary>Samples activity and screens in the user's Windows session. Only the service connects to the server.</summary>
internal static class Program
{
    private static readonly TimeSpan SampleInterval = TimeSpan.FromSeconds(1);
    private static readonly TimeSpan LiveSampleInterval = TimeSpan.FromSeconds(2);
    private const int MaxPendingMessages = 50_000;

    private static async Task<int> Main()
    {
        using var mutex = new Mutex(initiallyOwned: true, @"Local\AlkoCopCollector", out var isFirst);
        if (!isFirst)
        {
            return 0;
        }

        Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);
        using var cts = new CancellationTokenSource();
        EventHandler onExit = (_, _) => cts.Cancel();
        AppDomain.CurrentDomain.ProcessExit += onExit;

        var tracker = new ActivityTracker(
            idleThreshold: TimeSpan.FromSeconds(AgentConfigDto.Default.IdleThresholdSec),
            maxSpanLength: TimeSpan.FromMinutes(1),
            maxSampleGap: TimeSpan.FromMinutes(2));
        var sampler = new WindowSampler();
        var pending = new Queue<string>();
        var elapsed = Stopwatch.StartNew();
        var nextLiveSample = TimeSpan.Zero;
        var schedule = new ScreenshotSchedule();
        var screenshots = new ScreenCapture();
        Task<CaptureBatch>? capture = null;
        CollectorConnection? connection = null;
        long connectionVersion = 0;

        try
        {
            using var timer = new PeriodicTimer(SampleInterval);
            while (await timer.WaitForNextTickAsync(cts.Token))
            {
                var config = connection?.Config;
                if (config is not null)
                {
                    tracker.IdleThreshold = TimeSpan.FromSeconds(config.IdleThresholdSec);
                }
                var sample = sampler.Sample();
                foreach (var span in tracker.Add(sample))
                {
                    Enqueue(pending, new PipeMessage(PipeMessage.TypeSpan, Span: span).ToLine());
                }

                if (connection?.IsClosed == true)
                {
                    await connection.DisposeAsync();
                    connection = null;
                }
                if (connection is null)
                {
                    schedule.Reset();
                    connection = await CollectorConnection.TryConnectAsync(cts.Token);
                    connectionVersion++;
                    nextLiveSample = TimeSpan.Zero;
                }
                if (connection is not null && elapsed.Elapsed >= nextLiveSample)
                {
                    nextLiveSample = elapsed.Elapsed + LiveSampleInterval;
                    var live = NativeMethods.IsInteractiveDesktop() ? new LiveSample(
                        LimitLength(sample.ProcessName, LiveSessionSnapshots.MaxProcessLength),
                        LimitLength(sample.WindowTitle, LiveSessionSnapshots.MaxTitleLength),
                        (int)Math.Min(sample.IdleFor.TotalSeconds, LiveSessionSnapshots.MaxIdleSeconds)) : null;
                    // Always send the latest observation first. Never queue a title for later replay.
                    if (!await connection.SendAsync(new PipeMessage(PipeMessage.TypeLiveSample, LiveSample: live).ToLine(), cts.Token))
                    {
                        await connection.DisposeAsync();
                        connection = null;
                        continue;
                    }
                }
                if (connection is not null && !await TryFlushAsync(connection, pending, cts.Token))
                {
                    await connection.DisposeAsync();
                    connection = null;
                    continue;
                }

                if (capture?.IsCompleted == true)
                {
                    var batch = await capture;
                    capture = null;
                    if (connection is not null && connectionVersion == batch.ConnectionVersion)
                    {
                        foreach (var frame in batch.Frames)
                        {
                            if (connection.Config != batch.Config)
                            {
                                // A superseded profile must never send a late frame to the service.
                                schedule.Reset();
                                break;
                            }
                            var line = new PipeMessage(PipeMessage.TypeScreenshot, Frame: frame).ToLine();
                            if (!await connection.SendAsync(line, cts.Token))
                            {
                                await connection.DisposeAsync();
                                connection = null;
                                break;
                            }
                        }
                    }
                }

                config = connection?.Config;
                if (capture is null && schedule.IsDue(config, sample.ProcessName, elapsed.Elapsed))
                {
                    var profile = config!;
                    var generation = connectionVersion;
                    capture = Task.Run(() => new CaptureBatch(profile, generation, screenshots.Take(profile, generation, cts.Token)));
                }
            }
        }
        catch (OperationCanceledException)
        {
        }
        finally
        {
            AppDomain.CurrentDomain.ProcessExit -= onExit;
            foreach (var span in tracker.Flush(DateTimeOffset.UtcNow))
            {
                Enqueue(pending, new PipeMessage(PipeMessage.TypeSpan, Span: span).ToLine());
            }
            if (connection is not null)
            {
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(1));
                try
                {
                    await TryFlushAsync(connection, pending, timeout.Token);
                }
                catch (OperationCanceledException)
                {
                }
                await connection.DisposeAsync();
            }
            if (capture is not null)
            {
                cts.Cancel();
                await capture;
            }
        }
        return 0;
    }

    private static void Enqueue(Queue<string> pending, string line)
    {
        if (pending.Count >= MaxPendingMessages)
        {
            pending.Dequeue();
        }
        pending.Enqueue(line);
    }

    private static string? LimitLength(string? value, int limit) =>
        value is not null && value.Length > limit ? value[..limit] : value;

    private static async Task<bool> TryFlushAsync(CollectorConnection connection, Queue<string> pending, CancellationToken ct)
    {
        while (pending.TryPeek(out var line))
        {
            if (!await connection.SendAsync(line, ct))
            {
                return false;
            }
            pending.Dequeue();
        }
        return true;
    }

    private sealed record CaptureBatch(AgentConfigDto Config, long ConnectionVersion, IReadOnlyList<ScreenshotFrame> Frames);
}
