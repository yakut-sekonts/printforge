import assert from "node:assert/strict";
import test from "node:test";
import { revealCommand } from "../src/revealCommand.ts";

class FakeElement {
  dataset: { cmd?: string } = {};
  parentElement: FakeElement | null = null;
  tagName = "BUTTON";
  open = false;
  hidden = false;
  cssHidden = false;
  isDisabled = false;
  title = "";
  focused = false;
  scrolled = false;
  clicks = 0;
  classes = new Set<string>();
  classList = { add: (value: string) => this.classes.add(value), remove: (value: string) => this.classes.delete(value) };
  ownerDocument = { defaultView: { getComputedStyle: () => ({ visibility: this.cssHidden ? "hidden" : "visible" }) } };
  getClientRects(): object[] {
    for (let current: FakeElement | null = this; current; current = current.parentElement) {
      if (current.hidden || current.cssHidden || current.tagName === "DETAILS" && !current.open) return [];
    }
    return [{}];
  }
  closest(): FakeElement | null {
    for (let current: FakeElement | null = this; current; current = current.parentElement) if (current.hidden) return current;
    return null;
  }
  matches(selector: string): boolean { return selector === ":disabled" ? this.isDisabled : this.tagName === "BUTTON"; }
  getAttribute(): string | null { return null; }
  querySelector(): null { return null; }
  scrollIntoView(): void { this.scrolled = true; }
  focus(): void { this.focused = true; }
  click(): void { this.clicks++; }
}

function scope(...elements: FakeElement[]): ParentNode {
  return { querySelectorAll: () => elements } as unknown as ParentNode;
}

test("показ команды открывает все закрытые ancestor details и не запускает команду", (context) => {
  context.mock.method(globalThis, "setTimeout", () => 1 as unknown as ReturnType<typeof setTimeout>);
  const outer = new FakeElement();
  outer.tagName = "DETAILS";
  const inner = new FakeElement();
  inner.tagName = "DETAILS";
  inner.parentElement = outer;
  const target = new FakeElement();
  target.dataset.cmd = "op.sketch_extrude";
  target.parentElement = inner;
  const result = revealCommand("op.sketch_extrude", scope(target));
  assert.equal(result.status, "shown");
  assert.equal(outer.open, true);
  assert.equal(inner.open, true);
  assert.equal(target.focused, true);
  assert.equal(target.scrolled, true);
  assert.equal(target.classes.has("cmd-highlight"), true);
  assert.equal(target.clicks, 0);
});

test("видимая доступная копия команды предпочтительнее скрытой и disabled", (context) => {
  context.mock.method(globalThis, "setTimeout", () => 1 as unknown as ReturnType<typeof setTimeout>);
  const hidden = new FakeElement();
  hidden.dataset.cmd = "file.save";
  hidden.cssHidden = true;
  const disabled = new FakeElement();
  disabled.dataset.cmd = "file.save";
  disabled.isDisabled = true;
  const enabled = new FakeElement();
  enabled.dataset.cmd = "file.save";
  const result = revealCommand("file.save", scope(hidden, disabled, enabled));
  assert.equal(result.status, "shown");
  assert.equal(enabled.focused, true);
  assert.equal(disabled.focused, false);
  assert.equal(hidden.focused, false);
});

test("отсутствующая команда, CSS-hidden панель и disabled имеют явные причины", () => {
  const absent = revealCommand("nonexistent", scope());
  assert.equal(absent.status, "unavailable");
  assert.match(absent.message, /нет в интерфейсе/);
  const hidden = new FakeElement();
  hidden.dataset.cmd = "op.fillet";
  hidden.cssHidden = true;
  assert.match(revealCommand("op.fillet", scope(hidden)).message, /скрытой панели/);
  const disabled = new FakeElement();
  disabled.dataset.cmd = "op.fillet";
  disabled.isDisabled = true;
  disabled.title = "Сначала выберите ребро";
  assert.deepEqual(revealCommand("op.fillet", scope(disabled)), { status: "unavailable", message: disabled.title });
  assert.equal(disabled.clicks, 0);
});

test("идентификатор сравнивается как значение, а не вставляется в CSS selector", () => {
  const target = new FakeElement();
  target.dataset.cmd = "op.fillet";
  assert.equal(revealCommand('op.fillet"] , button', scope(target)).status, "unavailable");
  assert.equal(target.focused, false);
  assert.equal(target.clicks, 0);
});
