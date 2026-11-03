import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { SplitHero } from './SplitHero';

const copy = {
  eyebrow: 'Platform console',
  title: 'Set up organisations and keep them running',
  lead: 'For the people who run the platform.',
  footnote: 'Staff of an organisation sign in at their own address, not here.',
};

describe('SplitHero', () => {
  it('shows the brand half with the product name, eyebrow, title, lead and footnote', () => {
    render(
      <SplitHero {...copy}>
        <p>Card</p>
      </SplitHero>,
    );
    const brand = screen.getByRole('region', { name: 'Overwatch' });
    expect(within(brand).getByText('Overwatch')).toBeInTheDocument();
    expect(within(brand).getByText('Platform console')).toBeInTheDocument();
    expect(within(brand).getByRole('heading', { level: 1, name: copy.title })).toBeInTheDocument();
    expect(within(brand).getByText(copy.lead)).toBeInTheDocument();
    expect(within(brand).getByText(copy.footnote)).toBeInTheDocument();
    expect(brand.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it('puts the children in the light half, a region named Sign in by default', () => {
    render(
      <SplitHero {...copy}>
        <button type="button">Sign in with your platform account</button>
      </SplitHero>,
    );
    const content = screen.getByRole('region', { name: 'Sign in' });
    expect(within(content).getByRole('button', { name: 'Sign in with your platform account' })).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Overwatch' })).queryByRole('button')).toBeNull();
  });

  it('names the light half from contentLabel when given', () => {
    render(
      <SplitHero title="FORTRUS LIMITED" contentLabel="Staff sign in">
        <p>Card</p>
      </SplitHero>,
    );
    expect(screen.getByRole('region', { name: 'Staff sign in' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Sign in' })).toBeNull();
  });

  it('leaves out the eyebrow, lead and footnote when they are not given', () => {
    render(<SplitHero title="Overwatch" />);
    const brand = screen.getByRole('region', { name: 'Overwatch' });
    expect(brand.querySelector('p')).toBeNull();
    expect(within(brand).queryByText('Platform console')).toBeNull();
    expect(within(brand).queryByText(copy.footnote)).toBeNull();
  });

  it('marks brandAt end on the root, so the stylesheet moves the brand to the right half', () => {
    const { container } = render(
      <SplitHero {...copy} brandAt="end">
        <p>Card</p>
      </SplitHero>,
    );
    expect(container.firstElementChild).toHaveAttribute('data-brand-at', 'end');
    expect(screen.getByRole('region', { name: 'Overwatch' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('defaults the brand to the start of the row', () => {
    const { container } = render(<SplitHero {...copy} />);
    expect(container.firstElementChild).toHaveAttribute('data-brand-at', 'start');
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <SplitHero {...copy}>
        <p>Card</p>
      </SplitHero>,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('keeps the text on the dark half at 4.5:1 or more', () => {
    const tokens = readFileSync(join(process.cwd(), 'app', 'tokens.css'), 'utf8');
    const css = readFileSync(join(process.cwd(), 'components', 'blocks', 'SplitHero.module.css'), 'utf8');

    const declared = (selector: string, prop: string): string => {
      const rule = css.match(new RegExp(`^${selector}\\s*\\{([^}]*)\\}`, 'm'));
      const value = rule?.[1].match(new RegExp(`(?<![-\\w])${prop}:\\s*([^;]+);`))?.[1];
      if (!value) throw new Error(`${selector} has no ${prop}`);
      return value.trim();
    };
    const colour = (value: string): string => {
      const ref = value.match(/^var\((--[\w-]+)\)$/);
      if (ref) {
        const found = tokens.match(new RegExp(`${ref[1]}:\\s*([^;]+);`))?.[1];
        if (!found) throw new Error(`token ${ref[1]} not found`);
        return colour(found.trim());
      }
      if (/^#[0-9a-f]{3}$/i.test(value)) return `#${value.slice(1).split('').map((c) => c + c).join('')}`;
      if (/^#[0-9a-f]{6}$/i.test(value)) return value;
      throw new Error(`not a hex colour: ${value}`);
    };
    const luminance = (hex: string): number => {
      const h = hex.slice(1);
      const [r, g, b] = [0, 2, 4].map((i) => {
        const c = parseInt(h.slice(i, i + 2), 16) / 255;
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const contrast = (a: string, b: string): number => {
      const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
      return (hi + 0.05) / (lo + 0.05);
    };

    const ground = colour(declared('\\.brand', 'background'));
    for (const selector of ['\\.title', '\\.eyebrow', '\\.lead', '\\.footnote']) {
      expect(contrast(colour(declared(selector, 'color')), ground), selector).toBeGreaterThanOrEqual(4.5);
    }
  });
});
