import assert from "node:assert/strict";
import test from "node:test";
import { TooltipController } from "../src/tooltipController.ts";

class FakeClock {
  now = 0;
  nextId = 1;
  tasks = new Map<number, { at: number; callback: () => void }>();
  set = (callback: () => void, delay: number): number => {
    const id = this.nextId++;
    this.tasks.set(id, { at: this.now + delay, callback });
    return id;
  };
  clear = (id: number): void => { this.tasks.delete(id); };
  advance(milliseconds: number): void {
    const end = this.now + milliseconds;
    while (true) {
      const next = [...this.tasks].filter(([, task]) => task.at <= end).sort((first, second) => first[1].at - second[1].at)[0];
      if (!next) break;
      this.now = next[1].at;
      this.tasks.delete(next[0]);
      next[1].callback();
    }
    this.now = end;
  }
}

test("уход до задержки не открывает подсказку для старого элемента", () => {
  const clock = new FakeClock();
  const updates: Array<object | null> = [];
  const controller = new TooltipController(350, (target) => updates.push(target), clock);
  controller.show({ command: "box" });
  clock.advance(349);
  assert.deepEqual(updates, []);
  controller.hideSoon();
  clock.advance(1000);
  assert.deepEqual(updates, [null]);
});

test("переход с кнопки в tooltip сохраняет ссылку доступной для нажатия", () => {
  const clock = new FakeClock();
  const updates: Array<object | null> = [];
  const controller = new TooltipController(350, (target) => updates.push(target), clock);
  const anchor = { command: "fillet" };
  controller.show(anchor);
  clock.advance(350);
  controller.hideSoon();
  clock.advance(100);
  controller.keepOpen();
  clock.advance(5000);
  assert.deepEqual(updates, [anchor]);
  controller.hideSoon();
  clock.advance(300);
  assert.deepEqual(updates, [anchor, null]);
});

test("keyboard focus открывает сразу и отменяет pending hover другого элемента", () => {
  const clock = new FakeClock();
  const updates: Array<object | null> = [];
  const controller = new TooltipController(500, (target) => updates.push(target), clock);
  const first = { command: "save" };
  const second = { command: "export" };
  controller.show(first, true);
  assert.deepEqual(updates, [first]);
  controller.show(second);
  clock.advance(100);
  controller.show(first, true);
  clock.advance(1000);
  assert.deepEqual(updates, [first]);
});

test("Escape и unmount удаляют все show/hide timers", () => {
  const clock = new FakeClock();
  const updates: Array<object | null> = [];
  const controller = new TooltipController(350, (target) => updates.push(target), clock);
  controller.show({ command: "save" });
  controller.hide();
  assert.equal(clock.tasks.size, 0);
  controller.show({ command: "save" }, true);
  controller.hideSoon();
  controller.dispose();
  const count = updates.length;
  clock.advance(10000);
  assert.equal(updates.length, count);
  assert.equal(updates.at(-1), null);
  assert.equal(clock.tasks.size, 0);
});
