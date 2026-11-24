using System.Net;
using AlkoCop.Agent.Core;

namespace AlkoCop.Agent.Service;

/// <summary>Sends live status independently of the persistent activity and screenshot queues.</summary>
public sealed class HeartbeatWorker(AgentRuntime runtime, ServerClient client, ILogger<HeartbeatWorker> logger) : BackgroundService
{
    private static readonly TimeSpan Interval = TimeSpan.FromSeconds(20);
    private static readonly TimeSpan RequestDeadline = TimeSpan.FromSeconds(3);

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var timer = new PeriodicTimer(Interval);
        try
        {
            do
            {
                if (runtime.ServerToken is { } token)
                {
                    await SendAsync(token, stoppingToken);
                }
            }
            while (await timer.WaitForNextTickAsync(stoppingToken));
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
        {
        }
    }

    private async Task SendAsync(string token, CancellationToken stoppingToken)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken);
        timeout.CancelAfter(RequestDeadline);
        try
        {
            var session = runtime.LiveSessions.MostRecentInput(
                NativeMethods.GetActiveSessions(), runtime.Config.IdleThresholdSec);
            await client.SendHeartbeatAsync(token, new HeartbeatRequest(session), timeout.Token);
        }
        catch (AgentUnauthorizedException)
        {
            // SyncWorker owns disk state and re-enrollment.
            runtime.RejectHeartbeatToken(token);
        }
        catch (HttpRequestException ex) when (ex.StatusCode == HttpStatusCode.NotFound)
        {
            // An agent may be installed before the server supporting live overview is upgraded.
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
        {
            logger.LogDebug("Heartbeat failed. A fresh observation will be sent on the next tick");
        }
    }
}
