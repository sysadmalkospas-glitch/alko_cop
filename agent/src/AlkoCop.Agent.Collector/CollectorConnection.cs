using System.IO.Pipes;
using System.Security.Principal;
using System.Text;
using AlkoCop.Agent.Core;

namespace AlkoCop.Agent.Collector;

internal sealed class CollectorConnection : IAsyncDisposable
{
    private readonly NamedPipeClientStream _pipe;
    private readonly CancellationTokenSource _stop = new();
    private readonly StreamReader _reader;
    private readonly StreamWriter _writer;
    private readonly Task _receive;
    private AgentConfigDto? _config;

    private CollectorConnection(NamedPipeClientStream pipe)
    {
        _pipe = pipe;
        _reader = new StreamReader(pipe, Encoding.UTF8, detectEncodingFromByteOrderMarks: false, leaveOpen: true);
        _writer = new StreamWriter(pipe, new UTF8Encoding(false), leaveOpen: true);
        _receive = ReceiveAsync();
    }

    public AgentConfigDto? Config => Volatile.Read(ref _config);
    public bool IsClosed => _receive.IsCompleted;

    public static async Task<CollectorConnection?> TryConnectAsync(CancellationToken ct)
    {
        var pipe = new NamedPipeClientStream(
            ".", PipeMessage.PipeName,
            PipeAccessRights.ReadData | PipeAccessRights.WriteData | PipeAccessRights.ReadAttributes | PipeAccessRights.ReadPermissions,
            PipeOptions.Asynchronous, TokenImpersonationLevel.Identification, HandleInheritability.None);
        try
        {
            await pipe.ConnectAsync(TimeSpan.FromMilliseconds(500), ct);
            // A pipe with this name can be created when the service is stopped. Verify its server before sending frames.
            if (NativeMethods.GetNamedPipeServerSessionId(pipe.SafePipeHandle, out var sessionId) && sessionId == 0
                && pipe.GetAccessControl().GetOwner(typeof(SecurityIdentifier)) is SecurityIdentifier owner
                && owner.IsWellKnown(WellKnownSidType.LocalSystemSid))
            {
                return new CollectorConnection(pipe);
            }
        }
        catch (Exception ex) when (ex is TimeoutException or IOException or UnauthorizedAccessException)
        {
        }
        catch
        {
            pipe.Dispose();
            throw;
        }
        pipe.Dispose();
        return null;
    }

    public async Task<bool> SendAsync(string line, CancellationToken ct)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(TimeSpan.FromSeconds(2));
        try
        {
            await _writer.WriteLineAsync(line.AsMemory(), timeout.Token);
            await _writer.FlushAsync(timeout.Token);
            return true;
        }
        catch (Exception ex) when (ex is IOException || ex is OperationCanceledException && !ct.IsCancellationRequested)
        {
            return false;
        }
    }

    private async Task ReceiveAsync()
    {
        try
        {
            while (await _reader.ReadLineAsync(_stop.Token) is { } line)
            {
                if (PipeMessage.FromLine(line) is { Type: PipeMessage.TypeConfig, Config: { } config })
                {
                    Volatile.Write(ref _config, config);
                }
            }
        }
        catch (Exception ex) when (ex is IOException or OperationCanceledException)
        {
        }
        finally
        {
            Volatile.Write(ref _config, null);
        }
    }

    public async ValueTask DisposeAsync()
    {
        _stop.Cancel();
        await _receive;
        _pipe.Dispose();
        try
        {
            _writer.Dispose();
        }
        catch (Exception ex) when (ex is IOException or ObjectDisposedException)
        {
        }
        _reader.Dispose();
        _stop.Dispose();
    }
}
