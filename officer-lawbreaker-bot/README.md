# Officer & Lawbreaker

A Discord-native social deduction minigame (Mafia/Werewolf x Spyfall): one
**Lawbreaker** has a secret task to work into ordinary chat, one **Officer**
has one shot to catch them, everyone else is an **Innocent** running a decoy
task of their own. Built in Python on `discord.py` 2.7.

On top of the core game, the host can pick a **mode** (unlocking more roles
with real abilities as the lobby gets bigger) and a **task content** rating
(SFW / 18+ / Mixed) - see [Modes](#modes), [Roles](#roles), and
[Task pools](#task-pools) below. Both default to the original Classic/SFW
behavior, so a lobby that never touches `/config` plays exactly the game
this bot always played.

## 1. Discord Developer Portal setup

1. Go to the [Developer Portal](https://discord.com/developers/applications) → **New Application**.
2. **Bot** tab → **Reset Token** → copy it (you'll paste it into `.env` below). Keep this secret; anyone with it can log in as your bot.
3. Still on the **Bot** tab, under **Privileged Gateway Intents**, turn on:
   - **Message Content Intent** - required. Tasks are checked against ordinary chat messages, not just slash commands.
   - **Server Members Intent** - required. Used to resolve display names and DM roles reliably.
4. **OAuth2 → URL Generator**: scopes `bot` + `applications.commands`; bot permissions `Send Messages`, `Embed Links`, `Read Message History`, `Use Slash Commands`. Open the generated URL to invite the bot to your test server.

Both intents above are self-serve toggles under 100 servers. Formal bot
verification only kicks in past that, and there's a separate 10,000-user
threshold that gates privileged-intent access beyond the portal toggle -
irrelevant for a test server, worth knowing the day this goes public.

## 2. Install

```powershell
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Paste your bot token into `.env`.

## 3. Run

```powershell
python main.py
```

First run can take up to an hour for global slash commands to propagate;
they're usually instant on the server you tested with during development.

## 4. Run the tests

Pure logic and orchestration, no live Discord connection needed:

```powershell
python tests\test_tasks.py
python tests\test_state.py
python tests\test_scoring.py
python tests\test_timing.py
python tests\test_modes.py
python tests\test_integration.py
```

(or `pip install pytest` and run `pytest tests\` if you'd rather.)

## Commands

| Command | Who | Phase | Does |
|---|---|---|---|
| `/join` | anyone | - | Joins the lobby in this channel, creating one if needed (first joiner becomes host) |
| `/leave` | anyone in the lobby | Lobby only | Leaves before the game starts; host leaving promotes the next-earliest joiner |
| `/gamestatus` | anyone | any | Shows the lobby list, or time left in an active round |
| `/config` | host | Lobby only | Sets `mode` and/or `content` for this lobby - see [Modes](#modes) and [Task pools](#task-pools) |
| `/modes` | anyone | any | Shows all four modes and how to set one |
| `/roles` | anyone | any | Shows every role, what unlocks it, and what it does |
| `/about` | anyone | any | The elevator pitch - what this bot is, in a few lines |
| `/howtoplay` | anyone | any | Full step-by-step walkthrough, including every role's ability |
| `/startgame` | host | Lobby only | Starts the game; optional `round_minutes` (2-1440, default 5) |
| `/shoot` | Officer | Active round only | Opens a private suspect picker with a confirm step before it fires |
| `/tip` | Snitch (Wildcard+) | Active round only | One-time private check: has the crime landed yet? |
| `/hunch` | Vigilante (Chaos+) | Active round only | Privately locks in who you think the Lawbreaker is - changeable anytime, bragging rights only |
| `/endgame` | host or a mod (Manage Server) | any | Cancels the lobby or round immediately |
| `/startsession` | anyone | any | Starts a scoring session for this channel - see [Scoring](#scoring) |
| `/leaderboard` | anyone | any | Shows the current session's point standings |
| `/endsession` | whoever started it, or a mod (Manage Server) | any | Ends the session and posts the final standings |

Min players: 3 (Officer + Lawbreaker + at least one Innocent). Max: 10 for
this version - see "Not included" below.

## How a round resolves

- Officer shoots the Lawbreaker → **Officer wins**.
- Officer shoots the wrong person → **Lawbreaker wins**.
- Time runs out, crime task was completed → **Lawbreaker wins**.
- Time runs out, crime task was never completed → **Officer wins** (this
  is what stops a Lawbreaker from just going quiet for a free stalemate).
- If a **Double Agent** is in play (Chaos+) and completes their own decoy
  task, that counts as the crime task being completed too - even if the
  Lawbreaker hasn't finished theirs. Nothing else changes any of the above;
  it's the one place an extra role touches the actual win condition.

## Scoring

`/startsession` opens a running point board for the channel - every game
that resolves from then until `/endsession` adds to it, regardless of how
many separate lobbies/games that ends up being. `/leaderboard` checks the
standings anytime without closing the session out.

Points are entirely **individual**, never "your side won" - the resolution
embed already gives the team result its own recap, so the session board
answers a different question: who's actually been playing well, round after
round, independent of which side ended up winning.

| Who | Earns points for |
|---|---|
| Officer | Correctly naming the Lawbreaker with `/shoot` (+2) |
| Lawbreaker | Completing their own crime task (+1), and evading a *wrong* `/shoot` (+2) - timing out with no shot fired at all doesn't count as evading anything |
| Innocent, Detective, Snitch | Completing their own task (+1) |
| Vigilante | Completing their own task (+1), plus a correct `/hunch` (+1) |
| Double Agent | Completing their own task (+1), plus a bonus (+1) on any round where that completion is what covered for the Lawbreaker's crime |
| Mimic | Completing their own task (+1), plus a bonus (+1) if the side they were secretly rooting for won |

A cancelled game (`/endgame`) never scores - only a round that actually
resolves adds to the board. Sessions are in-memory like everything else
here (see the top of `game/state.py`), so they don't survive a bot restart.

## Modes

Set with `/config mode:<mode>` during the lobby phase (host only); see it
rendered in-app with `/roles`. Every mode below is additive - Officer,
Lawbreaker, and Innocent are always in play; a mode only decides which
*extra* roles might join them, and how many of the lobby's seats they take.
Extra roles never take a seat that isn't there: at 3 players, every mode
short of the guaranteed Officer + Lawbreaker still behaves like Classic,
since there's no room for anything else.

| Mode | Adds | Recommended |
|---|---|---|
| **Classic** | Nothing - the original game | Any size (3+) |
| **Wildcard** | Detective (4+ players), then Snitch (6+) | 4+ |
| **Chaos** | Detective + Snitch from the start, then Double Agent (6+), then Vigilante (8+) | 6+ for the full set |
| **Crimson** | A shuffled mix of Detective/Snitch/Vigilante/Double Agent/Mimic - which ones actually show up varies game to game | 6+ |

Chaos is *tiered* (each extra role has its own fixed threshold, so a bigger
lobby predictably unlocks more). Crimson is *shuffled* instead (the whole
candidate pool - Mimic included - is shuffled and only as many as fit get
used), which is what makes it the "you don't know what's in play" mode
rather than just Chaos-with-a-different-role-list.

## Roles

Full abilities and unlock tiers: run `/roles` in Discord, or see the table
below. Every extra role gets a completely normal decoy task and is checked
by `on_message` exactly like an Innocent - the ability is bonus info
delivered privately in the role DM (and partly revealed in the final case
file), never something that changes how the round is played or resolved.

| Role | Unlocked by | Ability |
|---|---|---|
| Officer | Core | One `/shoot` to accuse the Lawbreaker |
| Lawbreaker | Core | Has the real crime task to hide in plain sight |
| Innocent | Core | Decoy task, no ability - pure camouflage |
| Detective | Wildcard+ | DM'd a lead naming several players (always including the Lawbreaker) - scales with lobby size: 3 names at 5 players, 4 at 6, 5 at 8, 6 at 10+. The Officer is just another candidate for the lead, so they may or may not be named. |
| Snitch | Wildcard+ (6+ players) | One-time `/tip`: has the crime landed yet? |
| Vigilante | Chaos+ (8+ players) | Private `/hunch` guess, changeable anytime - revealed (bragging rights only) at the end |
| Double Agent | Chaos+ (6+ players) | Knows the Lawbreaker; completing their own task also completes the Lawbreaker's crime |
| Mimic | Crimson only | Secretly rooting for a side to win - revealed only in the final case file |

A Detective's lead, a Snitch's tip, and a Vigilante's hunch are never shown
to anyone but that one player mid-round - the only place any of this
becomes public is the end-of-round recap, after the outcome is already
locked in.

## What the UI does

- **One live lobby card, not a growing pile of embeds.** `/join` and
  `/leave` edit the same message in place; short public one-liners
  ("**Alex** joined (4/10)") still ping the channel so people notice,
  without re-posting the whole roster embed every time.
- **Discord's own dynamic timestamps do the countdown work.** Round-end
  times render as `<t:...:R>` ("in 4 minutes") and stay live in everyone's
  client for free - no polling, no repeated edits on the bot's end.
- **One "down to the wire" ping per round**, timed to 10% of the round
  length (floored at 10s, capped at 5 min), so a 2-minute round and a
  24-hour round both get a warning that actually means something.
- **Role DMs go out concurrently**, not one at a time - a full 10-player
  lobby isn't waiting on 10 sequential Discord API round-trips.
- **A themed palette** (blue/Officer, dark red/Lawbreaker, green/Innocent,
  blurple/lobby) stays consistent from role reveal through the final case
  file, plus a block-character progress bar (`████░░░░`) on `/gamestatus`
  during an active round.
- **Stale UI says so.** The `/shoot` suspect picker and its confirm step
  grey themselves out and explain what happened if left untouched past
  their timeout, instead of just quietly going dead.

## Design decisions made along the way

A few things were left open and decided here rather than asked about -
easy to revisit if you want it the other way:

- **Round length is host-set, not voted.** `/startgame round_minutes:15`
  asks the one person already driving the lobby, instead of adding a
  whole separate voting phase (and tie-break logic) for a low-stakes
  setting. The 2 min-24 hr range is enforced by Discord itself via the
  slash command's min/max, so a bad value can't even be typed in.
- **`/endgame` uses the same permission model as starting the game**
  (host-controlled), plus a Manage Server override so a game can't get
  stuck if the host disappears mid-round - relevant now that rounds can
  run up to 24 hours.
- **`/leave` only works pre-game.** Once roles are out, an empty seat is
  either a dead Lawbreaker task or a missing juror - both break the
  round's logic more than they help. The round timer and `/shoot` still
  resolve things normally even if someone goes idle; `/endgame` is the
  clean way out mid-round.
- **The shoot flow is always a select menu**, even for 3-player games,
  rather than switching between buttons and a select past 5 players -
  one code path, one behavior to learn.
- **State is in-memory** (a `dict` per channel), same tradeoff the
  original design notes called out: simple and correct, but a bot
  restart wipes any game in progress. Worth a second thought now that a
  round can legitimately run for hours - a crash-and-restart mid-round
  loses that round. SQLite is the natural upgrade if that ever bites.
- **The lobby card is edited, join/leave events still get a short public
  line.** Full silence felt too quiet for something social; a full embed
  on every join/leave felt like spam. A one-line ping plus one
  always-current card splits the difference.
- **The warning ping is 10% of round length, floored/capped.** No brief
  said how "down to the wire" should scale from a 2-minute round to a
  24-hour one - percentage-of-length with sane floor/cap felt like the
  natural answer.
- **Extra roles are additive, never a replacement mechanic.** Every mode
  past Classic still runs the exact same single-round, one-shot,
  task-in-chat game - an extra role is just bonus private info (or, for
  the Double Agent, one small hook into task-completion) layered on top,
  never a new phase, a new way to be eliminated, or a second win
  condition to referee. That's a deliberate scope call: it's what let five
  new roles and four modes plug in without touching the round timer, the
  resolution logic, or the on_message dispatch (bar one `if` for the
  Double Agent).
- **Crimson shuffles; Chaos doesn't.** Chaos's extra roles each have their
  own fixed player-count threshold (predictable, tiered escalation).
  Crimson instead shuffles its whole candidate pool and keeps only as many
  as fit - so at the size where the Mimic first becomes eligible, it's
  genuinely a coin flip whether it (or anything else in the pool) shows up
  at all. Two different flavors of "more roles," not the same mechanism
  reused with different numbers.
- **`/config` is lobby-phase-only and edits the same lobby card**, same
  permission model as `/startgame`. A host can't change the rules out from
  under people already mid-round, and anyone considering `/join`-ing sees
  the mode and task-content rating on the card before they commit -
  especially relevant once `content` can be 18+.
- **18+ content is opt-in, clearly labeled, and never explicit.** SFW is
  the default; a host has to deliberately run `/config content:18+` (or
  `mixed`) to turn it on, and doing so adds a standing warning to the
  lobby card. The pool itself stays at "adult party game" (confessions,
  dating-app drama, corny flirting) rather than anything sexual - the same
  content boundary a game like Cards Against Humanity's base set draws,
  not its more explicit expansions.
- **`/about`, `/howtoplay`, `/modes`, and `/roles` all read from the same
  `MODE_INFO`/`ROLE_INFO` dictionaries in `game/modes.py`**, rather than
  each having its own hand-written copy of what a role or mode does.
  `/howtoplay`'s "roles at a glance" section, for instance, is the same
  blurbs `/roles` uses, just formatted tighter - so a future update to a
  role's ability only needs to happen in one place.
- **`ShuffleBag.draw_many` guarantees unique task *ids*, not just unique
  list positions.** This one's a bug fix, not a feature: `INNOCENT_TASKS`
  deliberately holds the mention-any sentinel twice (so it's twice as
  likely to come up on any single `draw()`), and the original
  `draw_many` didn't account for that - roughly 1 game in 30 could hand
  two Innocents in the same round the literal same task. Found it because
  this update's own tests call `assign_roles_and_tasks` far more times
  than the original suite did, which was often enough to hit it. Fixed at
  the source (every draw now checks by id, with a generic fallback so a
  plain non-Task pool - see this file's own tests - still works
  unchanged), plus a regression test that exercises the real pools at
  real round sizes a couple hundred times rather than once.
- **The round goes "live" (phase flips to `ACTIVE_ROUND`, the timer
  starts) before any role DMs are sent, not after.** Another bug fix:
  DM delivery is a per-player network round-trip, and `on_message` only
  processes messages once the round is active - so in the original
  ordering, a player who received their own DM quickly and immediately
  worked their task into chat could have that message silently ignored
  while a slower delivery to someone else was still in flight. Not just a
  missed notification either - the task genuinely never got marked
  complete, so it was correctly (if confusingly) shown as incomplete at
  round end too. Every player's role and task are already fully assigned
  by the time DMs start going out, so there's no reason `on_message` needs
  to wait for delivery to finish - it doesn't anymore. Covered by a
  regression test that stalls one player's DM mid-delivery and confirms a
  different player's message still counts.
- **The resolution recap now shows a done/not-done status on every task,
  not just the Lawbreaker's.** Innocents' and every special role's own
  task previously only showed the task description, with no way to tell
  who'd actually completed theirs - purely cosmetic (nothing but the
  Lawbreaker's task_complete affects who wins), but confusing to look at
  after the fact.
- **Session scoring (`game/scoring.py`) rewards individual performance,
  never team result.** The alternative - a point for everyone on the
  winning side - was tempting for how little logic it needs, but it means
  a silent Innocent who did nothing all game scores the same as the
  Officer who nailed the read, purely by being on the side that happened
  to win. Scoring what a player personally did instead (their own task,
  the Officer's shot, the Lawbreaker's evasion, a correct hunch, a cover
  that held, a bet that paid off) means the board rewards good individual
  play across a session even on nights where the same side keeps winning.
  A session is its own concept (`Session`/`SessionManager`), independent
  of `GameManager` - it outlives any single `Game`, so `resolve_round`
  reads what it needs via `score_round()` in the one instant before the
  `Game` object is discarded, rather than the session ever holding a
  reference to a game in progress.

## Task pools

`game/tasks.py` has an SFW pool (64 Crime, 64 Innocent) and a second,
opt-in **18+** pool (62 Crime, 61 Innocent - party-game energy:
embarrassing confessions, dating-app drama, corny flirting, think Truth or
Drink, not anything explicit or pornographic - see the content note
below). Both pools are built from 42 reusable validator types - the
original 23 (contains-a-word, all-caps, word count, ends with "?",
contains an emoji, is a reply, mentions someone, etc.) plus a second wave
aimed specifically at being harder to blend into normal chat by accident:
alliteration, a word doubled back-to-back, strictly-increasing word
lengths, a message that starts and ends on the same word (or the same
letter), all five vowels somewhere in one message, a parenthetical aside,
an actual quotation, a semicolon, an ordinal, a month or day of the week,
counting up or down by ones, three punctuation marks in a row, two
*different* emoji, and more - see `game/tasks.py`'s "structural/creative
primitives" section for the full list. Several validator families - and
even a couple of the trigger *words* themselves - appear in **both** sides
of a pool on purpose, in the SFW and 18+ pools independently. Pattern-
matching on task style alone ("all caps = always the crime") stops
working; reading the room is still the Officer's job.

The host picks which pool a lobby draws from with `/config content:<sfw|18+|mixed>`
(SFW is the default - 18+ and Mixed are opt-in, never the other way
around):

- **SFW** - the original-style pool, expanded, family-friendly.
- **18+** - the party-game pool only.
- **Mixed** - both pools shuffled together, so any given player might get
  either flavor of task, unpredictably.

**Content note:** "18+" here means adult-party-game humor - the tamer end
of something like Cards Against Humanity or Truth or Drink - not sexual or
explicit content. Nothing in the pool requires or produces anything you
couldn't say out loud at a party. Setting `content` to anything but SFW
adds a visible warning to the lobby card *before* anyone else joins, so
people can `/leave` (or just not `/join` in the first place) if that's not
what they're looking for.

Both pools (SFW and 18+ alike) are drawn from a shuffle-bag (shuffle once,
hand out front-to-back, reshuffle only once exhausted) shared across every
game the bot is running - so repeats are avoided bot-wide, not just within
one lobby. Add more entries directly to the relevant list in
`game/tasks.py` (`CRIME_TASKS` / `INNOCENT_TASKS` for SFW,
`CRIME_TASKS_18PLUS` / `INNOCENT_TASKS_18PLUS` for 18+); `_text_task(...)`
keeps each one to a single line for the ~18 existing validator types, and
`tests/test_tasks.py` checks id-uniqueness, pool size, and cross-pool style
overlap automatically - for all four pools - so a bad addition fails loudly
instead of quietly weakening the pool.

## Not included (easy follow-ups, not built here)

- **A 2nd Officer/Lawbreaker past ~8 players.** Right now every lobby size
  from 3 to 10 runs a single pair; bigger lobbies get noisier without more
  roles to compensate.
- **Lobby auto-timeout.** A stale, never-started lobby just sits there
  until someone runs `/endgame` or `/join`s past `LOBBY` phase.
- **Stats / SQLite.** Win rate by role, most-caught Lawbreaker, etc. - the
  in-memory design doesn't preclude adding this later.
- **Dev-mode fast timer** for iterating without waiting out a full round.

## Project layout

```
main.py            entry point
game/
  constants.py      Phase/Role/Mode/TaskContent enums, tunable limits
  modes.py           mode -> extra-role-pool logic, /modes + /roles copy
  tasks.py           validators, Task type, SFW + 18+ pools, shuffle-bags
  state.py            PlayerState/Game, GameManager, role+task assignment
  scoring.py          Session/SessionManager, individual-performance scoring
  timing.py            progress bar + warning-offset math (pure, testable)
  views.py               role-reveal button, shoot select+confirm, hunch select
  embeds.py                theme (colors/emoji) + every embed builder
  cog.py                     slash commands, timers, resolution, on_message
tests/
  test_tasks.py     validator + shuffle-bag + pool unit tests (SFW + 18+)
  test_state.py     role/task assignment unit tests (all modes/content)
  test_scoring.py   individual-performance scoring + Session unit tests
  test_modes.py     mode -> role-pool logic unit tests
  test_timing.py    progress bar + warning-offset unit tests
  test_integration.py   Cog orchestration tests (fake Discord objects)
```
