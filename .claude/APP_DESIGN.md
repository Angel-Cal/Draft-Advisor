# DraftBot App Design Notes

What the app mockup (`mockup/`, published as a private artifact, last version 39 plus a one-line text fix) decides, and what each visual choice
obliges the real app and the C# engine to do. The mockup is a target, not code: nothing here is built yet. Read this before Phase 5.

**Source and how to update.** Edit `mockup/*.dc.html` (one file per screen, CSS at the top of each) and `mockup/canvas.json` (board positions). The pages load a
`support.js` that only the Artifact tool provides, so they do not render from disk; ask Claude to publish a changed file. Artifact:
https://claude.ai/artifact/JdKvyqBHuqhXH2gkeswgjQ (private).

**Renders.** `mockup/renders/` holds one image per screen as of artifact Version 41 (see its README for how they were made and what they do not show).

**Where the numbers came from.** Sample draft: 12 teams, snake, user in slot 5, picks 1-43 made, user on the clock at #44 (next pick #53), 2026 live
projections with FantasyPros ADP. Rankings, wait costs, fallbacks and the "past the wall" list were produced by running the real engine
(`DefaultWait` with `AlternativeReach.WithinCap`, `DefaultReach`, `NeedSettings.Default`) over that state with a throwaway harness that is not in the repo.
Hand-written (not engine output): the headline "Take a running back now.", "Four receivers in a row, picks 40 to 43.", the "Take now" cutoff, all footer text,
the reworded "Recommended" hover, the roster, and the drafter-tendency numbers (those two panels are marked Planned).

---

## 1. Rules that govern every screen

1. **Amber (`#F2B84B`) is sacred: it means "this is the thing to do now".** It appears only on: Swift's card (border, rank badge, Draft button), the
   "Recommended" tag, the "Take now" tile (border, verdict pill, cost figure), the clock panel, the board's on-the-clock cell (only when it is the user's
   pick), and the brand mark. Never use amber or a near shade (orange, gold, yellow) for flags, links, selection, warnings or status. Warnings are red, caution is purple.
   TE is violet precisely to keep orange out of the position colors.
2. **Time pressure comes first.** The decision (take/wait band, three cards) sits at the top; reference material (roster, "past the wall", player table, board) is
   secondary and lives in the side panel or other tabs. Do not put accessory content in the middle of the screen; the user tried it ("Past the wall" under the cards) and reversed it.
3. **Do not repeat information.** If a number is shown, do not also say it in a sentence next to it. Reasons are tags; the sentence lives in a hover box.
4. **No abbreviations a layperson would have to decode.** "Over replacement", never "Over repl."; "replacement-level" is explained once per screen with a "?" hover.
5. **No score units, ever.** The engine's score (e.g. 90) is not shown anywhere. Numbers are projected season points, picks, or percent chance. This is why the
   "Why this score?" button was removed.
6. **Hover boxes carry explanation, never the decision.** The cost of waiting, the verdict and the player's stats are always visible. Hover boxes are also
   keyboard-focusable (`tabindex=0`). The app is desktop; if it is ever made touch-first, hover content needs a tap equivalent.
7. **Fonts and sizes:** IBM Plex Sans for text, IBM Plex Mono with tabular numerals for numbers. Reason tags 13px (padding 5/16), other tags 11px, Draft button 36px high with 32px side padding.

## 2. Color roles

| Role | Color | Used for |
|---|---|---|
| Recommendation / act now | amber `#F2B84B` | see rule 1 |
| Navigation | azure `#4DA3FF` | active tab underline, gear icon on Settings. Tried on the board and rejected |
| QB / RB / WR / TE | pink / green / blue / violet (`#F4B3D0`, `#7FDBB6`, `#9BC3F7`, `#B79CFF`) | position pills, board cells, tendency bars |
| Risk | red `#F3A0A0` | Injury history tag, negative over-replacement |
| Bargain | lime `#B6E65A`, solid fill | the Bargain tag only: a player available well after his ADP. Lime is the hue farthest from every other color in use, but it is the nearest to amber of the free ones, so watch it |
| Caution | purple `#C9B3F5` | Role caution tag, "Planned" badge |
| Everything else | off-white `#E7ECF2` / greys | primary buttons on Setup/Settings, selected options, your board column |

Known overlaps to watch when it is rendered: the green "Starter" tag shares a hue with the RB pill and the positive green numbers; "Planned" and "Role caution" are
both purple; the azure underline is near the WR blue. Cyan was rejected for TE (too close to RB green).

## 3. Screens and what each element requires

**Navigation:** Draft, Players, Board, plus a gear icon (Settings) and a Sleeper status chip. Roster and Setup are not tabs: the bench folded into the draft screen's
roster card, and setup is a one-time flow. Sleeper chip is drawn only in the "live" state; **stale and disconnected states are not designed** (needs a design, and the manual pick entry
that Settings promises has no screen).

**First-run setup** (no nav): 1 connect Sleeper, 2 choose league/draft (slot shown), 3 confirm rules (one summary line, read from Sleeper). Buttons: "Go to the draft",
"Start a practice draft instead". Needs Sleeper integration (Phase 5). Scoring is PPR only; half-PPR and standard are disabled and marked Planned (they need the Phase 3 retrain).

**Draft screen, top to bottom:**
- *Status strip.* Clock (amber label, tinted panel, white digits), round/pick, next pick and distance, last five picks, one summary sentence. **Needs a pick log and a run
  detector** to write "Four receivers in a row"; nothing in the engine produces that sentence yet.
- *Take/wait band.* Headline + one line, then four tiles (QB, RB, WR, TE): verdict pill, cost of waiting (points), the top player now, and the two best players likely to last
  to the next pick with their chance of lasting. Tiles are display-only (they used to filter the table). **Engine needs a per-position advice call**: top candidate, expected shortfall
  (`WaitBonus / Weight`), and the two best likely-to-last alternatives. `ValueCandidate.WaitFallback` gives only one alternative per candidate, so a second must be exposed.
  The mockup's alternatives are the best by base value with survival >= 0.5, inside the reach cap at the next pick (`WithinCap`). "Take now" is cost >= 5 points; between 0.5 and 5 shows the cost in
  grey with "Can wait"; below 0.5 shows "None". The 5-point cutoff is a display choice, not tested; it matches `Explainer.NoticeableDropOff`. The headline must be generated (largest cost, or "nothing is urgent").
- *Three recommendation cards* (the engine's top 3): rank badge, name, position pill, team, then Proj / Over replacement / ADP / Tier, reason tags, Draft button pinned to the card's bottom-left.
  Swift (rank 1) carries the amber treatment; the other two are neutral. Cards are equal size.
- *Reason tags* map to `ReasonLabel`: Starter, **Recommended** (this is the `RunningOut` reason, relabelled: it is an opportunity cost for that particular player, not a statement about the position), Injury history,
  Role caution, Not a starter (`Backup`). **Tags for Reach, Discount and Estimated projection are not designed**, and they must not be amber. The hover text comes from `Explainer`.
- *Also on the list:* ranks 4 and 5 as one quiet line, with the role caution tag hoverable. A bench-only player is described as "bench insurance for X".
- *Side panel:* roster card (filled and open starting slots, open slots count as replacement-level points with the "?" hover, a collapsed BENCH row "0 of 8 filled"), then "Past the wall".
- *Past the wall* (unranked): the policy decision is that the advisor keeps the tested reach limits for ranked picks, and shows players the model likes beyond them as information only. Compute it with the reach
  cost off, within 1.5 sigma of the pick (slight reaches only), by score without the cost; show points over replacement and how many picks early. The footer sentence must follow the data (QB waiting costs a little, so it says "little or nothing").
  A longer-term idea (not built): the pick log could measure how far this league's drafters really reach and loosen the wall.

**Players tab:** every available player sorted by ADP, with position chips, search, and columns Rec. (rank among the engine's top five, else a dash), Player, Pos, Team, Proj, Over replacement, ADP, Tier, Flags
(Injury, Role, Estimate). Replacement levels for the footnote (QB 248, RB 139, WR 141, TE 129) come from `LineupValue.Replacement` and are fixed per projections file. Tiers are the engine's tiers.

**Draft board:** 12 x 16 snake grid from the pick log; cells colored by position; your column has a grey header and a slightly lighter empty background and a light-grey border on your picks; the on-the-clock cell is amber **only when it is the
user's turn** (another team's turn must use the plain grey border). Two panels are marked Planned and need Phase 5 data: drafter tendencies (picks earlier/later than ADP per team) and the pick log.

**Settings (gear):** Practice draft (slot, rules, start), Advice toggles, Sleeper (status, follow live, reconnect, disconnect, choose another draft), League rules (editable, read from Sleeper), and a collapsed Developer options (the
three advisor variants, projection file details). The user-facing line is "Projections current as of ...". Implications: the app needs a **practice (mock) draft mode**, and the draft screen needs a clear **"Practice" marker** so it cannot be mistaken for a live draft (not designed);
the "Plain-language reasons" toggle predates the tags-only design and may be unnecessary (the reasons now only exist as hover text); the Role caution toggle must stay text-only and never change a score.

## 4. Engine and code changes the mockup implies

Done in milestone 1 (2026-10-28, `DraftAdvisor` and `Explainer` in Core): the Starter reason is now just "He fills an open starting RB spot." (or "would start ahead of X");
`ReasonLabel.RunningOut` is shown as "Recommended" (`ReasonLabels.DisplayName`) with a sentence that carries the same cost figure as the tile; one call, `DraftAdvisor.Advise`,
returns the top 5 with tags, the four position tiles (cost, "take now", two likely-to-last players with their chance) and the "past the wall" list; the "take now" cutoff and the explanation
cutoff are the one constant `Explainer.NoticeableCost` (5 points). "Past the wall" lists slight reaches only (within 1.5 sigma; at 2.5 it also listed a running back 20 picks early).
One advice call takes about 1-2 ms on the mockup's state.

Milestone 2 (the app on a practice draft) settled three things the mockup left open: the draft screen's header shows a neutral "Practice draft" chip where the Sleeper chip goes, so a practice draft
cannot be mistaken for a live one; the take/wait tiles are ordered "take now" first (most costly first) and then in QB, RB, WR, TE order (a plain sort by cost put TE ahead of WR on a 0.03-point difference); and
tags without a designed color (Bargain, Early pick, Estimate, Not a starter) are grey, never amber. "Not a starter" now appears as a grey tag on the "Also on the list" row, where the mockup had a text note.

After the user tried the app (2026-10-28): the Pause/Resume button sits beside the pick clock, not in the header. A player who is an early pick (`Explainer.EarlyPickSigmas`, 1 sigma or more past his ADP) is never a
recommendation: the cards and the "Also on the list" line hold only sane picks, and early picks within 1.5 sigma go under "Past the wall" (so a card never reads both "Early pick" and "Recommended"); if only early
picks are left they are shown anyway. The headline follows the top pick's position, and when the best pick at another position scores within 5% (at least 5 points) it says "Close call: a X or a Y." instead of
"Take a X now." (`DraftAdvisor.RivalPosition`; a display choice, not a tested one). The Bargain tag is lime.

Second round of feedback (same day): amber and "Recommended" go only to what the advice backs, never to something that merely costs points to wait on. A position tile is amber ("Take now", or "Best pick" if waiting is cheap)
only for the top pick's position and, in a close call, the other position; a position that is costly to wait on (5 points or more) but not backed reads "Costly to wait" in neutral, with its cost in off-white. The "Recommended" tag is on the top
pick only (and the best pick at the other position in a close call), so a card for a different position never says it. The explanation then says why: "Waiting on RB would cost about 22.3 points too, but the receiver is the
better use of this pick." The four card stats are a fixed 2 x 2 grid (Proj, Over replacement / ADP, Tier) so cards line up whatever the numbers.

Third round (same day, from a screenshot at pick 20): the top pick always carries "Recommended"; when waiting on him costs under 5 points the hover text is the best-overall reason (`Explainer.BestPickReason`:
weighs lineup value, waiting cost and how early he would be taken, and says whether he is a reach). The headline's explanation says why a costly position is not the pick: its best player would be a reach ("taking J.Allen or
B.Bowers now would be a reach: they usually go 3 picks after this one") or the top pick is worth more. What decided that screen: Allen and Bowers had the larger waiting bonus (62 and 53 against 14 for London) and would have won
without the reach cost, but taking them 3 picks before their ADP costs 379 and 290 points of score, so London, the only strong player available right at his ADP, wins; the engine weights the reach cost very heavily on purpose
(tested). The Bargain tag is solid white.
Open: players like Allen and Bowers (about 0.6 sigma early) still get cards 2 and 3, while the sentence calls them reaches; "early pick" for the cards is 1 sigma but the sentence uses 0.25 sigma. One line for both is needed.

Still to do:

1. Pick log + run detection + drafter tendencies (Phase 5) for the status sentence and the Planned panels (not in version 1; picks are still recorded silently).
2. Practice-draft mode, connection-state handling and manual pick entry (see Settings and navigation above).
3. Half-PPR and standard scoring need the Phase 3 retrain before the disabled options can be enabled.
