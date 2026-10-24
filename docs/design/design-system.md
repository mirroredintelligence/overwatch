# Community Overwatch design system

Version 1.0 · Owner: product and design (delegated to the delivery team) · Status: adopted by DEC-014

Community Overwatch shows, in one place, how many people or places a service can take right now. Staff who coordinate care use it under pressure, often on a phone, sometimes after a busy night. Patients never see it. The design must be easy enough that nobody needs training, friendly enough that it does not feel like an NHS form, and calm enough that a changing number never causes panic or a wrong decision.

Nothing in this system is specific to any one area. Area names, service names and contact numbers come from configuration. Copy never names a place.

## 1. Principles

These come from the reviewed skills and our clinical context. When two principles conflict, the earlier one wins.

1. **Information first, decoration never.** Data people read or act on does not move for style. Motion only explains a change, confirms an action, or keeps a state from appearing abruptly.
2. **Fail safe and say so.** A stale or unknown figure is shown as stale or unknown, in words and shape, never as a confident number. A wrong answer is worse than no answer.
3. **Frequency decides motion.** The more often someone does a thing, the less it moves. Keyboard and high-frequency actions have no animation at all.
4. **Plain words, one primary action.** Every screen has one obvious next step. Labels say what happens ("Confirm booking"), not how the system works.
5. **Built for thumbs and bad signal.** Touch targets are at least 44 px (we use 52 px for primary actions). Layouts work at 320 px wide and at 200% zoom.
6. **Calm, not clinical.** Warm neutrals, rounded shapes, friendly sentences, and space to breathe. Never a wall of grey forms.
7. **Accessible by default.** Status is always shape and word as well as colour. Keyboard and screen-reader support are part of done, not an extra.

## 2. Colour

Values are fixed in `frontend/app/tokens.css` (task F09) and were contrast-checked. Text on background pairs meet WCAG AA (4.5:1). Non-text boundaries meet 3:1.

| Token | Hex | Use | Contrast with white |
|---|---|---|---|
| `--c-primary` | `#0B5C8C` | Primary buttons, links, focus accents | 7.18 |
| `--c-primary-dark` | `#0B3F61` | Hover and pressed states of primary, large numerals | higher |
| `--c-limited` | `#A34700` | Limited status (amber family) | 6.07 |
| `--c-closed` | `#3A4750` | Not accepting status | 9.56 |
| `--c-surge` | `#6B2C91` | Over capacity status | 8.77 |
| `--c-unknown` | `#6B7B83` | Not updated and last known: dashed border only (not for text) | 4.39 as border |
| `--c-ink` | `#14232B` | Primary text | 17+ |
| `--c-ink-2` | `#26343B` | Secondary text | 12.83 |
| `--c-muted` | `#44555D` | Helper text, captions (never below 14 px) | 8+ |
| `--c-line` | `#DDE3E6` | Dividers, card edges | decorative |
| `--c-bg` | `#F4F6F5` | Page background | n/a |
| `--c-tint` | `#E3F1F8` | Selected option and friendly highlight backgrounds | n/a |
| `--c-amber-tint` | `#FFF1DC` | Attention panels (never critical alerts) | n/a |

Rules:
- Status colours always appear with the word and the shape (section 6). Removing the colour must not remove the meaning.
- No gradients, no glass or blur surfaces on the wall board, no decorative colour blocks.
- Dark mode is a later milestone. Tokens are the only place colour is defined, so it can be added without touching components.

## 3. Typography

Typeface: **Atkinson Hyperlegible** (designed for legibility; loaded with `next/font/google`). Fallback: `system-ui, sans-serif`.

| Role | Size | Line height | Weight | Tracking | Use |
|---|---|---|---|---|---|
| Display | `clamp(2rem, 5vw, 3.5rem)` | 1.05 | 700 | -0.02em | Board numbers, welcome heading |
| Heading | 28 px | 1.2 | 700 | -0.01em | Screen titles |
| Title | 22 px | 1.3 | 700 | 0 | Card and section titles |
| Body | 18 px | 1.5 | 400 | 0 | Default text (not below 16 px anywhere) |
| Label | 17 px | 1.4 | 700 | 0.01em | Field labels, button text |
| Caption | 14 px | 1.4 | 400 | 0.01em | Helper text, timestamps |

Rules:
- Body text is 18 px. Anything smaller than 16 px is forbidden, and inputs are at least 16 px so mobile browsers do not zoom on focus.
- Numbers that line up in columns or tick over use `font-variant-numeric: tabular-nums`.
- Line length stays near 65 characters on wide screens.
- Headings use `text-wrap: balance`.

## 4. Spacing, shape and depth

- **Spacing scale (px):** 4, 8, 12, 16, 24, 32, 48, 64. Use only these values. Group related items with 8–12 px, separate groups with 24–32 px.
- **Radius:** 14 px for buttons and fields, 24 px for cards and sheets, full round for chips and avatars.
- **Depth:** a 1 px `--c-line` edge and a very soft shadow (`0 1px 2px rgb(20 35 43 / 0.06)`) are enough. No heavy drop shadows.
- **Touch targets:** at least 44 px square. Primary buttons 52 px high, chips 48 px high.
- **Gutters:** 16 px minimum on phones, respecting safe-area insets.

## 5. Motion

Motion is part of the product's feel, but it is deliberately rare on the parts people use all day. The rules below apply the four-check gate from the skills (frequency, purpose, speed, function) to everything that moves.

### 5.1 Gate: should this move at all?

| Frequency of the action | Motion allowed |
|---|---|
| Keyboard shortcuts, typing, several times a minute | None |
| Tens of times a day (list navigation, hover) | Almost imperceptible, or none |
| Occasional (dialogs, sheets, toasts, dropdowns) | Standard motion, short |
| Rare or first-time (onboarding complete, first report sent) | Delight allowed, still under 600 ms |

Every motion must name a purpose: confirming input, showing where something came from or went, showing a state change, preventing an abrupt appearance, or explaining a feature during onboarding. "It looks nice" is not a purpose.

Data people read or act on never moves for style. On the wall board, a changed number may cross-fade its colour once (section 5.4). Nothing slides, bounces or pulses.

### 5.2 Tokens

**Durations**

| Token | Value | Use |
|---|---|---|
| `--dur-press` | 140 ms | Press feedback on buttons |
| `--dur-tip` | 150 ms | Tooltips and small popovers |
| `--dur-menu` | 200 ms | Dropdowns, selects, option lists |
| `--dur-sheet` | 320 ms | Dialogs, sheets and drawers |
| `--dur-state` | 240 ms | Status colour change on the board |
| `--dur-onboard` | 480 ms | Onboarding and success moments only |

Rules: UI motion is under 300 ms, except onboarding. Exits are faster than entrances. Stagger list entries by 30–80 ms, and never let stagger block interaction.

**Easing**

| Token | Value | Use |
|---|---|---|
| `--ease-out` | `cubic-bezier(0.23, 1, 0.32, 1)` | Things entering or leaving (default) |
| `--ease-in-out` | `cubic-bezier(0.77, 0, 0.175, 1)` | Things moving from one place to another |
| `--ease-drawer` | `cubic-bezier(0.32, 0.72, 0, 1)` | Sheets and drawers |
| `--ease-hover` | `ease` | Hover and colour changes |

Never use ease-in on UI. Linear is only for constant motion (progress indicators), never for interaction.

**Springs** (only for drag and momentum gestures, never decorative): `{ duration: 0.5, bounce: 0.2 }`. Keep bounce between 0.1 and 0.3, and only for gestures such as dragging a sheet away.

### 5.3 Component behaviour

- **Press:** buttons and pressable cards scale to 0.97 on `:active` over `--dur-press`. This confirms the touch was registered.
- **Entrance:** start at `scale(0.95)` with `opacity: 0`. Never from `scale(0)`.
- **Popovers and menus:** `transform-origin` is the trigger. **Dialogs and sheets:** centred origin, or sliding from the bottom on phones with `--ease-drawer`.
- **Toasts:** a single gentle slide and fade, short. Pause the timer when the tab is hidden. Never use a toast for anything that needs a decision.
- **Hover effects:** gated behind `@media (hover: hover) and (pointer: fine)`. Touch devices do not get hover states.
- **Tap highlight** is turned off on the root, and every tappable element has its own pressed state instead.
- **Only `transform` and `opacity` animate.** `height` is allowed only for accordions. Never animate width, margin, padding, top or left. Never use `transition: all`; list properties.

### 5.4 Status change on the wall board

When a service's status changes:
1. The status chip cross-fades its colour and word over `--dur-state` with `--ease-hover`.
2. The shape does not move. It changes instantly with the word, so the meaning is never ambiguous.
3. The tile does not jump, flash or bounce.
4. A screen reader hears the change through a polite live region, and nothing is announced more than once per change.

Live updates from the server are applied in place, never by re-rendering the whole board.

### 5.5 Reduced motion

Under `prefers-reduced-motion: reduce`:
- Remove all transform-based movement (slides, scales, stagger).
- Keep opacity and colour changes, because they carry meaning.
- Keep the same information. Nothing is only conveyed by motion.

Reduced motion means gentler, not zero. Implement it in tokens (`--dur-*` becomes 0 for movement tokens only) rather than in each component.

### 5.6 Performance

- Animate `transform` and `opacity` only. Use `will-change` only when motion is imminent, on the moving element only.
- Use CSS transitions for interactive state (they retarget mid-animation); use CSS keyframes only for predetermined motion; use JavaScript only for gestures.
- Do not drive per-frame updates through a CSS variable on a parent, and do not call React state inside per-frame handlers.
- Measure on a mid-range Android phone over remote debugging before calling a motion done.

## 6. Status

Seven statuses. Each has a word, a shape, and a colour. The badge reads the same in greyscale.

| Status | Word | Shape | Colour |
|---|---|---|---|
| Accepting | Accepting | Filled circle with tick | Primary |
| Limited | Limited | Triangle | Limited amber |
| Not accepting | Not accepting | Filled square | Closed slate |
| Over capacity | Over capacity | Diamond | Surge plum |
| Out of hours | Out of hours | Half circle | Closed slate |
| Not updated | Not updated | Dashed circle | Unknown grey, dashed border |
| Last known | Last known | Dashed circle | Unknown grey, dashed border |

Not updated and last known always show the time of the last figure, in words ("Last reported 13:58").

## 7. Components

Interactive primitives (dialogs, menus, selects, tabs, switches, toasts) come from **React Aria Components**, which handle focus, keyboard and screen-reader behaviour. We style them with our tokens. Everything visual on top of them (badges, tiles, cards, the wall board) is ours. Decision DEC-014 records this.

| Component | Behaviour | Notes |
|---|---|---|
| Button | Primary, secondary, quiet. 52 px high. Pressed state scales to 0.97 | One primary button per screen |
| Option chip | Toggle with `aria-pressed`. 48 px high | Used for ages, needs, urgency |
| Number stepper | Big minus and plus, 52 px, with the number between | Used for "how many can you take" |
| Status badge | Word, shape, colour | Section 6 |
| Service tile | Name, status, number, unit, data age | Data age is always visible |
| Field | Visible label above the field, never placeholder-only | Errors under the field, in words, with an icon |
| Dialog or sheet | Plain title, one clear action, one way out | Focus trapped and returned |
| Toast | Short, optional, never the only feedback for an action | One toaster at the root |
| Empty state | A friendly sentence and one next step | Used in place of blank space |

## 8. Voice and copy

Friendly, direct, calm. Write the way a knowledgeable colleague would talk to someone on the phone.

- Active voice, one idea per sentence, short words. Prefer "Send" to "Submit", "Confirm booking" to "Process request".
- Say what happens next: "Next update due 12:00."
- Errors say what went wrong and what to do: "That code is not right. You have 3 tries left."
- No jargon in front of users. Use "referrals" or "beds" as the service sets them; never "capacity units".
- No blame and no urgency theatre. "Not updated" is a fact, not an accusation.
- No emoji, no exclamation marks in alerts, no apologies in place of a fix.
- **Area-neutral:** copy never names a place. Use the service's configured name and the area from configuration. The product name is always **Community Overwatch**.

Replacement for area-specific screen headings (applies wherever the design canvas says "Dorset urgent care capacity"):
- Board heading: `{Area name} capacity`. The area name comes from configuration.
- Sign-in and footers: "Community Overwatch".
- Telephone contacts: "{Service line name}" from configuration, never a hard-coded number.

## 9. Mobile and phones

- Layouts work from 320 px wide. Forms stack to one column; wide tables scroll in their own box.
- Use the dynamic viewport height for app shells. Pad fixed bars and sheets with safe-area insets.
- Set input font size to at least 16 px. Turn off autocorrect for codes and usernames.
- Use `interactive-widget=resizes-content` so the on-screen keyboard shrinks the layout.
- Overscroll is contained on inner scroll areas, and disabled on the root.
- Install-to-home-screen and notifications are optional enhancements. The product must work fully in a browser.

## 10. Accessibility

- Contrast meets WCAG AA. Focus rings are a visible 3 px outline in `--c-ink`.
- Every control has a visible label. Icon-only buttons have an accessible name.
- Status is shape and word, never colour alone.
- Keyboard: every action is reachable, focus order follows the visual order, and dialogs return focus.
- Screen readers: live regions announce data changes once, politely.
- 200% zoom and reflow at 320 px must not clip, overlap or hide actions.
- Reduced motion is respected (section 5.5).
- Each component's test runs the axe checks; the browser suite checks colour contrast in a real browser.

## 11. Edge cases every screen must survive

Taken from the break-ui review rules. Test with realistic data at the real limits, not with lorem ipsum.

- Very long service and area names, and long translated button text: they wrap or truncate with a tooltip, and never overlap.
- Unbreakable strings such as URLs: they scroll or break inside their own box.
- Missing optional data: no orphaned dashes or blank lines.
- Numbers: thousands separators, the number 0, counts of exactly 1 ("1 referral", not "1 referrals"), and very large counts.
- Empty lists, a single item, and 1,000 rows (the list is virtualised).
- Missing images (avatars): show initials on a tinted circle.
- Text containing characters such as `<` or `*` is shown as typed, never interpreted.

## 12. Design process

- A new screen starts from the design canvas wording and this system, not from a fresh look.
- For any new interactive pattern, compare two or three directions in the prototype before building. Pick the simplest that meets the principles.
- A motion is accepted only if it passes the gate in 5.1 and the review checks in 5.7.

### 5.7 Motion review checklist

A motion is rejected if any of these hold:
- It runs on a keyboard action or a high-frequency action.
- It starts from `scale(0)` or uses ease-in.
- It lasts over 300 ms without an onboarding reason.
- A popover or menu does not scale from its trigger.
- It animates width, height (outside accordions), margin, padding, top or left.
- It has no reduced-motion handling.
- It runs on hover on a touch device.
- It is decorative on data people read.

## 13. What we will not do

- No decorative animation on the wall board, status tiles or any number.
- No gradients, glassmorphism or neon.
- No dark patterns: no hidden opt-outs, no fake urgency, no nudging staff toward a service.
- No ranking of services or staff. The board shows numbers, shapes and data age, and nothing is scored.
- No patient data in any visual element, screenshot or animation.
