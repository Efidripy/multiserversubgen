# Admin UI Audit Result (Playwright) — 2026-05-31

Target: `https://dev.kleva.ru/y4cooovh/`  
Auth: admin account credentials (redacted)

## Coverage
- Viewport widths checked:
  - `426, 640, 854, 960, 1280, 1366, 1600, 1920, 2560, 3840`
- For each width:
  - login
  - open main admin sections detected in sidebar
  - scroll down in each visited section
  - full-page screenshots collected

Artifacts:
- `E:/GitHub/repos/multiserversubgen/.tmp/playwright-audit-20260531/`
- `E:/GitHub/repos/multiserversubgen/.tmp/playwright-audit-20260531-v2/`

## Findings (current pass)
- **No deterministic UI breakages detected by automated checks**:
  - no stable horizontal overflow on tested views
  - no reproducible section-level render collapse found in this run
  - no blocking navigation errors during authenticated flow in this run

## Important caveat
- This was an automated pass; it can miss nuanced visual defects (micro-overlap, text clipping in rare states, data-dependent card/table breakpoints).
- If you want strict “pixel-level” signoff, next step is a guided manual visual pass on top of saved screenshots with explicit checklist per section/state.

## Suggested next pass (to close remaining risk)
1. Add stateful scenarios before capture:
   - open modals
   - expand long tables
   - trigger validation errors
   - switch dark/light theme if available
2. Force high-density datasets in Monitoring and Inbounds pages.
3. Add element-level assertions:
   - no clipped button labels
   - no overlap between sticky headers and content
   - no off-canvas controls in modal/dialog views

## Status
- **Current result:** `PASS (automated baseline)`  
- **Recommended confidence level:** medium (good baseline, not final visual QA signoff)

---

## Deep Pass Update (same date)

I ran an additional “stress” pass aimed at:
- opening action flows (`Add/Create/Edit`-like buttons),
- forcing validation focus/blur states,
- long vertical scrolling after interactions.

Artifacts:
- `E:/GitHub/repos/multiserversubgen/.tmp/playwright-audit-deep-20260531/`

### Additional findings
1. `P2` — small button text clipping risk  
   - Section: `Monitoring`  
   - Width: `854`  
   - Symptom: compact button with label `Add` had `scrollWidth > clientWidth` in one state snapshot.  
   - Impact: minor visual truncation risk in compact controls.

2. `P2` — same clipping pattern seen in one extra compact-nav context (emoji-labeled menu route)  
   - Width: `854`  
   - Impact: low, cosmetic.

### Fix direction
- Increase horizontal padding/min-width for compact `.btn.btn-sm` controls.
- Avoid hard width constraints for short labeled action buttons in responsive bands.

### Note on depth
- The deep pass succeeded, but current nav structure (including external/API-doc-like entries) reduces deterministic section-by-section traversal reliability for pure auto-discovery.
- For strict final signoff, I recommend pinning an explicit route list for core admin pages and replaying the same deep script against that fixed list.

---

## User-Reported Priority Items (added to plan)

These items are explicitly confirmed by real usage and should be treated as high-priority layout/UX targets:

1. `Registered fleet` does not show full server list on 4K  
   - Expected: all `10` servers visible (or clearly accessible without hidden clipping).  
   - Current observed: only `7` visible at `3840px` width.  
   - Priority: `P1`.

2. `Usage Telemetry` block is too narrow for available right-side space  
   - Expected: content width should expand proportionally and use desktop real estate better.  
   - Priority: `P1`.

3. `Monitoring` legends have unreadable node names  
   - Expected: readable node labels for all legend items across wide and medium screens.  
   - Priority: `P1`.

4. Layout width benchmark alignment with `Mission Control` right-column behavior  
   - Desired rule: use Mission Control right-column width behavior as desktop target baseline across sections.  
   - Constraint: keep small-width behavior stable (no breakage on mobile/narrow viewports).  
   - Priority: `P1` (systemic layout consistency).

5. `Actions -> +Add` should not expand inline inside table flow  
   - Current pain: inline open state breaks table layout/alignment.
   - Expected: open dedicated modal (same interaction pattern as `+Batch Add`).
   - Goal: keep row/cell geometry stable, prevent table reflow/jumps.
   - Priority: `P1`.

## Implementation intent for next iteration
- Introduce shared desktop width strategy for right content column across key sections.
- Add responsive guards for small breakpoints (`<=960`, `<=640`, `<=426`) to avoid regressions.
- Re-validate sections with explicit visual checklist after changes.

## Implementation Progress (2026-05-31, in progress)

Completed:
- `Actions -> +Add` in Nodes intake switched from inline expansion to modal-style interaction
  (aligned with `+Batch Add` behavior to avoid layout reflow in surrounding table/section flow).
- Desktop width constraints relaxed for main content area on wide screens:
  - removed strict `max-width` caps for `1920+`, `2560+`, `3840+` breakpoints to better use right-side space.
- Fleet panel overflow constraints eased:
  - disabled unintended clipping constraints in fleet block/table wrapper.
- Monitoring render safety:
  - added baseline canvas min-width guard to reduce chart clipping risk.
- Monitoring chart legend tuning:
  - moved legend to bottom/start and tightened spacing/font sizing for readability.

Pending verification:
- Re-check `Registered fleet` visibility of all 10 nodes at 4K.
- Re-check `Usage Telemetry` width behavior against Mission Control right-column baseline.
- Re-check node-name readability in Monitoring legends across target widths.
