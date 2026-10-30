import { render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RegisterServiceWorker } from './RegisterServiceWorker';

const register = vi.fn(() => Promise.resolve({} as ServiceWorkerRegistration));

beforeEach(() => {
  register.mockClear();
  Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: { register } });
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('RegisterServiceWorker', () => {
  it('registers /sw.js in a production build', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    render(<RegisterServiceWorker />);
    await waitFor(() => expect(register).toHaveBeenCalledWith('/sw.js'));
  });

  it('does not register outside production', async () => {
    vi.stubEnv('NODE_ENV', 'development');
    render(<RegisterServiceWorker />);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(register).not.toHaveBeenCalled();
  });
});
