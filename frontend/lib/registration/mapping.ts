// Red stub (lesson L139): each mapper answers a value no test expects, so each test fails on its assertion.
import type { Decision, Overview, QueueResponse } from './types';

export function queueFromBackend(raw: unknown): QueueResponse | null {
  void raw;
  return { tab: 'waiting', counts: {}, tabs: [], items: [{ id: 'x', serviceName: 'x', state: 'x', submittedAt: 'x', submittedByRole: 'x' }] };
}

export function overviewFromBackend(raw: unknown): Overview | null {
  return raw as Overview;
}

export function decisionFromBackend(raw: unknown): Decision | null {
  void raw;
  return { missing: ['x'], approvedBy: [], test: {}, timeline: [] };
}
