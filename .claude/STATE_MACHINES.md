# State machines

Every state machine in the app and the code it drives, explicit or implicit: its states, the invariants that must hold between calls, and every transition.
Then the invalid states and transitions the code can actually reach, with evidence, grouped into issues by impact. Written 2026-11-06; keep it in step with the code
(a new screen, user action, timer or background step adds rows here).

Notation: `N` = `Teams x RosterSize` picks in the draft (12 x 16 = 192 in the default league); `n` = picks made so far (`DraftState.OverallPick`); `snake(n)` = the team
on the clock at pick `n` (odd rounds 0..T-1, even rounds T-1..0).

## 1. Draft state (`DraftState`, Core) - explicit counter

The pick counter `(Round, PickInRound)`; everything else (who is on the clock, completion) is derived from it.

| State | Meaning |
|---|---|
| `OnClock(n)`, 0 <= n < N | team `snake(n)` is on the clock (`CurrentTeam`) |
| `Complete` | n = N (`IsComplete`) |

| From | Event | Guard | To | Effect |
|---|---|---|---|---|
| `OnClock(n)` | `Draft(id)` | `id` in `Available` | `OnClock(n+1)`, or `Complete` if n+1 = N | player moves from `Available` to the team's `Roster` and to `History` |
| `OnClock(n)` | `Draft(id)` | `id` not in `Available` | `OnClock(n)` | returns false, nothing changes |
| `Complete` | `Draft(id)` | - | `Complete` | throws `InvalidOperationException` |
| any | `Clone()` | - | same state, independent copy | used by the advisor's re-rankings and the simulator |

Invariants (between calls):
- D1 `History.Count == OverallPick`, and `History[k].Team == snake(k)`.
- D2 Every pool player is in exactly one of `Available` and `History`; no player is drafted twice.
- D3 The rosters together hold exactly `History`; team t holds one player per turn it has had.
- D4 `IsComplete` iff `OverallPick == N`.
- D5 (not enforced) player ids are unique, and the pool has at least N players, so every `OnClock` state has a legal move. Holds for every shipped file:
  233-300 players, no duplicate ids, against 192 picks. It becomes reachable once league size is user-set (the planned Settings screen): 16 teams x 18 = 288 picks exceed the 2019-2025 files.

## 2. Practice draft session (`PracticeDraft`, App) - explicit pause flag, implicit phases

One session per app run (a DI singleton). The bots' turns are a transient phase inside the constructor and `Draft`; no caller ever sees it.

| State | Meaning |
|---|---|
| `BotsPicking` | transient: the bots pick until the user's turn or the end (`AdvanceToMyTurn`) |
| `MyTurn.Guarded` | user on the clock, clock running, the advice has been up for less than `RepeatGuard` (0.5 s): picks refused, Draft buttons greyed out |
| `MyTurn.Running` | user on the clock, clock running, `AcceptsPicks` |
| `MyTurn.Paused` | user on the clock, clock stopped, drafting refused |
| `Complete` | every roster full, `Advice` null |

`MyTurn.Guarded` and `MyTurn.Running` differ only by `ElapsedOnPick` (paused time does not count), so the move between them is the clock passing `RepeatGuard`, not a call.

| From | Event | Guard | To | Effect |
|---|---|---|---|---|
| (new) | constructor | - | `BotsPicking` -> `MyTurn.Guarded` (or `Complete`) | bots for every team but `Slot`; advice computed; then the clock starts |
| `MyTurn.Guarded` | time passes `RepeatGuard` | - | `MyTurn.Running` | the screen re-renders as the buttons unlock |
| `MyTurn.Running` | `Draft(id, pick)` | `pick` is the current pick, `id` available | `BotsPicking` -> `MyTurn.Guarded` at the next pick, or `Complete` | `Changed` raised once; advice recomputed; clock restarted |
| `MyTurn.Running` | `Draft(id, pick)` | `pick` is another pick, or `id` gone or unknown | `MyTurn.Running` | returns false, no `Changed` |
| `MyTurn.Guarded` / `MyTurn.Paused` | `Draft(id, pick)` | - | unchanged | returns false |
| `MyTurn.Guarded` / `MyTurn.Running` | `Pause()` | - | `MyTurn.Paused` | clock stops; `Changed` |
| `MyTurn.Paused` | `Resume()` | - | `MyTurn.Guarded` or `MyTurn.Running` (by time on the pick) | clock start moved forward by the time paused; `Changed` |
| `MyTurn.Paused` | `Pause()` / `MyTurn.*` `Resume()` | - | unchanged | no-op |
| `Complete` | `Draft` / `Pause` / `Resume` | - | `Complete` | false / no-op |

Invariants (between calls):
- P1 `Complete` or `State.CurrentTeam == Slot`.
- P2 `Advice is null` iff `Complete`; otherwise `Advice.Pick == OverallPick + 1` and `Advice.NextPick == State.NextPick(Slot)`.
- P3 `IsPaused` implies not `Complete`.
- P4 `ElapsedOnPick >= 0` and grows only while running (monotonic `TimeProvider` timestamps; it was the wall clock before ISSUE-4).
- P5 A pick is taken only for the pick whose advice the user acted on (`Draft(id, pick)` checks the number), and only once that advice has been up for `RepeatGuard`
  (ISSUE-1, fixed).
- P6 (not enforced) `0 <= Slot < Teams`. Outside it no turn ever comes, and the draft runs to `Complete` in the constructor. The app always passes 4; `MockDraft` checks it.

## 3. Screen navigation (`Root`, `AppShell`) - implicit

| State | Mounted component | Subscriptions |
|---|---|---|
| `Draft` (initial) | `DraftScreen` | `Session.Changed`, plus a 1 s re-render timer from first render to dispose |
| `Players` | `PlayersScreen` | `Session.Changed` |
| `Board` | `BoardScreen` | `Session.Changed` |

Transitions: any state to any state on a nav click (`OnNavigate`); the previous screen is disposed and unsubscribes.
Invariants: N1 exactly one screen is mounted; N2 the `Changed` subscribers are exactly the mounted screen; N3 only `DraftScreen` changes the session (draft, pause, resume).
Screen-local state (the Players filter and search) is lost on navigation by design.

## 4. Draft screen view (`DraftScreen`) - implicit, derived from the session

| View | Condition | Shows |
|---|---|---|
| `Finished` | `Advice is null` | the user's picks in order |
| `OnClock.HasNextPick` | `Advice.NextPick` is set | clock, "take now or wait until #next" band with position tiles, cards with Draft buttons, roster, past the wall |
| `OnClock.LastPick` | `Advice.NextPick` is null (the user's last pick) | "Your last pick / Take the best player left." in place of the band, no tiles (ISSUE-3, fixed) |
| `.Locked` overlay | `!Session.AcceptsPicks` (guarded or paused) | Draft buttons disabled |
| `.Paused` overlay | `Session.IsPaused` | "Paused" badge, Resume |

The band's tiles cover only positions with a player inside the reach window: at the first picks of a draft (pick 1 in the default league) that is RB and WR only, by design.

| Event | Guard | Effect |
|---|---|---|
| click Draft on card k | button enabled | `Session.Draft(card k, advice.Pick)`; the screen re-renders with the next pick (the call returns within about 20 ms on the 2026 file), buttons locked |
| unlock timer (one-shot, `RepeatGuard` after the advice appeared) | - | re-render: buttons enabled |
| click Pause / Resume | - | `Session.Pause()` / `Resume()`; a resume inside the guard reschedules the unlock |
| clock timer tick (1 s) | - | re-render (the clock) |
| `Session.Changed` | - | rebuild the roster card, re-render, schedule the unlock |

Invariant V1: a Draft click drafts the player on the card the user saw, at the pick that card was shown for, once per deliberate click (ISSUE-1, fixed).

## 5. Desktop startup (`App.OnStartup`, `PracticeStartup.Open`, `MainWindow`) - implicit lifecycle

No window exists until the draft is open (no `StartupUri`), so every start ends in `Running` or in a message and exit code 1 (ISSUE-2, fixed).

| From | Event | To |
|---|---|---|
| `Starting` | `ProjectionLocator.Find()` returns null | message "Could not find the projections file ...", exit 1 |
| `Starting` | file found, `ProjectionFile.Load` throws (truncated, malformed, wrong schema, unreadable) | message "Could not read the projections file <path>: <reason>", exit 1 |
| `Starting` | file loads but has fewer players than the draft has picks (D5) | message "... has n players; a 12-team draft needs at least 192", exit 1 |
| `Starting` | file found and valid | `PracticeDraft` built (bots play to the user's first turn), then `MainWindow` and its WebView shown: `Running` |
| `Running` | window closed | process ends; the draft is not saved (by design for practice) |

Before the fix the window was created by `StartupUri` and opened the draft in its constructor: a bad file threw an unhandled `XamlParseException`, and a missing file
called `Shutdown()` from inside the constructor.

## 6. Projection file on disk - implicit, across processes

The Python export (`src/data/export_projections.py`, `write`) writes the file the app reads at startup.

| State | Meaning |
|---|---|
| `Absent` | no file |
| `Writing` | the export writes `projections_<season>_v1.json.tmp` next to it; readers still see the previous file (or none) |
| `Written` | `os.replace` swapped the complete file in at once |

Before the fix `Path.write_text` truncated the file and wrote it in place, so a reader in that moment saw partial JSON (ISSUE-2). On Windows the rename fails while
another process has the file open; the app holds it only while reading it at startup, so an export that runs into that fails loudly, leaving the old file whole and the `.tmp` file beside it.

## 7. Console mock draft (`MockDraft`, Sim) - explicit loop

| State | Event | To |
|---|---|---|
| `BotTurn` | bot picks a legal player | next turn |
| `HumanTurn.Prompt` | Enter / `1`..`5` / `a` / `v` / a unique name match | pick made, next turn |
| `HumanTurn.Prompt` | name with several matches | `HumanTurn.Disambiguate` |
| `HumanTurn.Disambiguate` | valid number | pick made; anything else back to `Prompt` |
| `HumanTurn.*` | `q` or end of input | `Abandoned` (returns false) |
| last pick made | - | `Finished` (summary, returns true) |

Invariant M1: every chosen player is available (each path picks from `Available`, the legal list or the suggestions). The human may take a player the bots' roster rules would block;
the screen marks him, by design. No violation found.

## Invalid states and transitions found

How they were found: a throwaway harness played 72 full practice drafts on the 2026 file (every slot, 2 seeds, always card 1, 2 or 3), checked D1-D4 and P1-P3 after every call,
and rendered all three screens at every pick. No invariant broke and no screen threw. Separately, a test renderer whose display updates stay unacknowledged (like the WebView
while the browser applies a batch) replayed clicks, and the desktop app was launched against a truncated file.

### ISSUE-1 (high, fixed): one gesture can make two picks, the second from advice the user never saw

Picks cannot be undone, so an accidental pick costs a round.

- 1a Double-click on Draft. `Draft` returns in about 20 ms (median over a 2026 draft), then the screen re-renders with the next pick's cards in the same places. The second click of a
  double-click (up to 500 ms later at the Windows default) lands on the next pick's Draft button and drafts that card too. Nothing guards it: the session accepts any click
  that names an available player on the user's turn. This holds at every pick for every slot, because the bots' picks are instant.
- 1b Stale click before the screen updates. A click sent before the browser applied the previous update still runs the old button's handler (Blazor keeps the old handler bound until
  the batch is acknowledged). The handler drafts the old card's player at the next pick if he is still there. Reproduced: slot 1, pick 24, card 1 (J. Allen) then card 2 (G. Pickens)
  before the update; Pickens was drafted at pick 25. Slots 1 and 12 pick twice in a row at each turn, so the old card is nearly always still there.
- Root cause: P5/V1 are not enforced. A draft request does not say which pick it was made for, and nothing separates two clicks of one gesture.

### ISSUE-2 (medium, fixed): startup has no handled failure path

- 2a A projection file that fails to load kills the app with an unhandled exception and no message. Reproduced: the desktop exe with `DRAFTBOT_PROJECTIONS` pointing at a truncated
  file exits at once with `XamlParseException` wrapping `JsonException` (stack: `MainWindow..ctor` -> `CreatePracticeDraft` -> `ProjectionFile.Load`).
- 2b The export writes the live file in place (`Path.write_text`), so starting the app while an export runs reads a truncated file and hits 2a.
- 2c The missing-file path calls `Application.Current.Shutdown()` inside the `StartupUri` window's constructor and returns, so WPF goes on to show a half-built window without its
  WebView while it shuts down. Not observed directly; it goes away with the fix for 2a, which decides before any window exists.

### ISSUE-3 (low, fixed): the last pick's advice talks about waiting

At the user's last pick (`NextPick` null) the band reads "Take now or wait until #?". Every tile says "Likely still there at #" and "Can wait", and the explanation says the
positions "can wait". There is no later pick. Seen at the last pick of all 72 harness drafts. The "Your next pick: None" box beside it is correct.

### ISSUE-4 (low, fixed): the pick clock reads the wall clock

`ElapsedOnPick` subtracts `DateTime.UtcNow` values. If the system clock is set back during a pick (a time sync), the elapsed time goes negative and the clock shows more than
1:30 (P4). It also started before the advice was computed, not when it was produced as documented (about 20 ms, negligible).

### Checked, not reachable now

- D5 (duplicate ids, pool smaller than N): not reachable with any shipped file or the fixed league; it becomes reachable with user-set league sizes (planned Settings screen). If
  the pool runs dry the bots throw inside `AdvanceToMyTurn` after the state has moved, leaving `Advice` from the previous pick (P2 broken). Guard it when league size becomes a setting.
- P6 (slot outside the league): the app passes a constant.
- Concurrency inside a pick: the advisor's re-rankings (`Parallel.For` in `DraftAdvisor.TopShares`) only read the draft state, each on its own copy, while the UI thread waits. The
  clock timer reaches the session only through `InvokeAsync`, on the renderer's thread.
- A Draft click while paused: the buttons are disabled and the session refuses it. Pause/Resume clicked twice toggles twice, which is what two clicks mean.

### Left as is

- The "Too early for this pick" tooltip on cards 2-3 ends "he may well be the right pick a little later", which is wrong at the last pick. The reach cost still applies
  there (the advisor is frozen until 2026 is scored), so only the wording is off. Not changed.

## Issue status

The 1b, 2a and 3 failures were reproduced before their fixes (see each issue). After the fixes the 72-draft harness found no violation of D1-D4 or P1-P3, no render error,
and no "#?" left on any screen. The C# suite is at 208 tests.

| Issue | Status | Fix | Regression tests |
|---|---|---|---|
| ISSUE-1 | fixed 2026-11-06 | `PracticeDraft.Draft(playerId, pick)` refuses any pick but the current one; `RepeatGuard` (0.5 s, the Windows double-click time, chosen by the user over 1 s and a confirm step) refuses picks until the advice has been up that long, and `DraftScreen` greys out its buttons until then and re-renders as they unlock | `StateMachineTests`: `A_click_sent_before_the_screen_showed_the_next_pick_does_not_draft_at_that_pick` (a renderer that never acknowledges its display updates), `A_draft_request_for_another_pick_is_refused_even_when_the_player_is_still_there`, `The_second_click_of_a_double_click_does_not_draft_at_the_next_pick`, `The_draft_buttons_are_disabled_until_the_new_picks_advice_has_been_up_for_the_guard`, `Paused_time_does_not_count_toward_the_guard` |
| ISSUE-2 | fixed 2026-11-06 | `PracticeStartup.Open` turns every failure (missing, unreadable, malformed, wrong schema, too few players) into a message; `App.OnStartup` shows it and exits before any window exists; `export_projections.write` writes a temporary file and renames it | `StateMachineTests`: `Startup_*` (4 tests); `tests/test_export_projections.py`: `test_write_replaces_the_file_in_one_step_and_leaves_no_temporary_file`, `test_a_write_that_fails_before_the_rename_leaves_the_old_file_whole`. Checked by hand on the real exe: a truncated file shows the message and starts no WebView; a normal start opens the window |
| ISSUE-3 | fixed 2026-11-06 | at the last pick the band reads "Your last pick / Take the best player left. There is no later pick to wait for, so the cost of waiting does not apply." with no tiles (the user's choice over hiding the band) | `StateMachineTests`: `The_last_pick_says_it_is_the_last_instead_of_weighing_a_wait`, `Every_pick_before_the_last_still_weighs_taking_now_against_the_next_pick` |
| ISSUE-4 | fixed 2026-11-06 | the pick clock uses `TimeProvider` timestamps (injectable) and starts after the advice is computed | `StateMachineTests`: `Setting_the_system_clock_back_during_a_pick_does_not_move_the_pick_clock`, `The_pick_clock_counts_only_time_running_and_restarts_at_each_pick` |

Also kept as a regression test: `Every_pick_of_a_full_draft_keeps_the_draft_and_session_invariants` (D1-D3, P1-P2 at every pick for three slots and card choices).
