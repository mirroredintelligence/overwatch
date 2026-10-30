import type { Metadata } from 'next';
import { PhonesList } from '@/components/lead/PhonesList';

// The phones and the services they report for (W43). At /lead/phones.

export const metadata: Metadata = {
  title: 'Phones and services - DIUCS capacity',
  robots: { index: false },
};

export default function PhonesPage() {
  return <PhonesList />;
}
