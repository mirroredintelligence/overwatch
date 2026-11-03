'use client';

import { useEffect } from 'react';

// Inline style attributes are blocked by the strict style policy (lib/security/csp.ts), which allows
// style sheets only. So a component that needs a value computed at render time puts it in a `data-css`
// attribute, as JSON, and this component copies it onto the element through the CSS object model, which
// the policy allows. It runs once for the page, and again for any element that is added or changed.
// The values are numbers and strings from our own render, never from a request, and a script is never
// read from them.

function kebab(key: string): string {
  return key.startsWith('--') ? key : key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
}

function apply(element: HTMLElement): void {
  const raw = element.dataset.css;
  if (raw === undefined) return;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return;
  }
  if (typeof parsed !== 'object' || parsed === null) return;
  for (const [key, value] of Object.entries(parsed)) {
    if (typeof value === 'string' || typeof value === 'number') {
      element.style.setProperty(kebab(key), String(value));
    }
  }
}

export function InlineStyles() {
  useEffect(() => {
    document.querySelectorAll<HTMLElement>('[data-css]').forEach(apply);
    const observer = new MutationObserver((records) => {
      for (const record of records) {
        if (record.type === 'attributes' && record.target instanceof HTMLElement) {
          apply(record.target);
        }
        record.addedNodes.forEach((node) => {
          if (!(node instanceof HTMLElement)) return;
          if (node.matches('[data-css]')) apply(node);
          node.querySelectorAll<HTMLElement>('[data-css]').forEach(apply);
        });
      }
    });
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['data-css'] });
    return () => observer.disconnect();
  }, []);
  return null;
}
