namespace AlkoCop.Agent.Service;

/// <summary>Настройки агента (appsettings.json рядом со службой).</summary>
public sealed class AgentOptions
{
    /// <summary>Адрес сервера, например https://alkocop.clinic.local:8000/</summary>
    public string ServerUrl { get; set; } = "";

    /// <summary>Ключ регистрации, совпадает с ALKOCOP_ENROLL_KEY на сервере.</summary>
    public string EnrollKey { get; set; } = "";

    /// <summary>Каталог с очередью и состоянием агента.</summary>
    public string DataDirectory { get; set; } =
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "AlkoCop");

    /// <summary>Путь к сборщику; по умолчанию рядом со службой.</summary>
    public string? CollectorPath { get; set; }
}
