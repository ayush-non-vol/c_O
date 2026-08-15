"""Officer & Lawbreaker - a Discord-native social deduction minigame.

Package layout:
    constants.py  - Phase/Role/Mode/TaskContent enums, tunable limits
    modes.py      - mode -> extra-role-pool logic, plus the descriptive
                    copy used by /modes, /roles, and role-DM embeds
    tasks.py      - validator primitives, the Task type, the SFW and 18+
                    crime/innocent pools, and the shuffle-bag drawer
    state.py      - PlayerState/Game dataclasses, GameManager, role+task
                    assignment (mode- and task-content-aware)
    scoring.py    - Session/SessionManager (a session outlives any single
                    Game) and score_round, the individual-performance
                    point calculation read by resolve_round
    views.py      - Discord UI (role-reveal button, shoot select+confirm,
                    hunch select)
    embeds.py     - embed copy, kept separate from command logic
    cog.py        - slash commands, round timer, resolution, the
                    on_message task-completion listener
"""
