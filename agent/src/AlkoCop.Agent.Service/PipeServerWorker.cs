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
    private const int MaxLineLength = 64 * 1024;

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
                _ = Task.Run(() => HandleClientAsync(connected, stoppingToken), stoppingToken);
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
        security.AddAccessRule(new PipeAccessRule(
            new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null), PipeAccessRights.FullControl, AccessControlType.Allow));
        security.AddAccessRule(new PipeAccessRule(
            new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null), PipeAccessRights.FullControl, AccessControlType.Allow));
        security.AddAccessRule(new PipeAccessRule(
            new SecurityIdentifier(WellKnownSidType.AuthenticatedUserSid, null), PipeAccessRights.ReadWrite, AccessControlType.Allow));
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
        await using var _ = pipe;
        try
        {
            string? login = null;
            pipe.RunAsClient(() => login = WindowsIdentity.GetCurrent(TokenAccessLevels.Query).Name);
            NativeMethods.GetNamedPipeClientSessionId(pipe.SafePipeHandle, out var sessionId);
            if (string.IsNullOrEmpty(login) || sessionId == 0)
            {
                return;
            }

            var writer = new StreamWriter(pipe, new UTF8Encoding(false), leaveOpen: true);
            await writer.WriteLineAsync(new PipeMessage(PipeMessage.TypeConfig, Config: runtime.Config).ToLine());
            await writer.FlushAsync(ct);

            using var reader = new StreamReader(pipe, Encoding.UTF8, detectEncodingFromByteOrderMarks: false, leaveOpen: true);
            while (!ct.IsCancellationRequested && await reader.ReadLineAsync(ct) is { } line)
            {
                if (line.Length > MaxLineLength)
                {
                    continue;
                }
                var msg = PipeMessage.FromLine(line);
                if (msg?.Type == PipeMessage.TypeSpan && msg.Span is { } span)
                {
                    runtime.RecordSpan(span with { Login = login, SessionId = (int)sessionId });
                }
            }
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
    }
}
