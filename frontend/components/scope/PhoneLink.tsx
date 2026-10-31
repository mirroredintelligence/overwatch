import styles from './Scope.module.css';

// A link to phone a service on its service line (docs/design/network-ui.md section 4): the number is what is
// seen; the words before it are read out ("Phone UCR West on 01632 960010"), so a list of links is never a
// list of bare numbers. The visible text is part of the name, as WCAG 2.5.3 asks.

export function telHref(phone: string): string {
  return `tel:${phone.replace(/[^0-9+]/g, '')}`;
}

export function PhoneLink({ serviceName, phone, dataEl }: { serviceName: string; phone: string; dataEl?: string }) {
  return (
    <a href={telHref(phone)} data-el={dataEl}>
      <span className={styles.visuallyHidden}>{`Phone ${serviceName} on `}</span>
      {phone}
    </a>
  );
}
