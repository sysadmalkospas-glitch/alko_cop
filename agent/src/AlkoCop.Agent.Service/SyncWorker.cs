using System.Reflection;
using System.Runtime.InteropServices;
using AlkoCop.Agent.Core;
using Microsoft.Extensions.Options;

namespace AlkoCop.Agent.Service;

/// <summary>Регистрация на сервере, получение настроек и отправка накопленных данных.</summary>
public sealed class SyncWorker(
    AgentRuntime runtime,
    ServerClient client,
    IOptions<AgentOptions> options,
    ILogger<SyncWorker> logger) : BackgroundService
{
    private static readonly TimeSpan ConfigRefresh = TimeSpan.FromMinutes(5);
    private static readonly TimeSpan MaxBackoff = TimeSpan.FromMinutes(5);

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        runtime.RecordEvent(SystemEventKinds.AgentStart, null);
        var uploader = new OutboxUploader(runtime.Queue, client);
        var screenshotUploader = new ScreenshotUploader(runtime.Screenshots, client);
        var lastConfig = DateTimeOffset.MinValue;
        var backoff = TimeSpan.FromSeconds(5);

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var token = await EnsureEnrolledAsync(stoppingToken);
                runtime.ServerToken = token;
                if (DateTimeOffset.UtcNow - lastConfig > ConfigRefresh)
                {
                    runtime.Config = await client.GetConfigAsync(token, stoppingToken);
                    lastConfig = DateTimeOffset.UtcNow;
                }
                var sent = await uploader.DrainAsync(token, stoppingToken);
                sent += await screenshotUploader.DrainAsync(token, TimeSpan.FromSeconds(10), stoppingToken);
                if (sent > 0)
                {
                    logger.LogDebug("Uploaded {Count} records", sent);
                }
                backoff = TimeSpan.FromSeconds(5);
                await Task.Delay(TimeSpan.FromSeconds(Math.Max(5, runtime.Config.UploadIntervalSec)), stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (AgentUnauthorizedException)
            {
                logger.LogWarning("Server rejected the agent token, enrolling again");
                runtime.ServerToken = null;
                var state = runtime.State.LoadOrCreate();
                runtime.State.Save(state with { Token = null });
            }
            catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
            {
                // Нет связи с сервером (VPN, перезагрузка сервера): данные ждут в очереди.
                logger.LogWarning("Server unavailable: {Message}. Retry in {Delay}", ex.Message, backoff);
                await Task.Delay(backoff, stoppingToken).ContinueWith(_ => { }, CancellationToken.None);
                backoff = TimeSpan.FromTicks(Math.Min(backoff.Ticks * 2, MaxBackoff.Ticks));
            }
            catch (Exception ex)
            {
                // Любая другая ошибка не должна останавливать службу.
                logger.LogError(ex, "Sync failed. Retry in {Delay}", MaxBackoff);
                await Task.Delay(MaxBackoff, stoppingToken).ContinueWith(_ => { }, CancellationToken.None);
            }
        }
    }

    public override async Task StopAsync(CancellationToken cancellationToken)
    {
        runtime.RecordEvent(SystemEventKinds.AgentStop, null);
        await base.StopAsync(cancellationToken);
    }

    private async Task<string> EnsureEnrolledAsync(CancellationToken ct)
    {
        var state = runtime.State.LoadOrCreate();
        if (!string.IsNullOrEmpty(state.Token) && !runtime.IsHeartbeatTokenRejected(state.Token))
        {
            return state.Token;
        }
        var resp = await client.EnrollAsync(
            new EnrollRequest(
                options.Value.EnrollKey,
                state.MachineId,
                Environment.MachineName,
                RuntimeInformation.OSDescription,
                typeof(SyncWorker).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion),
            ct);
        runtime.State.Save(state with { Token = resp.Token, ComputerId = resp.ComputerId });
        logger.LogInformation("Enrolled as computer {ComputerId}", resp.ComputerId);
        return resp.Token;
    }
}
