# Engine Zero production path regression

The proof state transition previously declared `CHALLENGE_WINDOW=10` and
`deadline=$((height + CHALLENGE_WINDOW))` in one Bash `local` invocation. Bash
expands all assignments before applying them: the deadline used an unset or
inherited window. Separate the initialization and arithmetic. The expected
challenge deadline remains inclusion height + 10; no consensus rule changed.

The real native Engine Zero regression now submits a cryptographically valid
proof, produces its block, checks the persisted challenge deadline and rebuilds
derived state to check deterministic recovery. No mocked chain is used.

Block production no longer reports successful network broadcast after a failed
announcement. Local commit, DHT announcement, propagation and remote durability
remain separate outcomes. A solitary fresh validator can create its own chain;
this does not establish a multi-validator network or remote replica.

Executed: `PYTHONPATH=. python3 -m unittest discover -s ci -p test_compute.py -v`
Result: 4 passed, 0 failed, 0 skipped (21.318 seconds). No native compilation.
