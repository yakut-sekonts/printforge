import React from "react";
import type { TemplateDef } from "./types";
import { IconCube, IconCylinder, IconSphere } from "./icons";

interface Props {
  templates: TemplateDef[];
  onCreate: (template: TemplateDef) => void;
}

function iconFor(templateId: string): React.ReactNode {
  if (templateId === "cylinder") return <IconCylinder />;
  if (templateId === "sphere") return <IconSphere />;
  return <IconCube />;
}

export function PrimitivePicker({ templates, onCreate }: Props) {
  const primitives = templates.filter((template) => template.kind === "primitive");
  return (
    <details className="scene-shape-picker">
      <summary className="btn btn-primary">+ Форма</summary>
      <div className="scene-shape-menu" aria-label="Добавить базовую форму">
        <strong>Добавить форму</strong>
        <span>Она станет отдельным телом. Затем её можно переместить, объединить или вычесть.</span>
        {primitives.map((template) => (
          <button
            key={template.template_id}
            className="scene-shape-option"
            data-cmd={template.command_id}
            aria-label={`Добавить: ${template.title}`}
            onClick={(event) => {
              onCreate(template);
              (event.currentTarget.closest("details") as HTMLDetailsElement | null)?.removeAttribute("open");
            }}
          >
            {iconFor(template.template_id)}
            <span>{template.title}</span>
          </button>
        ))}
      </div>
    </details>
  );
}
