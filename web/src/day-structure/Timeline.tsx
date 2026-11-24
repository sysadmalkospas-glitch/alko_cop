import { Portal } from "@mantine/core";
import { useId, useMemo, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";
import type { ActivityInterval, ActivityStatus, DayStructure, EmployeeTimeline } from "./api";

const activityLabels: Record<ActivityStatus, string> = {
  active: "Работа", idle: "Простой", no_data: "Нет данных",
};
const activityColors: Record<ActivityStatus, string> = {
  active: "var(--structure-active)", idle: "var(--structure-idle)", no_data: "var(--structure-empty)",
};
const hour = 60 * 60 * 1000;

interface Scale {
  start: number;
  end: number;
  clock: Intl.DateTimeFormat;
  ticks: { label: string; offset: number }[];
}

interface PositionedBand {
  interval: ActivityInterval;
  from: number;
  to: number;
}

interface Selection {
  index: number;
  x: number;
  y: number;
  mode: "pointer" | "keyboard";
}

function percent(value: string, start: number, end: number) {
  return 100 * (Date.parse(value) - start) / (end - start);
}

function makeScale(data: DayStructure): Scale {
  const start = Date.parse(data.starts_at);
  const end = Date.parse(data.ends_at);
  const clock = new Intl.DateTimeFormat("ru-RU", {
    timeZone: data.timezone, hourCycle: "h23", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const axisClock = new Intl.DateTimeFormat("ru-RU", {
    timeZone: data.timezone, hourCycle: "h23", hour: "2-digit", minute: "2-digit",
  });
  const ticks = [];
  for (let at = start; at < end - hour; at += 3 * hour) {
    ticks.push({ label: axisClock.format(at), offset: 100 * (at - start) / (end - start) });
  }
  ticks.push({ label: "24:00", offset: 100 });
  return { start, end, clock, ticks };
}

function intervalAt(bands: PositionedBand[], expected: number): number {
  let low = 0;
  let high = bands.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (expected < bands[middle].to) high = middle;
    else low = middle + 1;
  }
  return low;
}

export function Timeline({ data }: { data: DayStructure }) {
  const help = useId();
  const scale = useMemo(() => makeScale(data), [data]);

  return (
    <>
      <ul className="structure-legend" aria-label="Условные обозначения">
        {(Object.keys(activityLabels) as ActivityStatus[]).map((status) => (
          <li key={status}><i style={{ backgroundColor: activityColors[status] }} />{activityLabels[status]}</li>
        ))}
        <li><i className="structure-shift" />По графику</li>
        <li><i className="structure-break" />Перерыв по графику</li>
        <li className="structure-timezone">{data.timezone}</li>
      </ul>
      <p className="structure-sr-only" id={help}>Выберите отрезок мышью или клавишами со стрелками.</p>
      <div className="structure-scroll">
        <div className="structure-grid">
          <span className="structure-name structure-heading">Сотрудники</span>
          <div className="structure-axis" aria-label={"Шкала времени, " + data.timezone}>
            {scale.ticks.map(({ label, offset }) => <span key={offset} style={{ left: offset + "%" }}>{label}</span>)}
          </div>
          {data.rows.map((row) => <TimelineRow key={row.employee_id} row={row} scale={scale} help={help} />)}
        </div>
      </div>
    </>
  );
}

function TimelineRow({ row, scale, help }: { row: EmployeeTimeline; scale: Scale; help: string }) {
  const { start, end } = scale;
  const bands = useMemo(() => row.activity.map((interval) => ({
    interval, from: percent(interval.starts_at, start, end), to: percent(interval.ends_at, start, end),
  })), [row.activity, start, end]);
  const painting = useMemo(() => {
    const stops = bands.map(({ interval, from, to }) =>
      activityColors[interval.status] + " " + from.toFixed(4) + "% " + to.toFixed(4) + "%",
    );
    return "linear-gradient(to right," + stops.join(",") + ")";
  }, [bands]);
  const [selection, setSelection] = useState<Selection>();
  const tooltipId = useId();
  const band = selection && bands[selection.index];

  function inspectPointer(event: PointerEvent<HTMLDivElement>) {
    const area = event.currentTarget.getBoundingClientRect();
    if (!bands.length || area.width === 0) return;
    const offset = 100 * (event.clientX - area.left) / area.width;
    const index = intervalAt(bands, offset);
    if (index !== selection?.index || selection.mode !== "pointer") {
      setSelection({ index, x: event.clientX, y: event.clientY, mode: "pointer" });
    }
  }

  function inspectKeyboard(element: HTMLDivElement, index: number) {
    const area = element.getBoundingClientRect();
    const next = bands[index];
    if (!next) return;
    setSelection({
      mode: "keyboard", index, x: area.left + area.width * (next.from + next.to) / 200, y: area.bottom,
    });
  }

  function handleKey(event: KeyboardEvent<HTMLDivElement>) {
    const index = selection?.index ?? 0;
    let next: number;
    switch (event.key) {
      case "ArrowLeft": next = Math.max(0, index - 1); break;
      case "ArrowRight": next = Math.min(bands.length - 1, index + 1); break;
      case "Home": next = 0; break;
      case "End": next = bands.length - 1; break;
      default: return;
    }
    event.preventDefault();
    inspectKeyboard(event.currentTarget, next);
  }

  return (
    <>
      <span className="structure-name">{row.full_name}</span>
      <div
        role="group"
        className="structure-track"
        tabIndex={0}
        aria-label={row.full_name + " · отрезки активности"}
        aria-describedby={band ? help + " " + tooltipId : help}
        onPointerMove={(event) => { if (event.pointerType !== "touch") inspectPointer(event); }}
        onPointerDown={inspectPointer}
        onPointerLeave={() => { if (selection?.mode === "pointer") setSelection(undefined); }}
        onFocus={(event) => inspectKeyboard(event.currentTarget, Math.max(0, bands.findIndex(({ interval }) => interval.status !== "no_data")))}
        onBlur={() => setSelection(undefined)}
        onKeyDown={handleKey}
      >
        {row.schedule.map((part, i) => (
          <span
            key={i}
            className={"structure-plan " + (part.is_break ? "structure-break" : "structure-shift")}
            aria-hidden="true"
            style={{ left: percent(part.starts_at, start, end) + "%", right: (100 - percent(part.ends_at, start, end)) + "%" }}
          />
        ))}
        <div className="structure-activity" aria-hidden="true" style={{ backgroundImage: painting }} />
        {scale.ticks.slice(1, -1).map(({ offset }) =>
          <span key={offset} className="structure-guide" aria-hidden="true" style={{ left: offset + "%" }} />,
        )}
      </div>
      {selection && band && <BandTooltip id={tooltipId} selection={selection} band={band.interval} scale={scale} />}
    </>
  );
}

function BandTooltip({ id, selection, band, scale }: {
  id: string; selection: Selection; band: ActivityInterval; scale: Scale;
}) {
  const above = selection.y > window.innerHeight / 2;
  const starts = scale.clock.format(Date.parse(band.starts_at));
  const ends = Date.parse(band.ends_at) === scale.end ? "24:00:00" : scale.clock.format(Date.parse(band.ends_at));
  return (
    <Portal>
      <div className="structure-tooltip" role="tooltip" id={id} aria-live={selection.mode === "keyboard" ? "polite" : "off"}
        style={{
          left: "clamp(8px, " + (selection.x + 12) + "px, calc(100vw - 304px))",
          top: above ? undefined : selection.y + 10,
          bottom: above ? window.innerHeight - selection.y + 10 : undefined,
        }}>
        <strong>{activityLabels[band.status]} · {starts}–{ends}</strong>
        {band.process_name && <span>{band.process_name}</span>}
        {band.window_title && <span>{band.window_title}</span>}
      </div>
    </Portal>
  );
}
