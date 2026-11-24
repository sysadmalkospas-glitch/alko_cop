import { Paper, Text, Title } from "@mantine/core";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ComputersDirectory, EmployeesDirectory, GroupsDirectory, OfficesDirectory, PositionsDirectory } from "./Directories";
import { UnknownLoginsDirectory } from "./Logins";
import "./settings.css";

const pages = [
  { path: "offices", title: "Офисы", component: OfficesDirectory },
  { path: "groups", title: "Группы", component: GroupsDirectory },
  { path: "positions", title: "Должности", component: PositionsDirectory },
  { path: "employees", title: "Сотрудники", component: EmployeesDirectory },
  { path: "computers", title: "Компьютеры", component: ComputersDirectory },
  { path: "unknown-logins", title: "Неизвестные логины", component: UnknownLoginsDirectory },
];

export default function SettingsPage() {
  const { search } = useLocation();
  return (
    <>
      <Title order={1} className="page-heading">Настройки</Title>
      <nav className="directory-nav" aria-label="Разделы настроек">
        {pages.map(({ path, title }) => (
          <NavLink key={path} to={{ pathname: `/settings/${path}`, search }} end>{title}</NavLink>
        ))}
      </nav>
      <Routes>
        <Route index element={<Navigate to={{ pathname: "/settings/offices", search }} replace />} />
        {pages.map(({ path, component: Screen }) => <Route key={path} path={path} element={<Screen />} />)}
        <Route path="*" element={<Paper withBorder p="lg"><Text>Раздел настроек не найден.</Text></Paper>} />
      </Routes>
    </>
  );
}
