interface TimerScheduler {
  set: (callback: () => void, delay: number) => number;
  clear: (timer: number) => void;
}

const scheduler: TimerScheduler = {
  set: (callback, delay) => window.setTimeout(callback, delay),
  clear: (timer) => window.clearTimeout(timer),
};

export class TooltipController<Target extends object> {
  private pendingTimer: number | undefined;
  private closingTimer: number | undefined;
  private visibleTarget: Target | null = null;
  private readonly delay: number;
  private readonly onChange: (target: Target | null) => void;
  private readonly timers: TimerScheduler;

  constructor(
    delay: number,
    onChange: (target: Target | null) => void,
    timers: TimerScheduler = scheduler,
  ) {
    this.delay = delay;
    this.onChange = onChange;
    this.timers = timers;
  }

  show(target: Target, keyboard = false): void {
    this.keepOpen();
    if (this.pendingTimer != null) this.timers.clear(this.pendingTimer);
    this.pendingTimer = undefined;
    if (this.visibleTarget === target) return;
    const open = () => {
      this.pendingTimer = undefined;
      this.visibleTarget = target;
      this.onChange(target);
    };
    if (keyboard) open();
    else this.pendingTimer = this.timers.set(open, this.delay);
  }

  keepOpen(): void {
    if (this.closingTimer != null) this.timers.clear(this.closingTimer);
    this.closingTimer = undefined;
  }

  hideSoon(): void {
    if (this.pendingTimer != null) this.timers.clear(this.pendingTimer);
    this.pendingTimer = undefined;
    this.keepOpen();
    this.closingTimer = this.timers.set(() => this.hide(), 300);
  }

  hide(): void {
    if (this.pendingTimer != null) this.timers.clear(this.pendingTimer);
    if (this.closingTimer != null) this.timers.clear(this.closingTimer);
    this.pendingTimer = undefined;
    this.closingTimer = undefined;
    this.visibleTarget = null;
    this.onChange(null);
  }

  dispose(): void {
    this.hide();
  }
}
