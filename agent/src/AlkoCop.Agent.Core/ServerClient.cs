using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;

namespace AlkoCop.Agent.Core;

/// <summary>Токен агента больше не принимается сервером: нужна повторная регистрация.</summary>
public sealed class AgentUnauthorizedException() : Exception("Server rejected the agent token");

/// <summary>HTTP-клиент API агента (v1). HttpClient.BaseAddress — адрес сервера.</summary>
public sealed class ServerClient(HttpClient http)
{
    public async Task<EnrollResponse> EnrollAsync(EnrollRequest request, CancellationToken ct)
    {
        using var resp = await http.PostAsJsonAsync("api/agent/v1/enroll", request, AgentJson.Options, ct);
        resp.EnsureSuccessStatusCode();
        return (await resp.Content.ReadFromJsonAsync<EnrollResponse>(AgentJson.Options, ct))!;
    }

    public async Task<AgentConfigDto> GetConfigAsync(string token, CancellationToken ct)
    {
        using var req = new HttpRequestMessage(HttpMethod.Get, "api/agent/v1/config");
        req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        using var resp = await SendAsync(req, ct);
        return (await resp.Content.ReadFromJsonAsync<AgentConfigDto>(AgentJson.Options, ct))!;
    }

    public async Task<BatchResult> UploadActivityAsync(string token, ActivityBatch batch, CancellationToken ct)
    {
        using var req = new HttpRequestMessage(HttpMethod.Post, "api/agent/v1/activity")
        {
            Content = JsonContent.Create(batch, options: AgentJson.Options),
        };
        req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        using var resp = await SendAsync(req, ct);
        return (await resp.Content.ReadFromJsonAsync<BatchResult>(AgentJson.Options, ct))!;
    }

    public async Task UploadScreenshotAsync(string token, QueuedScreenshot item, CancellationToken ct)
    {
        var frame = item.Frame;
        using var form = new MultipartFormDataContent();
        form.Add(new StringContent(frame.Id.ToString("N")), "id");
        form.Add(new StringContent(item.Login), "login");
        form.Add(new StringContent(frame.TakenAt.ToString("O", CultureInfo.InvariantCulture)), "taken_at");
        form.Add(new StringContent(frame.Monitor.ToString(CultureInfo.InvariantCulture)), "monitor");
        var image = new ByteArrayContent(frame.Data);
        image.Headers.ContentType = new MediaTypeHeaderValue(frame.ContentType);
        form.Add(image, "file", "screenshot");

        using var req = new HttpRequestMessage(HttpMethod.Post, "api/agent/v1/screenshots") { Content = form };
        req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        using var resp = await SendAsync(req, ct);
    }

    private async Task<HttpResponseMessage> SendAsync(HttpRequestMessage req, CancellationToken ct)
    {
        var resp = await http.SendAsync(req, ct);
        if (resp.StatusCode == HttpStatusCode.Unauthorized)
        {
            resp.Dispose();
            throw new AgentUnauthorizedException();
        }
        if (!resp.IsSuccessStatusCode)
        {
            resp.Dispose();
            throw new HttpRequestException($"Server returned {(int)resp.StatusCode}", null, resp.StatusCode);
        }
        return resp;
    }
}
