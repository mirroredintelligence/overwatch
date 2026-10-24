import { axe } from 'vitest-axe';

// jsdom has no canvas, so axe's colour-contrast rule cannot run here.
// Contrast is checked against the real rendering in the Playwright suite.
export function runAxe(element: Element) {
  return axe(element, { rules: { 'color-contrast': { enabled: false } } });
}
