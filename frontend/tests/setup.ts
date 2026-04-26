import "@testing-library/jest-dom/vitest";

// happy-dom does not implement EventSource. Provide a noop shim so
// useJobEvents can be exercised in unit tests without crashing.
class FakeEventSource {
  url: string;
  withCredentials = false;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
  }
  addEventListener(): void {}
  removeEventListener(): void {}
  close(): void {}
}
// @ts-expect-error attach to global
globalThis.EventSource = FakeEventSource;
