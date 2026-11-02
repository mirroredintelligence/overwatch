# Ground rules for an agent implementing one unit of the redesign

Read this whole file first. It is short on purpose and every line is here because something went wrong without it.

## 1. What you are doing

You implement ONE unit (a route or a small group of routes) of the redesign in `frontend/`, test first. A unit gives you:

- the route files and components you may change (your allow-list),
- the artboard files that show the design (`docs/design/redesign/boards/<surface>/*.dc.html`),
- the section of the surface brief that describes the unit (`docs/design/redesign/<brief>.md`).

Nothing else is yours. Do not edit a file that is not on your allow-list, except to ADD new files next to your own. If you think a shared file must change (`app/tokens.css`, the shared shell, `StageGrid`, `StatusTag`, `Skeleton`, `Disclose`, anything under `components/shell/`), do NOT edit it: say so in your report and work around it inside your own files.

## 2. Reading an artboard

An artboard (`*.dc.html`) is a high-fidelity HTML mock-up. It is the specification.

- Inline `style="..."` holds the exact sizes, colours, spacing, radius and type. Copy those numbers.
- `{{name}}` is placeholder data. `<sc-for list="{{x}}" as="y">` is a loop, `<sc-if value="{{x}}">` a condition, `<dc-import name="Rail">` mounts another board file in the same folder.
- The `<script type="text/x-dc">` block's `renderVals()` holds the fake data AND, in interactive boards, the rule that turns a state (a step number) into styles. That rule is the morph: read it.
- Colours you will see map to tokens in `app/tokens.css`: `#0B5C8C` `--c-primary`, `#0B3F61` `--c-primary-dark`, `#14232B` `--c-ink`, `#26343B` `--c-ink-2`, `#44555D` `--c-muted`, `#DDE3E6` `--c-line`, `#F4F6F5` `--c-bg`, `#E3F1F8` `--c-tint`, `#FFF1DC` `--c-amber-tint`, `#A34700` `--c-limited`, `#3A4750` `--c-closed`, `#6B2C91` `--c-surge`, `#6B7B83` `--c-unknown`. The rail colour `#0B2A3D` and the page ground `#EEF2F3` are new tokens added by the shared foundation (`--c-rail`, `--c-ground`): use them once they exist in `app/tokens.css`. Use a token wherever one exists; a raw hex only where the board uses a colour with no token, and then say so in your report.
- Do not copy markup blindly. Rebuild it as React components with CSS modules, bound to the real data and behaviour of the existing component. Keep the existing data fetching, hooks, idempotency keys, CSRF handling, accessible names and messages unless the board changes them.
- Sample names, numbers and times on a board are illustrative. Never hard-code them.

## 3. The workspace

You run in a git worktree on your own branch. `frontend/node_modules` does not exist there. Before anything else, from the worktree's `frontend/` folder:

```
MSYS_NO_PATHCONV=1 cmd /c "mklink /J node_modules C:\github\overwatch\frontend\node_modules"
```

That is a junction to the shared install. NEVER run `npm install`, `pnpm install` or `rm -rf node_modules` here. If you ever need to remove the junction use `cmd /c rmdir node_modules` (never `rm -rf`, which would delete the shared install).

Commands, run from the worktree's `frontend/` folder:

- tests: `node --no-experimental-webstorage node_modules/vitest/vitest.mjs run <paths>` (the flag is required on this machine)
- types: `npx tsc --noEmit`
- lint: `npx eslint <the files you touched>`

Tests that already fail on the base branch because of local storage under that flag, and which you must ignore ONLY if they fail the same way and you did not touch their area: `components/admin/SupportRequests.test.tsx`, `components/clinical/CaseView.test.tsx`, `components/help/SupportCode.test.tsx`, `components/learn/*`, `lib/learn/progress.test.ts`, `lib/operator/browser.test.ts`, `lib/storage/tenantStore.test.ts`.

## 4. Git and files

- Commit only your own files, on your worktree branch, with a plain message ("Unit <id>: <what>"). Do not push.
- NEVER run `git reset --hard`, `git clean`, `git checkout -- .`, `git stash`, `git rebase`, `git merge`, or change branch. This repository has a file whose name differs only by case on Windows, and these commands have destroyed work before. If a file looks wrong, tell me; do not "fix" it with git.
- The warning "LF will be replaced by CRLF" is harmless. Edit with the Edit and Write tools. Do not run a formatter or `sed` over many files.
- Git Bash: put `MSYS_NO_PATHCONV=1` in front of a command whose argument starts with `/`. Do not write code with quotes through a shell heredoc: use the Write tool.

## 5. Code rules that bite

- React 19, Next 16 app router, TypeScript strict. `'use client'` only where a hook or event handler needs it. Match the surrounding code's comment density and naming.
- ESLint forbids calling `setState` synchronously inside an effect (react-hooks/set-state-in-effect): derive the value, or set it inside an async callback.
- Styles: CSS modules, design tokens only (spacing `--space-*`, radius `--radius*`, type `--type-*`, motion `--dur-*` and `--ease-*`). Motion tokens are zero under reduced motion, so use them for every transition and animation. The local spring is `cubic-bezier(0.34, 1.56, 0.64, 1)`, used only on small things (a chevron, a chip, a new row), never on a height.
- Rules every screen follows: a layout changes only because the person chose something; live figures never animate for style; status is shape plus word (never colour alone); text 4.5:1; touch targets 44px or more, primary actions 52px or more; works at 320px wide; one primary action per screen; no patient name anywhere.
- Do not add a dependency. Do not invent an endpoint or a field: use what the existing component already calls. If the board shows something the data does not have, render the board's version without it and list it under "gaps" in your report.

## 6. The protocol: test first, then build

1. Read the existing component(s) and their tests, the brief section and every board named for your unit.
2. Change or add tests so they describe the NEW design: the structure and text a person sees, roles and accessible names, each state the board shows (loading, empty, error, success, and the unit's own states), keyboard behaviour, and `runAxe` where the existing tests use it. Do not delete a test of real behaviour; update it.
3. Run them. They must FAIL, and fail for the right reason (the new thing is missing, not a typo). Write down the failing test names and the one-line reason for each.
4. Implement the design.
5. Run your tests until they pass. Then run `npx tsc --noEmit`, `npx eslint` on your files, and every other test file in the folders you touched.
6. Never make a test pass by weakening it. If a test is wrong, say why in the report.
7. Commit.

## 7. Your final report (exactly this shape, no praise, facts only)

```
UNIT: <id>
BRANCH: <worktree branch>   COMMIT: <sha>
FILES CHANGED: <list>   FILES ADDED: <list>
RED RUN: <n tests failed before implementation: names and one-line reasons>
GREEN RUN: <test files, passed/failed counts>   TSC: clean|errors   ESLINT: clean|errors
OTHER TESTS RUN IN THE TOUCHED FOLDERS: <counts, and any failure with its cause>
TESTS WEAKENED OR REMOVED: <none | each one and why>
DEVIATIONS FROM THE BOARD: <none | each one and why>
GAPS (board shows it, data does not have it): <none | list>
SHARED FILES I WANTED TO CHANGE BUT DID NOT: <none | list>
THINGS IN THIS PROMPT OR THESE RULES THAT WERE UNCLEAR OR WRONG: <none | list>
TIME LOST ON: <none | list: for example environment, a flaky test, a lint rule>
```
