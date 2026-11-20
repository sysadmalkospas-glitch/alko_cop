using System.IO.Pipes;
using System.Security.Principal;
using System.Text;
using AlkoCop.Agent.Core;

namespace AlkoCop.Agent.Collector;

/// <summary>
/// Сборщик в сессии пользователя. Запускается службой AlkoCopAgent в каждой
/// активной сессии (включая RDP), окон не показывает. Раз в секунду снимает
/// активное окно и простой, собирает отрезки активности и передаёт их службе
/// через именованный канал. Сам на сервер не ходит: токен есть только у службы.
/// </summary>
internal static class Program
{
    private static readonly TimeSpan SampleInterval = TimeSpan.FromSeconds(1);
    private const int MaxPendingMessages = 50_000;

    private static async Task<int> Main()
    {
        using var mutex = new Mutex(initiallyOwned: true, @"Local\AlkoCopCollector", out var isFirst);
        if (!isFirst)
        {
            return 0;
        }

        using var cts = new CancellationTokenSource();
        AppDomain.CurrentDomain.ProcessExit += (_, _) => cts.Cancel();

        var config = AgentConfigDto.Default;
        var tracker = new ActivityTracker(
            idleThreshold: TimeSpan.FromSeconds(config.IdleThresholdSec),
            maxSpanLength: TimeSpan.FromMinutes(1),
            maxSampleGap: TimeSpan.FromMinutes(2));
        var sampler = new WindowSampler();
        var pending = new Queue<string>();
        NamedPipeClientStream? pipe = null;
        StreamWriter? writer = null;

        try
        {
            using var timer = new PeriodicTimer(SampleInterval);
            while (await timer.WaitForNextTickAsync(cts.Token))
            {
                foreach (var span in tracker.Add(sampler.Sample()))
                {
                    Enqueue(pending, new PipeMessage(PipeMessage.TypeSpan, Span: span).ToLine());
                }

                if (writer is null)
                {
                    (pipe, writer, var received) = await TryConnectAsync(cts.Token);
                    if (received is not null)
                    {
                        config = received;
                        tracker.IdleThreshold = TimeSpan.FromSeconds(config.IdleThresholdSec);
                    }
                }

                if (writer is not null && !await TryFlushAsync(writer, pending))
                {
                    writer.Dispose();
                    pipe?.Dispose();
                    (writer, pipe) = (null, null);
                }
            }
        }
        catch (OperationCanceledException)
        {
        }
        finally
        {
            foreach (var span in tracker.Flush(DateTimeOffset.UtcNow))
            {
                Enqueue(pending, new PipeMessage(PipeMessage.TypeSpan, Span: span).ToLine());
            }
            if (writer is not null)
            {
                await TryFlushAsync(writer, pending);
                writer.Dispose();
            }
            pipe?.Dispose();
        }
        return 0;
    }

    private static void Enqueue(Queue<string> pending, string line)
    {
        // Если служба долго недоступна, отбрасываем самое старое, чтобы не съесть память.
        if (pending.Count >= MaxPendingMessages)
        {
            pending.Dequeue();
        }
        pending.Enqueue(line);
    }

    private static async Task<(NamedPipeClientStream?, StreamWriter?, AgentConfigDto?)> TryConnectAsync(CancellationToken ct)
    {
        var pipe = new NamedPipeClientStream(
            ".", PipeMessage.PipeName, PipeDirection.InOut, PipeOptions.Asynchronous, TokenImpersonationLevel.Identification);
        try
        {
            await pipe.ConnectAsync(TimeSpan.FromMilliseconds(500), ct);
            var reader = new StreamReader(pipe, Encoding.UTF8, detectEncodingFromByteOrderMarks: false, leaveOpen: true);
            // Первым сообщением служба присылает текущие настройки мониторинга.
            var line = await reader.ReadLineAsync(ct).AsTask().WaitAsync(TimeSpan.FromSeconds(5), ct);
            var config = line is null ? null : PipeMessage.FromLine(line)?.Config;
            var writer = new StreamWriter(pipe, new UTF8Encoding(false), leaveOpen: true) { AutoFlush = false };
            return (pipe, writer, config);
        }
        catch (Exception ex) when (ex is TimeoutException or IOException or UnauthorizedAccessException)
        {
            await pipe.DisposeAsync();
            return (null, null, null);
        }
    }

    private static async Task<bool> TryFlushAsync(StreamWriter writer, Queue<string> pending)
    {
        try
        {
            while (pending.TryPeek(out var line))
            {
                await writer.WriteLineAsync(line);
                pending.Dequeue();
            }
            await writer.FlushAsync();
            return true;
        }
        catch (IOException)
        {
            return false;
        }
    }
}
