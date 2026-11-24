import { Alert, AppShell, Burger, Button, Group, Paper, Stack, Text, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { lazy, Suspense, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import { ReportFilters } from "./ReportFilters";
import { signOut } from "./auth";
import type { CabinetUser } from "./auth";
import { DayChronology } from "./DayChronology";

const reports = [
  { slug: "time-tracking", title: "Учёт времени" },
  { slug: "day-structure", title: "Структура дня" },
  { slug: "day-timeline", title: "Хронометраж дня" },
  { slug: "live-overview", title: "Оперативная сводка" },
  { slug: "productivity", title: "Продуктивность" },
  { slug: "applications", title: "Программы" },
  { slug: "application-usage", title: "Работа с программами" },
  { slug: "events", title: "Системные события" },
  { slug: "timesheets", title: "Табели" },
  { slug: "screenshots", title: "Снимки экрана" },
  { slug: "search-queries", title: "Поисковые запросы" },
];

const defaultReport = "/reports/time-tracking";
const SettingsPage = lazy(() => import("./settings/SettingsPage"));

export function Cabinet({ user, onLogout }: { user: CabinetUser; onLogout: () => void }) {
  const { search } = useLocation();
  const [menuOpened, { toggle, close }] = useDisclosure();
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState(false);
  const home = { pathname: defaultReport, search };

  async function logout() {
    if (loggingOut) return;
    setLogoutError(false);
    setLoggingOut(true);
    try {
      await signOut();
      onLogout();
    } catch {
      setLogoutError(true);
    } finally {
      setLoggingOut(false);
    }
  }

  return (
    <AppShell
      header={{ height: 64 }}
      navbar={{ width: 248, breakpoint: "sm", collapsed: { mobile: !menuOpened } }}
      padding={{ base: "md", md: "xl" }}
    >
      <AppShell.Header className="cabinet-header">
        <Group justify="space-between" h="100%" px={{ base: "md", md: "xl" }} wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger
              opened={menuOpened}
              onClick={toggle}
              hiddenFrom="sm"
              size="sm"
              color="white"
              aria-label={menuOpened ? "Закрыть меню" : "Открыть меню"}
              aria-expanded={menuOpened}
              aria-controls="cabinet-nav"
            />
            <Link className="brand-link" to={home} onClick={close}>AlkoCop</Link>
          </Group>
          <Group gap="sm" wrap="nowrap">
            <Text size="sm" className="cabinet-user" title={user.login}>{user.login}</Text>
            <Button variant="white" size="compact-sm" loading={loggingOut} onClick={logout}>
              Выйти
            </Button>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar id="cabinet-nav" p="md" className="cabinet-navbar" aria-label="Навигация кабинета">
        <Text component="h2" className="nav-heading">Отчёты</Text>
        {reports.map(({ slug, title }) => (
          <NavLink key={slug} to={{ pathname: `/reports/${slug}`, search }} className="nav-link" onClick={close}>
            {title}
          </NavLink>
        ))}
        <div className="nav-divider" />
        <NavLink to={{ pathname: "/settings", search }} className="nav-link" onClick={close}>
          Настройки
        </NavLink>
      </AppShell.Navbar>

      <AppShell.Main className="cabinet-main">
        <Stack className="cabinet-content" gap="lg">
          {logoutError && (
            <Alert color="red" role="alert">Не удалось завершить сеанс. Повторите выход.</Alert>
          )}
          <Routes>
            <Route path="/" element={<Navigate to={home} replace />} />
            <Route path="/reports/:slug" element={<ReportPage />} />
            <Route path="/settings/*" element={(
              <Suspense fallback={<Text role="status">Загрузка настроек</Text>}>
                <SettingsPage />
              </Suspense>
            )} />
            <Route path="*" element={<MissingPage />} />
          </Routes>
        </Stack>
      </AppShell.Main>
    </AppShell>
  );
}

function ReportPage() {
  const { slug } = useParams();
  const report = reports.find((item) => item.slug === slug);

  if (!report) return <MissingPage />;

  return (
    <>
      <Title order={1} className="page-heading">{report.title}</Title>
      {slug === "day-timeline" ? <DayChronology /> : (
        <>
          <ReportFilters />
          <Paper withBorder p="lg" className="empty-panel">
            <Text c="dimmed">Данные отчёта пока недоступны.</Text>
          </Paper>
        </>
      )}
    </>
  );
}

function MissingPage() {
  const { search } = useLocation();
  return (
    <>
      <Title order={1} className="page-heading">Страница не найдена</Title>
      <Link to={{ pathname: defaultReport, search }}>Перейти к отчётам</Link>
    </>
  );
}
