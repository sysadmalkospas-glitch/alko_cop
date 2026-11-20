using System.Net;
using System.Text;
using System.Text.Json;
using AlkoCop.Agent.Core;

namespace AlkoCop.Agent.Core.Tests;

public sealed class OutboxTests : IDisposable
{
    private readonly string _dir = Path.Combine(Path.GetTempPath(), "alkocop-tests-" + Guid.NewGuid().ToString("N"));

    public void Dispose()
    {
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        if (Directory.Exists(_dir))
        {
            Directory.Delete(_dir, recursive: true);
        }
    }

    private static string SpanJson(string id) => JsonSerializer.Serialize(
        new ActivitySpanDto(id, "u", 1, DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch.AddSeconds(1), false, "p.exe", "t", null),
        AgentJson.Options);

    [Fact]
    public void Queue_IgnoresDuplicates_AndKeepsOrder()
    {
        using var q = new OutboxQueue(Path.Combine(_dir, "q.db"));
        q.Enqueue(OutboxQueue.KindSpan, "a", "1");
        q.Enqueue(OutboxQueue.KindSpan, "b", "2");
        q.Enqueue(OutboxQueue.KindSpan, "a", "1");
        Assert.Equal(["a", "b"], q.Peek(10).Select(i => i.Id));
        q.Remove(["a"]);
        Assert.Equal(1, q.Count());
    }

    [Fact]
    public async Task Uploader_SendsBatches_AndClearsQueue()
    {
        using var q = new OutboxQueue(Path.Combine(_dir, "q.db"));
        for (var i = 0; i < 5; i++)
        {
            q.Enqueue(OutboxQueue.KindSpan, $"s{i}", SpanJson($"s{i}"));
        }
        q.Enqueue(OutboxQueue.KindEvent, "e1", JsonSerializer.Serialize(
            new SystemEventDto("e1", "u", DateTimeOffset.UnixEpoch, SystemEventKinds.Logon), AgentJson.Options));

        var handler = new RecordingHandler(HttpStatusCode.OK);
        var client = new ServerClient(new HttpClient(handler) { BaseAddress = new Uri("http://server/") });
        var sent = await new OutboxUploader(q, client, batchSize: 4).DrainAsync("tok", CancellationToken.None);

        Assert.Equal(6, sent);
        Assert.Equal(0, q.Count());
        Assert.Equal(2, handler.Bodies.Count);
        Assert.Contains("\"started_at\"", handler.Bodies[0]);
        Assert.Equal("Bearer tok", handler.Auth[0]);
    }

    [Fact]
    public async Task Uploader_KeepsQueue_WhenServerFails()
    {
        using var q = new OutboxQueue(Path.Combine(_dir, "q.db"));
        q.Enqueue(OutboxQueue.KindSpan, "s1", SpanJson("s1"));
        var client = new ServerClient(new HttpClient(new RecordingHandler(HttpStatusCode.BadGateway)) { BaseAddress = new Uri("http://server/") });

        await Assert.ThrowsAsync<HttpRequestException>(() => new OutboxUploader(q, client).DrainAsync("tok", CancellationToken.None));
        Assert.Equal(1, q.Count());
    }

    [Fact]
    public async Task Unauthorized_IsReported()
    {
        var client = new ServerClient(new HttpClient(new RecordingHandler(HttpStatusCode.Unauthorized)) { BaseAddress = new Uri("http://server/") });
        await Assert.ThrowsAsync<AgentUnauthorizedException>(() => client.GetConfigAsync("tok", CancellationToken.None));
    }

    [Fact]
    public void StateStore_PersistsMachineId()
    {
        var store = new AgentStateStore(Path.Combine(_dir, "state.json"));
        var first = store.LoadOrCreate();
        store.Save(first with { Token = "t", ComputerId = 3 });
        var again = store.LoadOrCreate();
        Assert.Equal(first.MachineId, again.MachineId);
        Assert.Equal("t", again.Token);
    }

    [Fact]
    public void PipeMessage_RoundTrips()
    {
        var msg = new PipeMessage(PipeMessage.TypeConfig, Config: AgentConfigDto.Default);
        var parsed = PipeMessage.FromLine(msg.ToLine());
        Assert.Equal(AgentConfigDto.Default, parsed!.Config);
        Assert.Null(PipeMessage.FromLine("not json"));
    }

    private sealed class RecordingHandler(HttpStatusCode status) : HttpMessageHandler
    {
        public List<string> Bodies { get; } = [];
        public List<string?> Auth { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Bodies.Add(request.Content is null ? "" : await request.Content.ReadAsStringAsync(ct));
            Auth.Add(request.Headers.Authorization?.ToString());
            var body = request.RequestUri!.AbsolutePath.EndsWith("/config")
                ? JsonSerializer.Serialize(AgentConfigDto.Default, AgentJson.Options)
                : "{\"accepted_spans\":0,\"accepted_events\":0}";
            return new HttpResponseMessage(status) { Content = new StringContent(body, Encoding.UTF8, "application/json") };
        }
    }
}
