import { describe, expect, it } from 'vitest';
import { bookedFinishAddress, bookedFromAddress } from './outcome';

// A confirmed booking in the address of the finish screen (DEC-1344).

describe('bookedFromAddress', () => {
  it('reads an accepted-and-booked outcome with a service id', () => {
    expect(bookedFromAddress('accepted-and-booked', 'svc-ucr-west')).toEqual({ destination: 'svc-ucr-west' });
  });

  it('is null for any other outcome, a missing service, or a service id that is not one', () => {
    expect(bookedFromAddress('declined', 'svc-ucr-west')).toBeNull();
    expect(bookedFromAddress('accepted-and-booked', undefined)).toBeNull();
    expect(bookedFromAddress('accepted-and-booked', '')).toBeNull();
    expect(bookedFromAddress('accepted-and-booked', 'a b')).toBeNull();
    expect(bookedFromAddress('accepted-and-booked', '../x')).toBeNull();
    expect(bookedFromAddress(undefined, 'svc-ucr-west')).toBeNull();
  });
});

describe('bookedFinishAddress', () => {
  it('names the outcome and the service, and round-trips through the reader', () => {
    const address = bookedFinishAddress('4821', 'svc-ucr-west');
    expect(address).toBe('/advisor/case/4821/finish?outcome=accepted-and-booked&destination=svc-ucr-west');
    const query = new URL(address, 'https://x.test').searchParams;
    expect(bookedFromAddress(query.get('outcome'), query.get('destination'))).toEqual({ destination: 'svc-ucr-west' });
  });
});
