import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { VersionTimeline, type VersionEntry } from './VersionTimeline';

const versions: VersionEntry[] = [
  { id: 'v3', title: 'Version 3', state: 'waiting', stateLabel: 'Waiting for approval', detail: 'Sent today at 14:20 · review by 23 Jan' },
  {
    id: 'v2',
    title: 'Version 2',
    state: 'live',
    stateLabel: 'Live now',
    detail: 'Review by 30 Oct',
    facts: [
      { label: 'What changed from version 1', value: 'Added weight-bearing assessment.' },
      { label: 'Approved', value: 'By the Ward A manager and a clinical lead.' },
    ],
  },
  { id: 'v1', title: 'Version 1', state: 'earlier', stateLabel: 'At registration', detail: 'Replaced by version 2' },
];

describe('VersionTimeline', () => {
  it('is a list of versions, newest first as given', () => {
    render(<VersionTimeline label="Versions" versions={versions} />);
    const list = screen.getByRole('list', { name: 'Versions' });
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent('Version 3');
    expect(items[2]).toHaveTextContent('Version 1');
  });

  it('says each version state in words', () => {
    render(<VersionTimeline label="Versions" versions={versions} />);
    expect(screen.getByText('Waiting for approval')).toBeInTheDocument();
    expect(screen.getByText('Live now')).toBeInTheDocument();
    expect(screen.getByText('At registration')).toBeInTheDocument();
  });

  it('marks the live version as current and the others not', () => {
    render(<VersionTimeline label="Versions" versions={versions} />);
    const items = screen.getAllByRole('listitem');
    expect(items[1]).toHaveAttribute('aria-current', 'true');
    expect(items[0]).not.toHaveAttribute('aria-current');
    expect(items[0]).toHaveAttribute('data-state', 'waiting');
    expect(items[2]).toHaveAttribute('data-state', 'earlier');
  });

  it('shows the detail line and the labelled facts', () => {
    render(<VersionTimeline label="Versions" versions={versions} />);
    expect(screen.getByText('Sent today at 14:20 · review by 23 Jan')).toBeInTheDocument();
    expect(screen.getByText('What changed from version 1')).toBeInTheDocument();
    expect(screen.getByText('By the Ward A manager and a clinical lead.')).toBeInTheDocument();
  });

  it('draws the line down between versions but not after the last', () => {
    render(<VersionTimeline label="Versions" versions={versions} />);
    const items = screen.getAllByRole('listitem');
    expect(items[0].querySelector('[data-line]')).not.toBeNull();
    expect(items[2].querySelector('[data-line]')).toBeNull();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<VersionTimeline label="Versions" versions={versions} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
