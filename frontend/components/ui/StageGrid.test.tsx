import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StageArea, StageGrid, StageLayer } from './StageGrid';

// The layout-morph primitive: one grid with three areas (list, stage, side), the columns for the current stage
// from a table the page gives, and layers that are inert and hidden from assistive technology unless current.

const TEMPLATES = ['0px minmax(0,1fr) 340px', '0px minmax(0,1fr) 320px', '300px minmax(0,1fr) 0px', '270px minmax(0,1fr) 300px'];

function grid(stage: number) {
  return render(
    <StageGrid stage={stage} templates={TEMPLATES}>
      <StageArea name="stage">
        {[0, 1, 2, 3].map((i) => (
          <StageLayer key={i} index={i} current={stage}>
            <button type="button">Stage {i}</button>
          </StageLayer>
        ))}
      </StageArea>
    </StageGrid>,
  );
}

describe('StageGrid', () => {
  it.each([0, 1, 2, 3])('sets the columns of stage %i', (stage) => {
    const { container } = grid(stage);
    const el = container.firstElementChild as HTMLElement;
    expect(JSON.parse(el.dataset.css ?? '{}').gridTemplateColumns).toBe(TEMPLATES[stage]);
    expect(el).toHaveAttribute('data-stage', String(stage));
  });

  it('names the three areas and gives the stage area to its children', () => {
    const { container } = render(
      <StageGrid stage={0} templates={TEMPLATES}>
        <StageArea name="list">a</StageArea>
        <StageArea name="stage">b</StageArea>
        <StageArea name="side">c</StageArea>
      </StageGrid>,
    );
    expect([...container.querySelectorAll('[data-area]')].map((a) => a.getAttribute('data-area'))).toEqual(['list', 'stage', 'side']);
    expect(container.querySelector('[data-area="stage"]')).toHaveTextContent('b');
  });

  it('sets the column gap of the stage, or the default one', () => {
    const { container, rerender } = render(
      <StageGrid stage={1} templates={TEMPLATES} gaps={['0px', '0px', '22px', '22px']}>
        <p>x</p>
      </StageGrid>,
    );
    expect(JSON.parse((container.firstElementChild as HTMLElement).dataset.css ?? '{}').columnGap).toBe('0px');
    rerender(
      <StageGrid stage={2} templates={TEMPLATES} gaps={['0px', '0px', '22px', '22px']}>
        <p>x</p>
      </StageGrid>,
    );
    expect(JSON.parse((container.firstElementChild as HTMLElement).dataset.css ?? '{}').columnGap).toBe('22px');
    rerender(
      <StageGrid stage={2} templates={TEMPLATES}>
        <p>x</p>
      </StageGrid>,
    );
    expect(JSON.parse((container.firstElementChild as HTMLElement).dataset.css ?? '{}').columnGap).toBe('var(--space-5)');
  });

  it('keeps the last template for a stage past the end, and the first for one before it', () => {
    const { container, rerender } = grid(9);
    expect(JSON.parse((container.firstElementChild as HTMLElement).dataset.css ?? '{}').gridTemplateColumns).toBe(TEMPLATES[3]);
    rerender(
      <StageGrid stage={-2} templates={TEMPLATES}>
        <p>x</p>
      </StageGrid>,
    );
    expect(JSON.parse((container.firstElementChild as HTMLElement).dataset.css ?? '{}').gridTemplateColumns).toBe(TEMPLATES[0]);
  });
});

describe('StageLayer', () => {
  it('lets the current layer be read and used, and hides the others', () => {
    grid(1);
    const layers = [0, 1, 2, 3].map((i) => screen.getByText(`Stage ${i}`).closest('[data-layer]') as HTMLElement);
    layers.forEach((layer, i) => {
      const current = i === 1;
      expect(layer).toHaveAttribute('data-layer', current ? 'current' : i < 1 ? 'before' : 'after');
      expect(layer.hasAttribute('inert')).toBe(!current);
      if (current) expect(layer).not.toHaveAttribute('aria-hidden');
      else expect(layer).toHaveAttribute('aria-hidden', 'true');
    });
    expect(screen.getByRole('button', { name: 'Stage 1' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Stage 0' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Stage 2' })).toBeNull();
  });

  it('moves the current marking when the stage changes', () => {
    const { rerender } = grid(0);
    expect(screen.getByText('Stage 0').closest('[data-layer]')).toHaveAttribute('data-layer', 'current');
    rerender(
      <StageGrid stage={2} templates={TEMPLATES}>
        <StageArea name="stage">
          {[0, 1, 2, 3].map((i) => (
            <StageLayer key={i} index={i} current={2}>
              <button type="button">Stage {i}</button>
            </StageLayer>
          ))}
        </StageArea>
      </StageGrid>,
    );
    expect(screen.getByText('Stage 2').closest('[data-layer]')).toHaveAttribute('data-layer', 'current');
    expect(screen.getByText('Stage 0').closest('[data-layer]')).toHaveAttribute('data-layer', 'before');
    expect(screen.getByText('Stage 0').closest('[data-layer]')).toHaveAttribute('inert');
  });
});
