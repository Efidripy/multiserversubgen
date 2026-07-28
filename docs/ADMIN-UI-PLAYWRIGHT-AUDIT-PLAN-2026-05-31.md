# Admin UI Playwright Audit Plan (2026-05-31)

## Goal
- Run a full visual/UX audit of `https://dev.kleva.ru/y4cooovh/` with admin login credentials.
- Verify correctness on widths:
  - `426, 640, 854, 960, 1280, 1366, 1600, 1920, 2560, 3840`
- For each section:
  - open section
  - scroll through full page vertically
  - record layout breaks, missing elements, overlap, clipping, disappearing controls

## Current Status
- `blocked` (environment/network restrictions), not by app logic.

## What was attempted
1. Local Playwright run from workstation:
   - `playwright` installed successfully.
   - Browser launch worked, but page navigation failed with:
     - `net::ERR_NETWORK_ACCESS_DENIED` for `https://dev.kleva.ru/y4cooovh/`.
2. Remote Playwright run on `dev.kleva.ru`:
   - System Python blocked global pip install (PEP 668, expected).
   - Switched to `venv` approach.
   - `venv` install failed because server cannot fetch from `pypi.org` (timeouts / no package resolution).

## Hard blockers to resolve
1. Allow browser network access from local Playwright runner to:
   - `https://dev.kleva.ru`
2. Or allow `dev.kleva.ru` server outbound access to:
   - `https://pypi.org`
   - `https://files.pythonhosted.org`
   - Playwright browser CDN endpoints

## Exact audit execution plan after unblock
1. Prepare runner
   - Install Playwright + Chromium in the active environment.
2. Authenticate
   - Open login page, submit credentials, assert successful auth.
3. Section crawl
   - Collect sidebar/navigation links.
   - Visit each section route.
4. Per viewport audit
   - Set width from required list.
   - Capture full-page screenshot per section.
   - Auto-check:
     - horizontal overflow (`documentElement.scrollWidth > viewportWidth`)
     - off-screen interactive elements
     - clipped text/controls
5. Manual visual pass
   - Review all screenshots and note issues by severity.
6. Deliverables
   - `docs/ADMIN-UI-AUDIT-RESULT-2026-05-31.md`
   - screenshot bundle by width/section
   - prioritized fix list (P0/P1/P2)

## Result format (ready template)
- For each issue:
  - ID
  - Section
  - Width(s)
  - Repro steps
  - Actual behavior
  - Expected behavior
  - Severity
  - Suggested fix

## Notes
- The application itself is reachable and login endpoint works when service is up.
- This file tracks execution constraints and the exact next steps to complete the requested audit immediately after network restrictions are lifted.
