'use client';

import { createElement, useLayoutEffect, useRef, type ComponentPropsWithoutRef, type CSSProperties } from 'react';

// A value that is only known at run time (a bar's width, a pin's place) cannot be a class, and the
// content security policy (style-src 'self' 'nonce-...') refuses a style attribute in the markup the
// server sends. The browser does allow the style object's own properties to be set from script, so the
// value is set there, once the element exists: the element is in the markup without it, and takes it
// before the first paint. The text of every such element is in the markup, so nothing that is read
// depends on the value; only the picture does.

function apply(element: HTMLElement, css: CSSProperties, previous: Set<string>): Set<string> {
  const keys = new Set(Object.keys(css));
  for (const key of previous) {
    if (!keys.has(key)) {
      if (key.startsWith('--')) element.style.removeProperty(key);
      else (element.style as unknown as Record<string, string>)[key] = '';
    }
  }
  for (const [key, value] of Object.entries(css)) {
    if (key.startsWith('--')) element.style.setProperty(key, String(value));
    else (element.style as unknown as Record<string, string>)[key] = String(value);
  }
  return keys;
}

function make<K extends 'div' | 'span' | 'td' | 'button'>(tag: K) {
  function Styled({ css, ...rest }: ComponentPropsWithoutRef<K> & { css: CSSProperties }) {
    const ref = useRef<HTMLElement | null>(null);
    const applied = useRef<Set<string>>(new Set());
    const signature = JSON.stringify(css);
    useLayoutEffect(() => {
      if (ref.current) applied.current = apply(ref.current, JSON.parse(signature) as CSSProperties, applied.current);
    }, [signature]);
    return createElement(tag, { ...rest, ref });
  }
  Styled.displayName = `Styled(${tag})`;
  return Styled;
}

export const StyledDiv = make('div');
export const StyledSpan = make('span');
export const StyledTd = make('td');
export const StyledButton = make('button');
