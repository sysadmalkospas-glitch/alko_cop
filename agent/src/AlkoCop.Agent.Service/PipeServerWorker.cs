using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using AlkoCop.Agent.Core;

namespace AlkoCop.Agent.Service;

/// <summary>
/// Принимает данные от сборщиков в сессиях пользователей. Логин и номер сессии
/// служба определяет сама по подключившемуся процессу, а не верит присланным.
/// </summary>
public sealed class PipeServerWorker(AgentRuntime runtime, ILogger<PipeServerWorker> logger) : BackgroundService
{
    private const int MaxActivityLineLength = 64 * 1024;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            NamedPipeServerStream? server = null;
            try
            {
                server = CreateServer();
                await server.WaitForConnectionAsync(stoppingToken);
                var connected = server;
                server = null;
                _ = HandleClientAsync(connected, stoppingToken);
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Pipe server error");
                await Task.Delay(TimeSpan.FromSeconds(1), stoppingToken).ContinueWith(_ => { }, CancellationToken.None);
            }
            finally
            {
                server?.Dispose();
            }
        }
    }

    private static NamedPipeServerStream CreateServer()
    {
        var security = new PipeSecurity();
        var system = new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null);
        using var identity = WindowsIdentity.GetCurrent();
        if (identity.IsSystem)
        {
            security.SetOwner(system);
        }
        security.AddAccessRule(new PipeAccessRule(
            system, PipeAccessRights.FullControl, AccessControlType.Allow));
        security.AddAccessRule(new PipeAccessRule(
            new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null), PipeAccessRights.FullControl, AccessControlType.Allow));
        security.AddAccessRule(new PipeAccessRule(
            new SecurityIdentifier(WellKnownSidType.AuthenticatedUserSid, null),
            PipeAccessRights.ReadData | PipeAccessRights.WriteData | PipeAccessRights.ReadAttributes | PipeAccessRights.ReadPermissions,
            AccessControlType.Allow));
        return NamedPipeServerStreamAcl.Create(
            PipeMessage.PipeName,
            PipeDirection.InOut,
            NamedPipeServerStream.MaxAllowedServerInstances,
            PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous,
            inBufferSize: 0,
            outBufferSize: 0,
            security);
    }

    private async Task HandleClientAsync(NamedPipeServerStream pipe, CancellationToken ct)
    {
        using var connection = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var writer = new StreamWriter(pipe, new UTF8Encoding(false), leaveOpen: true);
        var publish = PublishConfigAsync(writer, connection);
        var connectionId = Guid.NewGuid();
        var trustedSessionId = 0;
        try
        {
            using var reader = new StreamReader(pipe, Encoding.UTF8, detectEncodingFromByteOrderMarks: false, leaveOpen: true);
            var lines = new BoundedPipeReader(reader, ScreenshotFrame.MaxPipeLineLength);
            // Named-pipe impersonation uses the token from the last message read from the client.
            var line = await lines.ReadLineAsync(connection.Token);
            if (line is null)
            {
                return;
            }
            string? login = null;
            pipe.RunAsClient(() =>
            {
                using var identity = WindowsIdentity.GetCurrent(TokenAccessLevels.Query);
                login = identity.Name;
            });
            NativeMethods.GetNamedPipeClientSessionId(pipe.SafePipeHandle, out var sessionId);
            if (string.IsNullOrEmpty(login) || sessionId == 0)
            {
                return;
            }
            trustedSessionId = (int)sessionId;

            do
            {
                var msg = PipeMessage.FromLine(line);
                if (msg?.Type == PipeMessage.TypeSpan && line.Length <= MaxActivityLineLength && msg.Span is { } span)
                {
                    runtime.RecordSpan(span with { Login = login, SessionId = trustedSessionId });
                }
                else if (msg?.Type == PipeMessage.TypeLiveSample && line.Length <= MaxActivityLineLength)
                {
                    runtime.LiveSessions.Record(trustedSessionId, connectionId, login, msg.LiveSample);
                }
                else if (msg?.Type == PipeMessage.TypeScreenshot && msg.Frame is { } frame)
                {
                    runtime.RecordScreenshot(login, frame);
                }
            }
            while ((line = await lines.ReadLineAsync(connection.Token)) is not null);
        }
        catch (OperationCanceledException)
        {
        }
        catch (IOException)
        {
            // Сборщик отключился (выход пользователя, перезапуск) — это нормально.
        }
        catch (Exception ex)
        {
            logger.LogWarning(ex, "Collector connection failed");
        }
        finally
        {
            if (trustedSessionId != 0)
            {
                runtime.LiveSessions.ForgetConnection(trustedSessionId, connectionId);
            }
            connection.Cancel();
            await publish;
            await pipe.DisposeAsync();
            try
            {
                writer.Dispose();
            }
            catch (Exception ex) when (ex is IOException or ObjectDisposedException)
            {
                // The reader can disconnect before a config update is flushed.
            }
        }
    }

    private async Task PublishConfigAsync(StreamWriter writer, CancellationTokenSource connection)
    {
        try
        {
            while (!connection.IsCancellationRequested)
            {
                var (config, changed) = runtime.SnapshotConfig();
                var line = new PipeMessage(PipeMessage.TypeConfig, Config: config).ToLine();
                await writer.WriteLineAsync(line.AsMemory(), connection.Token);
                await writer.FlushAsync(connection.Token);
                await changed.WaitAsync(connection.Token);
            }
        }
        catch (OperationCanceledException)
        {
        }
        catch (IOException)
        {
            connection.Cancel();
        }
    }
}
