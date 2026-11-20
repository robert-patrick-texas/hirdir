import { describe, expect, it } from "vitest";
import { waitAfter, waitAsTold, watchEvery } from "./watch";

/** A clock that is moved by hand, with the timers that go off as it moves. */
function clock() {
  let at = 0;
  let made = 0;
  const timers = new Map<number, { due: number; run: () => void }>();
  return {
    now: () => at,
    setTimer(run: () => void, wait: number) {
      made += 1;
      timers.set(made, { due: at + wait, run });
      return made;
    },
    clearTimer(timer: unknown) {
      timers.delete(timer as number);
    },
    /** Move on, each timer going off at its own time and in order. */
    async pass(milliseconds: number) {
      const end = at + milliseconds;
      for (;;) {
        const due = [...timers.entries()]
          .filter(([, timer]) => timer.due <= end)
          .sort(([, one], [, other]) => one.due - other.due)[0];
        if (!due) break;
        at = Math.max(at, due[1].due);
        timers.delete(due[0]);
        due[1].run();
        await settled();
      }
      at = end;
      await settled();
    },
    waiting: () => timers.size,
  };
}

/** Let what follows an answer happen. */
async function settled(): Promise<void> {
  for (let turn = 0; turn < 5; turn += 1) await Promise.resolve();
}

interface Asked {
  at: number;
  signal: AbortSignal;
  answer: () => void;
  fail: () => void;
}

/** A watch whose requests are answered by hand. */
function setup(options: { visible?: boolean } = {}) {
  const time = clock();
  const asked: Asked[] = [];
  const page = { visible: options.visible ?? true };
  const watch = watchEvery({
    every: 5000,
    giveUp: 15_000,
    visible: () => page.visible,
    now: time.now,
    setTimer: time.setTimer,
    clearTimer: time.clearTimer,
    ask: (signal) =>
      new Promise<void>((resolve, reject) => {
        asked.push({
          at: time.now(),
          signal,
          answer: resolve,
          fail: () => reject(new Error("no answer")),
        });
        signal.addEventListener("abort", () => reject(new Error("let go")));
      }),
  });
  /** Answer the request that is out, after it has taken so long. */
  async function answer(took = 0, failed = false) {
    await time.pass(took);
    const last = asked.at(-1);
    if (failed) last?.fail();
    else last?.answer();
    await settled();
  }
  return { time, asked, page, watch, answer };
}

describe("waitAfter", () => {
  it("is what is left of the time between two requests, counted from the sending", () => {
    expect(waitAfter(5000, 0, false)).toBe(5000);
    expect(waitAfter(5000, 40, false)).toBe(4960);
    expect(waitAfter(5000, 4999, false)).toBe(1);
  });

  it("is the whole of it after an answer that failed, or that took that long", () => {
    expect(waitAfter(5000, 40, true)).toBe(5000);
    expect(waitAfter(5000, 5000, false)).toBe(5000);
    expect(waitAfter(5000, 12_000, false)).toBe(5000);
    expect(waitAfter(5000, Number.NaN, false)).toBe(5000);
    // A clock that went back is no reason to wait longer than that.
    expect(waitAfter(5000, -30, false)).toBe(5000);
  });
});

describe("waitAsTold", () => {
  const busy = { health: "busy", because: [], refusing: "reads", retry_after: 5 };

  it("is the usual wait after an answer, and after a failure that is not a busy server's", () => {
    expect(waitAsTold(1000, null)).toBe(1000);
    expect(waitAsTold(1000, { busy: null, retryAfter: null })).toBe(1000);
    // The one writer was busy for a moment: its seconds are not a busy server's.
    expect(waitAsTold(1000, { busy: null, retryAfter: 9 })).toBe(1000);
  });

  it("is as long as a busy server says, where that is longer", () => {
    expect(waitAsTold(1000, { busy, retryAfter: 5 })).toBe(5000);
    expect(waitAsTold(2000, { busy, retryAfter: 5 })).toBe(5000);
    expect(waitAsTold(8000, { busy, retryAfter: 5 })).toBe(8000);
    expect(waitAsTold(1000, { busy, retryAfter: null })).toBe(1000);
    expect(waitAsTold(1000, { busy, retryAfter: 0 })).toBe(1000);
  });
});

describe("watchEvery", () => {
  it("asks at once, and again every five seconds from when it last asked", async () => {
    const { time, asked, watch, answer } = setup();
    watch.start();
    expect(asked.map((one) => one.at)).toEqual([0]);
    await answer(40);
    await time.pass(4959);
    expect(asked).toHaveLength(1);
    await time.pass(1);
    expect(asked.map((one) => one.at)).toEqual([0, 5000]);
    await answer(200);
    await time.pass(4800);
    expect(asked.map((one) => one.at)).toEqual([0, 5000, 10_000]);
  });

  it("never has two requests out, however long an answer takes", async () => {
    const { time, asked, watch, answer } = setup();
    watch.start();
    await time.pass(12_000);
    expect(asked).toHaveLength(1);
    watch.look();
    watch.look();
    expect(asked).toHaveLength(1);
    // The slow answer comes: the next is asked a whole five seconds after it.
    await answer();
    await time.pass(4999);
    expect(asked).toHaveLength(1);
    await time.pass(1);
    expect(asked.map((one) => one.at)).toEqual([0, 17_000]);
  });

  it("waits the whole five seconds after a request that failed", async () => {
    const { time, asked, watch, answer } = setup();
    watch.start();
    await answer(100, true);
    await time.pass(4999);
    expect(asked).toHaveLength(1);
    await time.pass(1);
    expect(asked.map((one) => one.at)).toEqual([0, 5100]);
    // And goes on asking, one at a time, while they fail.
    await answer(0, true);
    await time.pass(5000);
    expect(asked.map((one) => one.at)).toEqual([0, 5100, 10_100]);
  });

  it("gives up a request with no answer in fifteen seconds, and asks again later", async () => {
    const { time, asked, watch } = setup();
    watch.start();
    await time.pass(14_999);
    expect(asked[0]?.signal.aborted).toBe(false);
    await time.pass(1);
    expect(asked[0]?.signal.aborted).toBe(true);
    expect(asked).toHaveLength(1);
    await time.pass(5000);
    expect(asked.map((one) => one.at)).toEqual([0, 20_000]);
  });

  it("asks nothing while the page is hidden, and once at once on coming back", async () => {
    const { time, asked, page, watch, answer } = setup();
    watch.start();
    await answer(10);
    page.visible = false;
    watch.look();
    expect(time.waiting()).toBe(0);
    await time.pass(60_000);
    expect(asked).toHaveLength(1);
    page.visible = true;
    watch.look();
    expect(asked.map((one) => one.at)).toEqual([0, 60_010]);
    await answer(10);
    await time.pass(4990);
    expect(asked.map((one) => one.at)).toEqual([0, 60_010, 65_010]);
  });

  it("asks nothing when it starts hidden, until the page comes to the front", async () => {
    const { time, asked, page, watch } = setup({ visible: false });
    watch.start();
    await time.pass(20_000);
    expect(asked).toHaveLength(0);
    page.visible = true;
    watch.look();
    expect(asked).toHaveLength(1);
  });

  it("asks at once on coming to the front again, and is then five seconds from that", async () => {
    const { time, asked, watch, answer } = setup();
    watch.start();
    await answer(10);
    await time.pass(2000);
    // The browser says the tab is in front again while a request is two seconds old.
    watch.look();
    expect(asked.map((one) => one.at)).toEqual([0, 2010]);
    await answer(10);
    await time.pass(2990);
    // The request that was due at five seconds is not asked as well.
    expect(asked).toHaveLength(2);
    await time.pass(2000);
    expect(asked.map((one) => one.at)).toEqual([0, 2010, 7010]);
  });

  it("schedules nothing after an answer that comes while the page is hidden", async () => {
    const { time, asked, page, watch, answer } = setup();
    watch.start();
    page.visible = false;
    watch.look();
    await answer(300);
    expect(time.waiting()).toBe(0);
    await time.pass(30_000);
    expect(asked).toHaveLength(1);
  });

  it("lets go of what it asked when it stops, and asks nothing more", async () => {
    const { time, asked, watch } = setup();
    watch.start();
    watch.stop();
    expect(asked[0]?.signal.aborted).toBe(true);
    await time.pass(60_000);
    watch.look();
    watch.start();
    expect(asked).toHaveLength(1);
  });

  it("takes a request that could not be sent for one that failed", async () => {
    const time = clock();
    let asked = 0;
    const watch = watchEvery({
      every: 5000,
      giveUp: 15_000,
      visible: () => true,
      now: time.now,
      setTimer: time.setTimer,
      clearTimer: time.clearTimer,
      ask: () => {
        asked += 1;
        throw new Error("could not be sent");
      },
    });
    watch.start();
    await settled();
    expect(asked).toBe(1);
    await time.pass(5000);
    expect(asked).toBe(2);
  });
});
