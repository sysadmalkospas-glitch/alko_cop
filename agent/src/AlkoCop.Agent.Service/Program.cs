using AlkoCop.Agent.Core;
using AlkoCop.Agent.Service;
using Microsoft.Extensions.Hosting.WindowsServices;
using Microsoft.Extensions.Options;

var builder = Host.CreateApplicationBuilder(args);
builder.Services.AddWindowsService(o => o.ServiceName = "AlkoCopAgent");
if (WindowsServiceHelpers.IsWindowsService())
{
    // Своя реализация, чтобы получать события входа, выхода и блокировки сессий.
    builder.Services.AddSingleton<IHostLifetime, AgentServiceLifetime>();
}

builder.Services.Configure<AgentOptions>(builder.Configuration.GetSection("Agent"));
builder.Services.AddSingleton(sp => new AgentRuntime(sp.GetRequiredService<IOptions<AgentOptions>>().Value));
builder.Services.AddHttpClient<ServerClient>((sp, http) =>
{
    var url = sp.GetRequiredService<IOptions<AgentOptions>>().Value.ServerUrl;
    http.BaseAddress = new Uri(url.EndsWith('/') ? url : url + "/");
    http.Timeout = TimeSpan.FromSeconds(30);
});
builder.Services.AddHostedService<PipeServerWorker>();
builder.Services.AddHostedService<SyncWorker>();
builder.Services.AddHostedService<HeartbeatWorker>();
builder.Services.AddHostedService<CollectorLauncherWorker>();

builder.Build().Run();
