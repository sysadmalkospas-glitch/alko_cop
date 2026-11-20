using System.Text.Json;

namespace AlkoCop.Agent.Core;

/// <summary>Постоянные данные агента: идентификатор машины и токен доступа к серверу.</summary>
public sealed record AgentState(string MachineId, string? Token, int? ComputerId);

public sealed class AgentStateStore(string path)
{
    public AgentState LoadOrCreate()
    {
        if (File.Exists(path))
        {
            try
            {
                var state = JsonSerializer.Deserialize<AgentState>(File.ReadAllText(path), AgentJson.Options);
                if (state is not null && !string.IsNullOrWhiteSpace(state.MachineId))
                {
                    return state;
                }
            }
            catch (JsonException)
            {
                // Повреждённый файл: создаём новое состояние ниже, машина перерегистрируется.
            }
        }
        var created = new AgentState(Guid.NewGuid().ToString("N"), null, null);
        Save(created);
        return created;
    }

    public void Save(AgentState state)
    {
        var dir = Path.GetDirectoryName(Path.GetFullPath(path));
        if (!string.IsNullOrEmpty(dir))
        {
            Directory.CreateDirectory(dir);
        }
        var tmp = path + ".tmp";
        File.WriteAllText(tmp, JsonSerializer.Serialize(state, AgentJson.Options));
        File.Move(tmp, path, overwrite: true);
    }
}
