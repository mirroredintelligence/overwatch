import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RADAR_PARTS } from '@/test/fixtures/radar';
import { OptionsMap } from './OptionsMap';
import { unplacedOf, UnplacedNote } from './UnplacedNote';

const placed = RADAR_PARTS.options[0];
const bare = { ...placed, serviceId: 'svc-bare', name: "Rob's H@H", position: null, coverage: null };

describe('UnplacedNote', () => {
  it('names a service with no place and no covered districts', () => {
    expect(unplacedOf([placed, bare])).toEqual([bare]);
    render(<UnplacedNote options={[placed, bare]} />);
    expect(screen.getByText(/Not drawn: Rob's H@H has no place or covered districts recorded/)).toBeInTheDocument();
  });

  it('says nothing when every service is placed', () => {
    const { container } = render(<UnplacedNote options={[placed]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows under the map', () => {
    render(
      <OptionsMap caseId="c1" postcode="DT4 8XX" patientArea={RADAR_PARTS.patientArea} options={[bare]} selectedId={null} onSelect={() => undefined} />,
    );
    expect(screen.getByText(/Not drawn: Rob's H@H/)).toBeInTheDocument();
  });
});
