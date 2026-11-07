import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { byEl } from '@/test/el';
import { resetLeadPosts } from '@/test/msw/handlers/lead';

vi.mock('next/navigation', () => ({ usePathname: () => '/lead/services/s-virtual-ward/roster' }));

import { AppShell } from '@/components/shell/AppShell';
import { RosterManager } from './RosterManager';

// Printing the check-in code (DEC-1346): the sheet is the only thing on the paper. jsdom cannot print, so this holds
// the markup (everything round the sheet carries data-noprint, the sheet does not) and the rules in the stylesheets
// that act on it. The rendered result is checked in a browser with print media emulated (see the delivery notes).

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'overwatch_csrf=csrf-for-the-print; path=/';
});

const read = (relative: string) => readFileSync(resolve(__dirname, '../..', relative), 'utf8');

async function rosterWithCode() {
  const user = userEvent.setup();
  const view = render(
    <AppShell role="lead" organisation="UCR West">
      <RosterManager serviceId="s-virtual-ward" />
    </AppShell>,
  );
  await screen.findByText('Ana Duty');
  await user.click(byEl('LEAD-CHECKIN-MAKE-BTN'));
  await screen.findByRole('img', { name: /QR code to check in/ });
  return view;
}

describe('printing the check-in code', () => {
  it('marks the shell chrome and every part of the page except the sheet as not for print', async () => {
    const { container } = await rosterWithCode();
    expect(byEl('RAIL')).toHaveAttribute('data-noprint');
    expect(byEl('APP-HEADER')).toHaveAttribute('data-noprint');

    const sheet = container.querySelector('[data-print]');
    expect(sheet).not.toBeNull();
    expect(sheet?.closest('[data-noprint]')).toBeNull();
    expect(sheet?.querySelector('[data-noprint]')).toBeNull();
    expect(sheet).toHaveTextContent('UCR West');
    expect(sheet).toHaveTextContent('Scan to go on or off shift.');

    // Nothing that has content is outside the sheet and also outside a data-noprint branch.
    const leaks = [...container.querySelectorAll('h1, h2, p, a, button, form, nav, ul, header')].filter(
      (el) => !el.closest('[data-print]') && !el.contains(sheet) && !el.closest('[data-noprint]'),
    );
    expect(leaks.map((el) => el.outerHTML.slice(0, 80))).toEqual([]);
  });

  it('keeps the code card heading, note and buttons off the paper too', async () => {
    await rosterWithCode();
    const card = byEl('LEAD-CHECKIN');
    expect(card.querySelector('h2')).toHaveAttribute('data-noprint');
    expect(byEl('LEAD-CHECKIN-PRINT-BTN').closest('[data-noprint]')).not.toBeNull();
    expect(byEl('LEAD-ROSTER').closest('[data-noprint]')).not.toBeNull();
  });
});

describe('the print rules', () => {
  it('hides data-noprint, in print only, on a page that holds a [data-print] sheet', () => {
    const css = read('app/tokens.css');
    const block = css.slice(css.indexOf('@media print'));
    expect(block).toMatch(/body:has\(\[data-print\]\) \[data-noprint\]\s*\{\s*display:\s*none\s*!important/);
  });

  it('sets the sheet black on white, centred, about 12cm wide, on one page', () => {
    const css = read('components/lead/CheckInCode.module.css');
    const block = css.slice(css.lastIndexOf('@media print'));
    expect(block).toMatch(/\.qr\s*\{[^}]*width:\s*12cm/);
    expect(block).toMatch(/text-align:\s*center/);
    expect(block).toMatch(/justify-content:\s*center/);
    expect(block).toMatch(/color:\s*#000/);
    expect(block).toMatch(/background:\s*#fff/);
    expect(block).toMatch(/break-inside:\s*avoid/);
  });

  it('leaves no print rule in the roster stylesheet that hides by class', () => {
    expect(read('components/lead/RosterManager.module.css')).not.toMatch(/@media print/);
  });
});
