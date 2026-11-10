import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CriteriaSummary } from './CriteriaSummary';

// The criteria summary (WS-CRS): four pairs, Age, Postcode, Need, Timeframe, in that order.
// A set value shows a filled dot, an unset one an open circle; both markers are aria-hidden.

const MARKERS = /[●○]\s*/g;

function valueText(definition: HTMLElement): string {
  return (definition.textContent ?? '').replace(MARKERS, '').trim();
}

describe('CriteriaSummary', () => {
  it('WS-CRS-T01 with nothing set shows four terms and four definitions each reading "Not set"', () => {
    render(<CriteriaSummary age={null} district={null} needs={[]} urgency={null} />);

    expect(screen.getByRole('region', { name: 'Criteria' })).toBeInTheDocument();
    const definitions = screen.getAllByRole('definition');
    expect(screen.getAllByRole('term')).toHaveLength(4);
    expect(definitions).toHaveLength(4);
    for (const definition of definitions) {
      expect(valueText(definition)).toBe('Not set');
      expect(definition.textContent).toContain('○');
      expect(definition.querySelector('[aria-hidden="true"]')).not.toBeNull();
    }
  });

  it('WS-CRS-T02 with everything set the definitions read "65 to 79", "DT4", "Frailty" and "Today"', () => {
    render(<CriteriaSummary age="65 to 79" district="DT4" needs={['Frailty']} urgency="Today" />);

    const definitions = screen.getAllByRole('definition');
    expect(definitions.map(valueText)).toEqual(['65 to 79', 'DT4', 'Frailty', 'Today']);
    for (const definition of definitions) {
      expect(definition.textContent).toContain('●');
      expect(definition.querySelector('[aria-hidden="true"]')).not.toBeNull();
    }
  });

  it('WS-CRS-T03 two needs read "Frailty, Wound care"', () => {
    render(<CriteriaSummary age={null} district={null} needs={['Frailty', 'Wound care']} urgency={null} />);

    const definitions = screen.getAllByRole('definition');
    expect(valueText(definitions[2])).toBe('Frailty, Wound care');
    expect(definitions[2].textContent).toContain('●');
  });

  it('WS-CRS-T04 the terms are exactly "Age", "Postcode", "Need", "Timeframe", in that order', () => {
    render(<CriteriaSummary age={null} district={null} needs={[]} urgency={null} />);

    const region = screen.getByRole('region', { name: 'Criteria' });
    const terms = within(region).getAllByRole('term');
    expect(terms.map((term) => term.textContent?.trim())).toEqual(['Age', 'Postcode', 'Need', 'Timeframe']);
  });

  it('WS-CRS-T05 no element has a style attribute and the component passes runAxe', async () => {
    const { container } = render(
      <CriteriaSummary age="65 to 79" district="DT4" needs={['Frailty', 'Wound care']} urgency={null} />,
    );

    expect(screen.getByRole('region', { name: 'Criteria' })).toBeInTheDocument();
    expect(container.querySelector('[style]')).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
