import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { CHOICE_COOKIE, unsealChoice } from '@/lib/auth/flow';
import { staffRoleWord } from '@/lib/shell/roleWords';
import styles from './choose.module.css';

// The tenant picker (DEC-1327): shown when one sign-in on the one domain finds the person holds a staff
// role in more than one organisation. Each choice starts a fresh sign-in naming that tenant; the back end
// checks the person's groups for it before any token is made. The list comes from a sealed cookie that
// expires in ten minutes; with none (expired, or a visit without a sign-in) the page sends the person back.
export default async function ChoosePage() {
  const value = (await cookies()).get(CHOICE_COOKIE)?.value ?? '';
  const tenants = await unsealChoice(value, new Date());
  if (tenants === null) redirect('/sign-in');

  return (
    <main className={styles.page}>
      <div className={styles.card}>
        <p className={styles.eyebrow}>Overwatch</p>
        <h1 className={styles.heading}>Choose an organisation</h1>
        <p className={styles.lede}>You work for more than one organisation. Pick the one you want to use now.</p>
        <ul className={styles.list}>
          {tenants.map((tenant) => (
            <li key={tenant.id}>
              <form method="post" action="/api/bff/auth/entra/start">
                <input type="hidden" name="tenant" value={tenant.id} />
                <button type="submit" className={styles.choice}>
                  <span className={styles.name}>{tenant.name}</span>
                  <span className={styles.roles}>{tenant.roles.map((role) => staffRoleWord(role)).join(', ')}</span>
                </button>
              </form>
            </li>
          ))}
        </ul>
        <p className={styles.note}>You will be asked to sign in with your staff account again. There is no new password.</p>
      </div>
    </main>
  );
}
