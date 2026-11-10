import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { WorkspaceFrame, type WorkspaceFrameProps } from './WorkspaceFrame';

// The workspace frame (WS-FRM): a top bar, a thread slot on the left, the canvas, and a footer. No side rail.

function frame(props: Partial<WorkspaceFrameProps> = {}) {
  return render(
    <WorkspaceFrame
      title="Find a service"
      organisation="Test Organisation"
      signOut={vi.fn(async () => ({ signedOut: true }))}
      showSignOut
      thread={null}
      assistantButton={<button type="button">Show the assistant</button>}
      footer="Browse only"
      {...props}
    >
      <p>Canvas text</p>
    </WorkspaceFrame>,
  );
}

// The elements with a style attribute, except the logo image: next/image writes its own `color: transparent` onto
// <Logo />, which is shared and not the frame's markup (see the report).
function styledElements(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('[style]'))
    .filter((el) => !(el instanceof HTMLImageElement && el.hasAttribute('data-nimg')))
    .map((el) => el.outerHTML);
}

describe('WorkspaceFrame', () => {
  it('WS-FRM-T01 renders a banner with the title and organisation, one main landmark named Canvas holding the children, and the footer text', () => {
    frame();
    const banner = screen.getByRole('banner');
    expect(within(banner).getByText('Find a service')).toBeInTheDocument();
    expect(within(banner).getByText('Test Organisation')).toBeInTheDocument();
    const mains = screen.getAllByRole('main');
    expect(mains).toHaveLength(1);
    expect(mains[0]).toHaveAttribute('aria-label', 'Canvas');
    expect(within(mains[0]).getByText('Canvas text')).toBeInTheDocument();
    expect(screen.getByRole('contentinfo')).toHaveTextContent('Browse only');
  });

  it('WS-FRM-T02 has no navigation landmark', () => {
    frame({ backHref: '/advisor/v2', action: { label: 'Open the list', href: '/advisor/v2/services' } });
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  it('WS-FRM-T03 with backHref there is a link named Back (or backLabel) first in the banner; without it there is no such link', () => {
    const { unmount } = frame({ backHref: '/advisor/v2?mode=find&view=list' });
    const back = screen.getByRole('link', { name: 'Back' });
    expect(back).toHaveAttribute('href', '/advisor/v2?mode=find&view=list');
    expect(within(screen.getByRole('banner')).getAllByRole('link')[0]).toBe(back);
    unmount();

    frame({ backHref: '/advisor/v2', backLabel: 'Back to results' });
    expect(screen.getByRole('link', { name: 'Back to results' })).toHaveAttribute('href', '/advisor/v2');
    expect(screen.queryByRole('link', { name: 'Back' })).toBeNull();
  });

  it('WS-FRM-T04 with action there is a link with its label and href; without it none', () => {
    const { unmount } = frame({ action: { label: 'Open the list', href: '/advisor/v2/services' } });
    expect(within(screen.getByRole('banner')).getByRole('link', { name: 'Open the list' })).toHaveAttribute('href', '/advisor/v2/services');
    unmount();

    frame();
    expect(screen.queryByRole('link', { name: 'Open the list' })).toBeNull();
  });

  it('WS-FRM-T05 a single role renders its plain word with no menu; two or more roles including role render the role switcher', () => {
    const { unmount } = frame({ role: 'advisor', roles: ['advisor'], roleWords: { advisor: 'Advisor' } });
    expect(document.querySelector('[data-el="FRAME-ROLE"]')).toHaveTextContent('Advisor');
    expect(document.querySelector('details')).toBeNull();
    unmount();

    frame({ role: 'advisor', roles: ['advisor', 'lead'], roleWords: { advisor: 'Advisor', lead: 'Shift lead' } });
    expect(document.querySelector('[data-el="ROLE-SWITCHER"]')).not.toBeNull();
    expect(document.querySelector('summary')).toHaveTextContent('Advisor');
    expect(document.querySelector('[data-el="FRAME-ROLE"]')).toBeNull();
  });

  it('WS-FRM-T06 with thread there is a complementary Assistant landmark holding it and no assistant button; with thread null there is no landmark and the assistant button is rendered', () => {
    const { unmount } = frame({ thread: <div>Thread body</div> });
    const aside = screen.getByRole('complementary', { name: 'Assistant' });
    expect(within(aside).getByText('Thread body')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Show the assistant' })).toBeNull();
    unmount();

    frame({ thread: null });
    expect(screen.queryByRole('complementary')).toBeNull();
    expect(screen.getByRole('button', { name: 'Show the assistant' })).toBeInTheDocument();
  });

  it('WS-FRM-T07 showSignOut true renders the Sign out button; false renders none', () => {
    const { unmount } = frame({ showSignOut: true });
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
    unmount();

    frame({ showSignOut: false });
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull();
  });

  it('WS-FRM-T08 no element has a style attribute, and the frame passes runAxe with every prop set', async () => {
    const withThread = frame({
      backHref: '/advisor/v2?mode=find&view=list',
      backLabel: 'Back to results',
      action: { label: 'Open the list', href: '/advisor/v2/services' },
      role: 'advisor',
      roles: ['advisor', 'lead'],
      roleWords: { advisor: 'Advisor', lead: 'Shift lead' },
      signOut: vi.fn(async () => ({ signedOut: true })),
      showSignOut: true,
      thread: <div>Thread body</div>,
      assistantButton: <button type="button">Show the assistant</button>,
      footer: 'Browse only',
      organisation: 'Test Organisation',
    });
    expect(styledElements(withThread.container)).toEqual([]);
    expect(await runAxe(withThread.container)).toHaveNoViolations();
    withThread.unmount();

    const withoutThread = frame({
      backHref: '/advisor/v2',
      action: { label: 'Open the list', href: '/advisor/v2/services' },
      role: 'advisor',
      roles: ['advisor'],
      roleWords: { advisor: 'Advisor' },
      thread: null,
      footer: 'Browse only',
    });
    expect(styledElements(withoutThread.container)).toEqual([]);
    expect(await runAxe(withoutThread.container)).toHaveNoViolations();
  });
});
