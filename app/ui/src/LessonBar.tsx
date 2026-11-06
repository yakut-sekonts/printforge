import React from "react";
import { IconCheck } from "./icons";
import { lessonMastered } from "./lessonEngine";
import type { LessonRun } from "./lessonEngine";
export type { LessonRun, StepStatus } from "./lessonEngine";

interface Props {
  run: LessonRun;
  onSkip: () => void;
  onTogglePause: () => void;
  onExit: () => void;
  onRestart: () => void;
  onInspect?: () => void;
}

export function LessonBar({ run, onSkip, onTogglePause, onExit, onRestart, onInspect }: Props) {
  const step = run.lesson.steps[run.stepIndex];
  const finished = run.stepIndex >= run.lesson.steps.length;
  const mastered = lessonMastered(run.statuses);
  const skipped = run.statuses.filter((status) => status === "skipped").length;
  return (
    <div className="lesson-bar" role="region" aria-label="Панель урока">
      <div className="lesson-meta">
        <span className="lesson-count">Урок {run.lessonIndex + 1} из {run.totalLessons}</span>
        <span className="lesson-title">{run.lesson.title}</span>
      </div>
      <ol className="lesson-progress" aria-label="Состояние шагов урока">
        {run.statuses.map((status, index) => (
          <li key={run.lesson.steps[index].id} className={`lesson-progress-step status-${status}`} aria-current={index === run.stepIndex ? "step" : undefined}>
            <span>Шаг {index + 1}</span>
            <span>{status === "done" ? "выполнен" : status === "skipped" ? "пропущен" : "ожидает"}</span>
          </li>
        ))}
      </ol>
      {finished ? (
        <div className="lesson-step">
          <span className="lesson-step-text">
            {mastered ? <><span className="lesson-check done"><IconCheck /></span> Все задания выполнены.</> : `Просмотр урока завершён. Пропущено заданий: ${skipped}. Повторите урок, чтобы выполнить их.`}
          </span>
        </div>
      ) : (
        <div className="lesson-step">
          <span className="lesson-step-num">Шаг {run.stepIndex + 1} из {run.lesson.steps.length}</span>
          <span className="lesson-step-text">{step.text}</span>
          {run.statuses[run.stepIndex] === "skipped" && <span className="pill pill-warning">пропущен</span>}
          {run.statuses[run.stepIndex] === "done" && <span className="lesson-check done"><IconCheck /></span>}
          {run.paused && <span className="pill">пауза</span>}
        </div>
      )}
      <div className="lesson-actions">
        {!finished && onInspect && (step.check.type === "inspection" || step.check.type === "mesh_inspected") && (
          <button className="btn btn-primary" aria-label="Подтвердить проверку" onClick={onInspect} disabled={run.paused}>Подтвердить проверку</button>
        )}
        {!finished && <button className="btn" data-cmd="lesson.skip" aria-label="Пропустить шаг" onClick={onSkip}>Пропустить</button>}
        {!finished && <button className="btn" data-cmd="lesson.pause" aria-label={run.paused ? "Продолжить урок" : "Поставить урок на паузу"} onClick={onTogglePause}>
          {run.paused ? "Продолжить" : "Пауза"}
        </button>}
        <button className="btn" data-cmd="lesson.restart" aria-label="Повторить урок" onClick={onRestart}>Повторить урок</button>
        <button className="btn" data-cmd="lesson.exit" aria-label="Выйти из урока" onClick={onExit}>Выйти</button>
      </div>
    </div>
  );
}
