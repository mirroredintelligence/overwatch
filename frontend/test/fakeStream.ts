import type { StreamSource } from '@/lib/board/useBoardFeed';

// A stand-in for the browser's EventSource, driven by the test.
export class FakeStream implements StreamSource {
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closed = false;
  private readonly listeners = new Map<string, ((event: MessageEvent) => void)[]>();

  addEventListener(type: string, listener: (event: MessageEvent) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  listenerNames(): string[] {
    return [...this.listeners.keys()];
  }

  close(): void {
    this.closed = true;
    this.readyState = 2;
  }

  /** The connection is open (first time, or after a reconnect). */
  open(): void {
    this.readyState = 1;
    this.onopen?.(new Event('open'));
  }

  /** The connection failed. The browser keeps retrying unless it gave up (`gaveUp`). */
  fail(gaveUp = false): void {
    this.readyState = gaveUp ? 2 : 0;
    this.onerror?.(new Event('error'));
  }

  /** A named event from the server. */
  emit(type: string, data = '{"serviceId":"svc-ucr-west"}'): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener(new MessageEvent(type, { data }));
    }
  }
}
