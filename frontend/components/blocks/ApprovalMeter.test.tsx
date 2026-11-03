import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { ApprovalMeter } from './ApprovalMeter';

describe('ApprovalMeter', () => {
  it('has one segment per approval needed, named "n of m approvals"', () => {
    const { container } = render(<ApprovalMeter given={1} needed={2} />);
    expect(screen.getByRole('img', { name: '1 of 2 approvals' })).toBeInTheDocument();
    const segments = container.querySelectorAll('[data-segment]');
    expect(segments).toHaveLength(2);
    expect([...segments].map((s) => s.getAttribute('data-segment'))).toEqual(['given', 'open']);
  });

  it('says the count in words under the bar', () => {
    render(<ApprovalMeter given={1} needed={2} />);
    expect(screen.getByText('1 of 2 approvals given.')).toBeInTheDocument();
  });

  it('lists who approved and the places still open', () => {
    render(<ApprovalMeter given={1} needed={2} approvers={[{ name: 'Sam Second', when: '2 Nov, 21:02' }]} />);
    const list = screen.getByRole('list', { name: 'Approvals' });
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('Sam Second');
    expect(items[0]).toHaveTextContent('Approved 2 Nov, 21:02');
    expect(items[1]).toHaveTextContent('One more person');
    expect(items[1]).toHaveTextContent('Not yet asked');
  });

  it('fills every segment when complete and has no list of open places', () => {
    const { container } = render(<ApprovalMeter given={2} needed={2} approvers={[{ name: 'A B' }, { name: 'C D' }]} />);
    expect([...container.querySelectorAll('[data-segment]')].every((s) => s.getAttribute('data-segment') === 'given')).toBe(true);
    expect(screen.queryByText('Not yet asked')).not.toBeInTheDocument();
  });

  it('shows initials, never more than two letters', () => {
    render(<ApprovalMeter given={1} needed={1} approvers={[{ name: 'Sam Ann Second' }]} />);
    expect(screen.getByText('SS')).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<ApprovalMeter given={1} needed={2} approvers={[{ name: 'Sam Second', when: '2 Nov' }]} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
