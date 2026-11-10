import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { OptionView } from '@/lib/advisor/options';
import { OPTIONS_VIEW } from '@/test/fixtures/options';
import { ServiceCard } from './ServiceCard';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

// DEC-1365: the attention glow on the service cards.

const [UCR_WEST, WARD_B, HAH] = OPTIONS_VIEW.options as unknown as OptionView[];
const ACCEPTING: OptionView = { ...UCR_WEST, status: 'accepting', staleWarning: false, figureUnavailable: false };

function cardOf(variant: 'full' | 'row', option: OptionView) {
  const { container, unmount } = render(<ServiceCard caseId="case-1" option={option} variant={variant} />);
  const card = container.querySelector<HTMLElement>('[data-el="ADV-OPT-CARD"]') as HTMLElement;
  const result = { attention: card.getAttribute('data-attention'), className: card.className };
  unmount();
  return result;
}

describe('ServiceCard: the attention glow (DEC-1365)', () => {
  it.each(['full', 'row'] as const)('the %s card: over capacity is red, limited and not accepting are static, accepting has none', (variant) => {
    expect(cardOf(variant, { ...ACCEPTING, status: 'over-capacity', overBy: 1 }).attention).toBe('over');
    expect(cardOf(variant, { ...ACCEPTING, status: 'limited' }).attention).toBe('limited');
    expect(cardOf(variant, { ...ACCEPTING, status: 'not-accepting' }).attention).toBe('closed');
    const plain = cardOf(variant, ACCEPTING);
    expect(plain.attention).toBeNull();
    expect(plain.className).not.toContain('attention');
  });

  it.each(['full', 'row'] as const)('the %s card: a not-updated, unavailable or old figure is stale, even when it last said over capacity', (variant) => {
    expect(cardOf(variant, { ...ACCEPTING, status: 'not-updated' }).attention).toBe('stale');
    expect(cardOf(variant, { ...ACCEPTING, figureUnavailable: true }).attention).toBe('stale');
    expect(cardOf(variant, { ...ACCEPTING, status: 'over-capacity', overBy: 2, staleWarning: true }).attention).toBe('stale');
    expect(cardOf(variant, { ...ACCEPTING, staleWarning: true }).className).toContain('attention attention-stale');
  });

  it('a stale card keeps its status word and shape, shows "?" and never the last figure as spare capacity', () => {
    const { container } = render(
      <ServiceCard caseId="case-1" option={{ ...ACCEPTING, status: 'not-updated', figureUnavailable: true, lastFigure: 5 }} variant="row" />,
    );
    const badge = container.querySelector('[data-status="not-updated"]');
    expect(badge).not.toBeNull();
    expect(badge?.getAttribute('data-shape')).toBe('dashed-circle');
    expect(container.querySelector('[data-el="ADV-OPT-NUMBER"]')?.textContent).toBe('?');
    expect(container.textContent).toContain('Current capacity unavailable');
  });

  it('keeps the order of the options it is given: nothing ranks by status', () => {
    const statuses = ['not-updated', 'over-capacity', 'accepting'] as const;
    const options = [WARD_B, UCR_WEST, HAH].map((o, i) => ({ ...o, status: statuses[i] }));
    const { container } = render(
      <>
        {options.map((o) => (
          <ServiceCard key={o.serviceId} caseId="case-1" option={o} variant="row" />
        ))}
      </>,
    );
    expect([...container.querySelectorAll('h3')].map((h) => h.textContent)).toEqual(options.map((o) => o.name));
  });
});
