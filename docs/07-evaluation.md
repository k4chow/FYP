# 07 — Evaluation Plan

Filled in through development; results recorded here in Phase 7 for the thesis
evaluation chapter.

## 1. Requirement coverage (functional testing)
Checklist derived directly from `01-requirements.md`: each F-requirement gets
a scripted test scenario and pass/fail evidence (screenshots + API traces).

## 2. Technical testing
| Layer | Method |
|---|---|
| Server endpoints | pytest + httpx against a test client (happy path + auth/RLS violations) |
| Memory lifecycle | Unit tests: proposed memories never leak into LLM context or recommendations; status transitions only via user actions |
| Context assembly | Unit tests: payload contains ≤ N messages + only confirmed memories; token bound check |
| Import pipeline | Fixture Letterboxd CSVs (clean, malformed rows, unmatched titles) |
| Client | TypeScript strict compile; component smoke tests for critical flows |

## 3. Usability evaluation
Small user study (5–8 participants, fellow students):
- Tasks: import library → complete a reflection → review insights (edit one,
  reject one) → inspect a recommendation's *why* → adjust profile toggles.
- Instruments: task completion rate/time, SUS questionnaire, short interview
  on trust/control ("did you feel the profile represented you?").
- Mock LLM vs real LLM noted as a limitation if the swap happens late.

## 4. Ethical considerations
- Informed consent; participants use throwaway accounts; data deleted after.
- System never infers mental-health states from film preferences (requirement
  N5) — evaluated by reviewing generated insights for inappropriate inferences.

## 5. Results (Phase 7)
_To be completed._
