import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { MAP_VIEW } from '@/test/fixtures/map';
import { TravelDetails } from './TravelDetails';

const UCR = MAP_VIEW.options[0];
const HAH = MAP_VIEW.options[2];

describe('TravelDetails (W50)', () => {
  it('is a table of Leg, Range, How and Source, one row per leg', () => {
    render(<TravelDetails option={UCR} caseId="4821" />);
    const table = screen.getByRole('table', { name: 'Travel details' });

    expect(within(table).getByRole('columnheader', { name: 'Leg' })).toBeInTheDocument();
    expect(within(table).getByRole('columnheader', { name: 'Range' })).toBeInTheDocument();
    expect(within(table).getByRole('columnheader', { name: 'How' })).toBeInTheDocument();
    expect(within(table).getByRole('columnheader', { name: 'Source' })).toBeInTheDocument();
    const row = within(table).getByRole('row', { name: /Patient to UCR West, by road/ });
    expect(within(row).getByText('35 to 50 min')).toBeInTheDocument();
    expect(within(row).getByText('Typical weekday afternoon. The spread is from traffic.')).toBeInTheDocument();
    expect(within(row).getByText('Routing data, updated 12 Oct')).toBeInTheDocument();
  });

  it('a visiting service is included in its response time', () => {
    render(<TravelDetails option={HAH} caseId="4821" />);
    expect(screen.getByText('Included in their response time')).toBeInTheDocument();
  });

  it('says a range is not a promise, and names the postcode centre', () => {
    render(<TravelDetails option={UCR} caseId="4821" />);
    expect(
      screen.getByText(
        'A range, not a promise. Roads, weather and the time of day change it. The patient is placed at the postcode centre, so the range is for the area, not the door.',
      ),
    ).toBeInTheDocument();
  });

  it('"Report a wrong estimate" goes to the problem form, from this screen', () => {
    render(<TravelDetails option={UCR} caseId="4821" />);
    expect(screen.getByRole('link', { name: 'Report a wrong estimate' })).toHaveAttribute(
      'href',
      `/help/problem?from=${encodeURIComponent('/advisor/case/4821/map')}`,
    );
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <main>
        <TravelDetails option={UCR} caseId="4821" />
      </main>,
    );
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
