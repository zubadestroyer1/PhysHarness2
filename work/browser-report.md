# Local console browser check

2026-09-14, real Vite console at http://127.0.0.1:5173 and real FastAPI at
http://127.0.0.1:8000, using the existing generated local researcher identity.

- Sign-in screen has labeled API URL and password input, with no anonymous fallback.
- Initial connection failure was visibly reported as NETWORK_ERROR, with remediation and retry state.
- Subsequent successful refresh showed Connected, API/database healthy, verification/Temporal unavailable,
  and VM/fleet qualifications unqualified.
- Inspected a screenshot at 1280×720: navigation, status strip, main workspace and evidence panel are legible.
- Created a campaign through the actual form for both quantum and classical programs. Its title is
  Development smoke checks; objective explicitly says local test records and no scientific result.
- The persisted campaign appeared in navigation and overview with zero problems, experiments and claims.
- No fake successes, proof receipts or expert reviews were inserted into the local lab.

Component suite: 8 tests passed in console agent's report. This browser check does not establish
accessibility, large-graph performance, mobile layout or the 128-worker console latency targets.

Final integration recheck, 2026-09-15 UTC: restarted the actual API with the updated code and
reused the authenticated browser session. The existing campaign survived restart; the console
reconnected and displayed all wave qualifications as unqualified. The Activity view used the
current event endpoint without a fabricated fallback. No additional science records were created.
The latest component suite has 10 passing tests; TypeScript/Vite production build also passed.
