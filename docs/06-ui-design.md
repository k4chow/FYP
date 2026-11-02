# 06 — UI Design

28 screens extracted from `FYP UI (1)_compressed.pdf`. Brand: **NOACF —
"Your personal film journal"**, film-strip logo, dark cinematic theme.

## Design tokens (defined in `client/src/index.css`)

| Token | Value | Usage |
|---|---|---|
| `--color-bg` | `#0b0d17` | page background (near-black navy) |
| `--color-surface` | `#151a2e` | cards, sidebar |
| `--color-surface-2` | `#1d2338` | raised elements, inputs |
| `--color-accent` | `#8b8cf8` | lavender/periwinkle — CTAs, active nav, chips |
| `--color-accent-grad` | `#7c7ff2 → #a78bfa` | primary button gradient |
| `--color-text` | `#f1f2f8` | headings |
| `--color-text-muted` | `#9aa0b5` | body/secondary |
| `--font-display` | "Playfair Display", serif | emotional headlines ("Films stay with us.") |
| `--font-body` | "Inter", system sans | UI text |

## Screen inventory → implementation mapping

| Flow | Screens (mockup #) | Phase |
|---|---|---|
| Landing hero / Sign up | 01, 02 | 1 |
| Sign in / Forgot password | 28-4a, 28-4b | 1 |
| Onboarding: Import | 03, 04 (user: "use this one") | 2 |
| Onboarding: film selection (≥5) | 05 | 2 |
| Onboarding: about-you question | 06 | 5 |
| First reflection entry points | 10 | 3 |
| Reflection chat | 11 (+ quick replies from 09) | 3 |
| Poster-choice layout (repurposed) | 07 | 3 |
| Review & edit insights | 12 | 4 |
| Compare and refine | 14 | 4 |
| Home dashboard | 15 | 1 (placeholder data) → 5 (live) |
| Discover grid + why-explanations | 17 | 6 |
| Film Assistant chat + thinking states | 18, 19 | 6 |
| Add a Reflection | 21+22 hybrid | 3 |
| My Films grid / Add-a-film modal | 23, 24 | 2 |
| My Profile (themes, insight toggles) | 25 | 5 |
| My Reflections list + detail tabs | 26 | 3 (list) → 5 (detail tabs) |
| Settings (Letterboxd, style slider, password) | 27 | 1 (shell) → 2/6 (features) |
| States: resume banner, feedback, search/empty/loading/error, film-added | 28 | per-flow |

## Recurring components
Sidebar app shell · film card (poster, meta, theme chips) · insight card
(Keep/Edit/Remove) · toggle switch · quick-reply chips · step progress bar ·
"Why am I seeing this?" link · recommendation card with *why* line and
More-like-this / Not-for-me feedback.
