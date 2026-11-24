using System.Net;
using System.Text.Json;
using AlkoCop.Agent.Core;

namespace AlkoCop.Agent.Core.Tests;

public sealed class LiveSessionTests
{
    [Fact]
    public void UsesMostRecentInputAmongActiveSessionsAndDropsStaleSamples()
    {
        var clock = new Clock();
        var samples = new LiveSessionSnapshots(clock);
        samples.Record(1, Guid.NewGuid(), "older", new LiveSample("editor.exe", "Older", 10));
        samples.Record(2, Guid.NewGuid(), "nearer", new LiveSample("viewer.exe", "Nearer", 0));
        clock.Tick = 2;
        Assert.Equal("older", samples.MostRecentInput([1], 12)!.Login);
        Assert.True(samples.MostRecentInput([1], 12)!.IsIdle);
        var latest = Assert.IsType<LiveSession>(samples.MostRecentInput([2, 1], 12));
        Assert.Equal("nearer", latest.Login);
        Assert.Equal(2, latest.SampleAgeSeconds);
        Assert.Equal(2, latest.IdleForSeconds);
        Assert.False(latest.IsIdle);
        clock.Tick = 8;
        Assert.Null(samples.MostRecentInput([1, 2], 12));
    }

    [Fact]
    public void LockAndDisconnectClearTitlesWithoutErasingAReconnectedCollector()
    {
        var samples = new LiveSessionSnapshots();
        var first = Guid.NewGuid();
        var second = Guid.NewGuid();
        var title = new LiveSample("editor.exe", "Document", 0);
        samples.Record(1, first, "employee", title);
        samples.SetPaused(1, true);
        samples.Record(1, first, "employee", title);
        Assert.Null(samples.MostRecentInput([1], 10));
        samples.SetPaused(1, false);
        samples.Record(1, second, "employee", title);
        samples.ForgetConnection(1, first);
        Assert.Equal("Document", samples.MostRecentInput([1], 10)!.WindowTitle);
        samples.Record(1, second, "employee", null);
        Assert.Null(samples.MostRecentInput([1], 10));
    }

    [Fact]
    public async Task HeartbeatUsesAgentAuthAndSendsOnlyTheLatestSessionFields()
    {
        using var http = new HttpClient(new HeartbeatHandler()) { BaseAddress = new Uri("https://server/") };
        var client = new ServerClient(http);
        var latest = new LiveSession("employee", "editor.exe", "Test Document", 15, 2, false);
        await client.SendHeartbeatAsync("test-token", new HeartbeatRequest(latest), CancellationToken.None);
    }

    private sealed class Clock : TimeProvider
    {
        public long Tick { get; set; }
        public override long TimestampFrequency => 1;
        public override long GetTimestamp() => Tick;
    }

    private sealed class HeartbeatHandler : HttpMessageHandler
    {
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Assert.Equal(HttpMethod.Post, request.Method);
            Assert.Equal("/api/agent/v1/heartbeat", request.RequestUri!.AbsolutePath);
            Assert.Equal("Bearer test-token", request.Headers.Authorization?.ToString());
            using var body = JsonDocument.Parse(await request.Content!.ReadAsStringAsync(ct));
            var session = body.RootElement.GetProperty("session");
            Assert.Equal("employee", session.GetProperty("login").GetString());
            Assert.Equal("Test Document", session.GetProperty("window_title").GetString());
            Assert.Equal(15, session.GetProperty("idle_for_seconds").GetInt32());
            Assert.False(session.TryGetProperty("computer_id", out _));
            return new HttpResponseMessage(HttpStatusCode.NoContent);
        }
    }
}
