import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { AssistantButton } from './AssistantButton';
import { ThreadDrawer, type ThreadChip, type ThreadMessage, type ThreadSummary } from './ThreadDrawer';

// The assistant thread drawer (DEC-1376, WS-THD). Presentational: no text box, no state of its own.

const MESSAGES: ThreadMessage[] = [
  { id: 'm1', from: 'assistant', text: 'Let us start with the age.' },
  { id: 'm2', from: 'person', text: '65 to 79' },
  { id: 'm3', from: 'assistant', text: 'What does the patient need?' },
];

const CHIPS: ThreadChip[] = [
  { label: 'List by name', href: '/advisor/v2?mode=find&view=list&order=name' },
  { label: 'Back to results', href: '/advisor/v2?mode=find&view=list' },
];

const SUMMARY: ThreadSummary = {
  line: '65 to 79 · Area One · Frailty · Today',
  changeHref: '/advisor/v2?mode=find&view=find&step=need',
};

function drawer(over: Partial<Parameters<typeof ThreadDrawer>[0]> = {}) {
  return (
    <ThreadDrawer messages={MESSAGES} summary={null} chips={[]} onHide={() => undefined} {...over} />
  );
}

describe('ThreadDrawer', () => {
  it('WS-THD-T01 renders a level-2 heading Assistant and a Hide button that calls onHide once', async () => {
    const user = userEvent.setup();
    const onHide = vi.fn();
    render(drawer({ onHide }));
    expect(screen.getByRole('heading', { level: 2, name: 'Assistant' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Hide the assistant' }));
    expect(onHide).toHaveBeenCalledTimes(1);
  });

  it('WS-THD-T02 renders messages in order, each paragraph carrying data-from', () => {
    const { container } = render(drawer());
    const paragraphs = Array.from(container.querySelectorAll('[data-from]'));
    expect(paragraphs.map((p) => p.textContent)).toEqual(MESSAGES.map((m) => m.text));
    expect(paragraphs.map((p) => p.getAttribute('data-from'))).toEqual(['assistant', 'person', 'assistant']);
    expect(paragraphs.every((p) => p.tagName === 'P')).toBe(true);
  });

  it('WS-THD-T03 the log region is named Conversation, is polite, and holds exactly the messages', () => {
    render(drawer({ summary: SUMMARY, chips: CHIPS, card: <p>Card body</p> }));
    const log = screen.getByRole('log', { name: 'Conversation' });
    expect(log).toHaveAttribute('aria-live', 'polite');
    expect(log).toHaveAttribute('aria-relevant', 'additions');
    expect(log.querySelectorAll('p')).toHaveLength(MESSAGES.length);
    expect(within(log).queryByText('Criteria set')).toBeNull();
    expect(within(log).queryByRole('link')).toBeNull();
    expect(within(log).queryByText('Card body')).toBeNull();
  });

  it('WS-THD-T04 with chips lists links named Suggested replies in order; with none there is no such list', () => {
    const { unmount } = render(drawer({ chips: CHIPS }));
    const list = screen.getByRole('list', { name: 'Suggested replies' });
    const links = within(list).getAllByRole('link');
    expect(links.map((a) => a.textContent)).toEqual(['List by name', 'Back to results']);
    expect(links[0]).toHaveAttribute('href', CHIPS[0].href);
    expect(links[1]).toHaveAttribute('href', CHIPS[1].href);
    unmount();
    render(drawer({ chips: [] }));
    expect(screen.queryByRole('list', { name: 'Suggested replies' })).toBeNull();
  });

  it('WS-THD-T05 with a summary shows Criteria set, the line and a Change criteria link; with null none of them', () => {
    const { unmount } = render(drawer({ summary: SUMMARY }));
    expect(screen.getByText('Criteria set')).toBeInTheDocument();
    expect(screen.getByText(SUMMARY.line)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Change criteria' })).toHaveAttribute('href', SUMMARY.changeHref);
    unmount();
    render(drawer({ summary: null }));
    expect(screen.queryByText('Criteria set')).toBeNull();
    expect(screen.queryByRole('link', { name: 'Change criteria' })).toBeNull();
  });

  it('WS-THD-T06 card is rendered after the log in document order', () => {
    render(drawer({ card: <p>Card body</p> }));
    const log = screen.getByRole('log', { name: 'Conversation' });
    const card = screen.getByText('Card body');
    expect(log.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('WS-THD-T07 shows Pick an option above and has no text box', () => {
    render(drawer({ chips: CHIPS, summary: SUMMARY }));
    expect(screen.getByText('Pick an option above')).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).toBeNull();
  });

  it('WS-THD-T08 AssistantButton is a button named Show the assistant with visible Assistant text; a click calls onShow once', async () => {
    const user = userEvent.setup();
    const onShow = vi.fn();
    render(<AssistantButton onShow={onShow} />);
    const button = screen.getByRole('button', { name: 'Show the assistant' });
    expect(button).toHaveTextContent('Assistant');
    expect(button).toHaveAttribute('data-el', 'WS-ASSISTANT-BUTTON');
    await user.click(button);
    expect(onShow).toHaveBeenCalledTimes(1);
  });

  it('WS-THD-T09 no element in either component has a style attribute', () => {
    const { container } = render(drawer({ summary: SUMMARY, chips: CHIPS, card: <p>Card body</p> }));
    expect(container.querySelector('[style]')).toBeNull();
    const second = render(<AssistantButton onShow={() => undefined} />);
    expect(second.container.querySelector('[style]')).toBeNull();
  });

  it('WS-THD-T10 ThreadDrawer with every part and AssistantButton pass runAxe', async () => {
    const full = render(drawer({ summary: SUMMARY, chips: CHIPS, card: <p>Card body</p> }));
    expect(await runAxe(full.container)).toHaveNoViolations();
    const button = render(<AssistantButton onShow={() => undefined} />);
    expect(await runAxe(button.container)).toHaveNoViolations();
  });
});
