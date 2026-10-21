import React from "react";
import type { Lesson } from "./types";
import { IconCheck } from "./icons";

export type StepStatus = "pending" | "done" | "skipped";

export interface LessonRun {
  lesson: Lesson;
  lessonIndex: number;
  totalLessons: number;
  stepIndex: number;
  statuses: StepStatus[];
  paused: boolean;
}

interface Props {
  run: LessonRun;
  onSkip: () => void;
  onTogglePause: () => void;
  onExit: () => void;
  onRestart: () => void;
}

export function LessonBar({ run, onSkip, onTogglePause, onExit, onRestart }: Props) {
  const step = run.lesson.steps[run.stepIndex];
  const finished = run.stepIndex >= run.lesson.steps.length;
  return (
    <div className="lesson-bar" role="region" aria-label="Панель урока">
      <div className="lesson-meta">
        <span className="lesson-count">Урок {run.lessonIndex + 1} из {run.totalLessons}</span>
        <span className="lesson-title">{run.lesson.title}</span>
      </div>
      {finished ? (
        <div className="lesson-step">
          <span className="lesson-step-text"><span className="lesson-check done"><IconCheck /></span> Урок завершён.</span>
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
        {!finished && <button className="btn" data-cmd="lesson.skip" aria-label="Пропустить шаг" onClick={onSkip}>Пропустить</button>}
        <button className="btn" data-cmd="lesson.pause" aria-label={run.paused ? "Продолжить урок" : "Поставить урок на паузу"} onClick={onTogglePause}>
          {run.paused ? "Продолжить" : "Пауза"}
        </button>
        <button className="btn" data-cmd="lesson.restart" aria-label="Повторить урок" onClick={onRestart}>Повторить урок</button>
        <button className="btn" data-cmd="lesson.exit" aria-label="Выйти из урока" onClick={onExit}>Выйти</button>
      </div>
    </div>
  );
}
