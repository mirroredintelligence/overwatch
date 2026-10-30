import { PRODUCT_NAME } from '@/lib/product';

// The same page for every host: the product's name and nothing about an organisation.
export default function HomePage() {
  return (
    <main>
      <h1>{PRODUCT_NAME}</h1>
    </main>
  );
}
