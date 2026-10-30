import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { parseProfile } from '@/lib/tenant/profile';
import { runAxe } from '@/test/a11y';
import { TENANTS } from '@/test/tenants';
import { TenantHeader } from './TenantHeader';

// The organisation's own name at the top of a page (TEN-049), so a person who works for more than one
// organisation always sees which one this is. It shows the display name from the profile and nothing
// else: no id, no host, no network.

const A = parseProfile(TENANTS.A.profile);
const B = parseProfile(TENANTS.B.profile);

describe('TenantHeader', () => {
  it('shows the organisation name as the profile gives it, in a labelled region', () => {
    render(<TenantHeader profile={A} />);
    const region = screen.getByRole('region', { name: 'Organisation' });
    expect(region).toHaveTextContent('Sample Area A');
    expect(region).toHaveAttribute('data-el', 'TENANT-HEADER');
  });

  it('shows another tenant’s name for another tenant’s profile, and never both', () => {
    const { rerender } = render(<TenantHeader profile={A} />);
    rerender(<TenantHeader profile={B} />);
    expect(screen.getByRole('region', { name: 'Organisation' })).toHaveTextContent('Sample Area B');
    expect(document.body.textContent).not.toContain('Sample Area A');
  });

  it('renders nothing when there is no profile (an unknown host, a back end that is down)', () => {
    const { container } = render(<TenantHeader profile={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the name as text: markup in it is shown, not run', () => {
    const tricky = parseProfile({ ...TENANTS.A.profile, displayName: '<img src=x onerror=alert(1)> Area' });
    const { container } = render(<TenantHeader profile={tricky} />);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByRole('region', { name: 'Organisation' })).toHaveTextContent('<img src=x onerror=alert(1)> Area');
  });

  it('holds no tenant id, host, phone number or network in the page', () => {
    const { container } = render(<TenantHeader profile={A} />);
    const html = container.innerHTML;
    expect(html).not.toContain(TENANTS.A.id);
    expect(html).not.toContain(TENANTS.A.host);
    expect(html).not.toContain('01632');
    expect(html).not.toMatch(/network|net-/i);
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<TenantHeader profile={A} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
