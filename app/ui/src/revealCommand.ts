export interface CommandRevealResult {
  status: "shown" | "unavailable";
  message: string;
}

function visible(element: HTMLElement): boolean {
  return element.getClientRects().length > 0 && !element.closest("[hidden]")
    && element.ownerDocument.defaultView?.getComputedStyle(element).visibility !== "hidden";
}

function disabled(element: HTMLElement): boolean {
  return element.matches(":disabled") || element.getAttribute("aria-disabled") === "true";
}

export function revealCommand(commandId: string, scope: ParentNode = document): CommandRevealResult {
  const candidates = [...scope.querySelectorAll<HTMLElement>("[data-cmd]")]
    .filter((element) => element.dataset.cmd === commandId);
  if (!candidates.length) {
    return { status: "unavailable", message: "Этой команды сейчас нет в интерфейсе. Проверьте условия выбора в статье и выберите нужную деталь или область модели." };
  }
  const element = candidates.find((candidate) => visible(candidate) && !disabled(candidate))
    ?? candidates.find((candidate) => !disabled(candidate)) ?? candidates[0];
  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    if (parent.tagName === "DETAILS") (parent as HTMLDetailsElement).open = true;
  }
  if (!visible(element)) {
    return { status: "unavailable", message: "Команда находится в скрытой панели. Увеличьте ширину окна или откройте нужную панель; справочник можно закрыть кнопкой в его заголовке." };
  }
  element.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  if (disabled(element)) {
    return { status: "unavailable", message: element.title || "Команда сейчас недоступна. Сначала выполните условия выбора, указанные в статье." };
  }
  const focusTarget = element.matches("button, input, select, textarea, a[href], [tabindex]")
    ? element : element.querySelector<HTMLElement>("button, input, select, textarea, a[href], [tabindex]");
  focusTarget?.focus({ preventScroll: true });
  element.classList.add("cmd-highlight");
  setTimeout(() => element.classList.remove("cmd-highlight"), 1200);
  return { status: "shown", message: "Команда показана и выделена в интерфейсе. Действие не выполнялось." };
}
