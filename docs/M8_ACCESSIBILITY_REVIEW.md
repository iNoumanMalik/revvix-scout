# M8 accessibility review

## Review status

Source, automated, and live-browser review completed on 2026-11-13 against the WCAG 2.2 Level A and AA success criteria. This is internal product-acceptance evidence rather than third-party accessibility certification.

Reference standards:

- [WCAG 2.2 Recommendation](https://www.w3.org/TR/WCAG22/)
- [WCAG 2.2 Quick Reference](https://www.w3.org/WAI/WCAG22/quickref/)

## Scope

- Supabase sign-in form.
- Business-lead filters, table, pagination, and export controls.
- Unified review queue and all enabled review actions.
- Lead-detail and individual-review modal panels.
- Desktop and narrow/mobile navigation paths.
- Loading, empty, read-only, error, and disabled states represented by the fictional test fixtures.

## Evidence and findings

| Area | Relevant criteria | Result and evidence |
| --- | --- | --- |
| Structure and relationships | 1.3.1, 1.3.2 | Native headings, landmarks, tables, labels, definition lists, and section relationships are present. Axe reports no violations in the tested states. |
| Text alternatives | 1.1.1 | Decorative icons and monograms are hidden from assistive technology; actionable controls have accessible names. |
| Contrast | 1.4.3, 1.4.11 | Small-text foregrounds were strengthened to at least 4.5:1 against their declared surfaces. Form boundaries and focus rings use colors above 3:1 against adjacent surfaces. Automated DOM tests do not disable axe's contrast rule, and the rendered states were visually reviewed in the live browser. |
| Reflow and responsive access | 1.4.10 | Content uses responsive grids and horizontal table containment. A mobile workspace selector preserves access to both lead intelligence and review queues when the desktop sidebar is hidden. Live review passed at 320 CSS pixels, the reflow equivalent of 1280 pixels at 400% zoom. |
| Keyboard access and focus order | 2.1.1, 2.1.2, 2.4.3 | Primary workflows are native controls. Automated keyboard tests cover sign-in order, filters, queue navigation, both dialogs, review resolution, Escape dismissal, focus restoration, and forward/reverse modal focus cycling. |
| Focus visibility and obscuring | 2.4.7, 2.4.11 | Three-pixel focus outlines are defined for light and dark surfaces. Modal background content becomes inert, focus is trapped within the active panel, and live keyboard checks confirmed forward/reverse cycling and Escape dismissal. |
| Page purpose and navigation | 2.4.1, 2.4.2, 2.4.6 | The page has a descriptive title, skip link, named navigation, labelled sections, and descriptive headings. |
| Target size | 2.5.8 | Interactive targets meet or exceed 24 by 24 CSS pixels in the source design; major form controls use at least 38 pixels and mobile controls use 44 pixels. Rendered desktop and mobile states were reviewed in the live browser. |
| Labels, errors, and status | 3.3.1, 3.3.2, 4.1.2, 4.1.3 | Inputs have programmatic labels and constraints; errors use `role="alert"`; loading states use `role="status"`; dialogs are named and modal. |
| Motion | 2.3.3 | The reduced-motion media query disables authored transitions and animations. No flashing content exists. |

## Automated acceptance

The Vitest/jsdom suite runs axe-core across the primary lead view, review queue, lead-detail dialog, individual-review dialog, and sign-in form. It also verifies:

- focus enters each dialog and returns to its invoking control;
- Tab and Shift+Tab cannot escape an active modal;
- Escape closes both review panels;
- background content is inert while a dialog is open;
- the mobile workspace control opens the review queue;
- individual decisions require a written rationale;
- opportunity review corrections remain keyboard-operable.

## Live browser acceptance record

The ChatGPT in-app browser was used against the live local Vite/FastAPI application with fictional fixtures only.

- Desktop viewport: 1440 × 900 CSS pixels; lead table, review queue, details, evidence cards, and modal scrolling rendered without clipping.
- Reflow viewport: 320 × 800 CSS pixels; mobile workspace navigation remained operable and all review content remained reachable.
- The first 320-pixel pass exposed horizontal overflow because `body` had `min-width: 320px` while a vertical scrollbar reduced the layout viewport. Removing that artificial minimum resolved the defect. Retesting reported 320 pixels for `innerWidth`, document `clientWidth`, document `scrollWidth`, and body `scrollWidth`.
- Keyboard: skip link moved focus to main content; lead-detail Tab and Shift+Tab stayed inside the modal; Escape closed both panels; individual review buttons remained disabled until a reason was entered.
- Advisory workflow: fictional opportunity analysis, acceptance, and reopening all completed successfully.
- Diagnostics: no browser console warnings or errors were present.
