[![make.fun · u-tidy-owl-94-9499-winner-takes-all-5-pump-fun-b82c82d3](https://make.fun/badge/u-tidy-owl-94-9499-winner-takes-all-5-pump-fun-b82c82d3.svg)](https://make.fun/bounty/u-tidy-owl-94-9499-winner-takes-all-5-pump-fun-b82c82d3?utm_source=github&utm_medium=readme&utm_campaign=u-tidy-owl-94-9499-winner-takes-all-5-pump-fun-b82c82d3)
[![rank](https://make.fun/badge/u-tidy-owl-94-9499-winner-takes-all-5-pump-fun-b82c82d3/NgademinSikil/makefun-pumpfun-winner/rank.svg)](https://make.fun/bounty/u-tidy-owl-94-9499-winner-takes-all-5-pump-fun-b82c82d3/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=u-tidy-owl-94-9499-winner-takes-all-5-pump-fun-b82c82d3)
[![reward](https://make.fun/badge/u-tidy-owl-94-9499-winner-takes-all-5-pump-fun-b82c82d3/NgademinSikil/makefun-pumpfun-winner/reward.svg)](https://make.fun/bounty/u-tidy-owl-94-9499-winner-takes-all-5-pump-fun-b82c82d3?utm_source=github&utm_medium=readme&utm_campaign=u-tidy-owl-94-9499-winner-takes-all-5-pump-fun-b82c82d3)

# Moonshot Sniper — a pump.fun replay bot for make.fun

A paper-money trading bot for the make.fun bounty
`u-tidy-owl-94-9499-winner-takes-all-5-pump-fun-b82c82d3`
("Winner Takes All — $5 Pump.fun Replay Sprint"): it trades new pump.fun
coins on a 6-hour replay with 10 SOL of starting capital, winner takes all.

## Strategy

The dev window (1,222 coins over 48 hours) teaches one thing: the money is
in a fat tail, not in the average coin. The median coin runs ~18% in its
first two slots, then fades back to its create price — so the average launch
loses to fees, and a fixed take-profit caps the tail and throws the edge
away. The winning pattern from the closest finished bounty of the same kind
("Beat our trading bots on a Solana replay": the winner took +0.55 SOL with
70 fills across 28 coins, tiny ~0.03 SOL scouts, most held under a minute,
profit concentrated in ONE coin) is breadth plus tiny scouts plus letting
one winner run. So this bot buys small and buys often, holds briefly, and
exits at once when the creator sells:

- **Enter:** a coin at most 3 slots old, real SOL in the curve between
  1.0 and 30 SOL, creator's own buy ≤ 2.5 SOL, at most 3 distinct outside
  buyers, creator has not sold. No run-up filter — the filter buys fewer
  coins and often misses the 20-coin guardrail. Buy 0.03 SOL (capped at
  1% of the real SOL reserve per reply, as the harness requires).
- **Exit:** after at most 3 slots held, or at once when the creator sells
  while held, or when the curve completes. No take-profit, no stop-loss:
  the bonding curve bounds the downside (the price cannot fall below the
  create price), so the worst case on a coin is bounded, while the upside
  is the 5–10x tail. No adds, no trailing stop — both lost money in
  testing.
- **Guardrails:** at least 20 coins with a round trip of ≥ 0.01 SOL
  bought, maximum drawdown ≤ 50%. The bot never shorts, never uses
  leverage, and never holds more than 5 positions at once.

## Results on the dev window

Measured with a faithful local replay of the kit's harness, validated
byte-for-byte against the kit's own `grade-local` on the equal-weight
baseline (net PnL −0.019283154 SOL on both), this design is the best of
~90 configurations tested — and it is honest to say every configuration
loses on the dev window on average. The final bot's full dev window:

- **Net PnL −0.227 SOL (−2.27%)**, 578 fills, 7 failed tx, max drawdown
  2.72%, 289 round trips across 289 distinct coins (all ≥ 0.01 SOL) —
  guardrails PASS, prize bar (PnL > 0) FAIL on dev.
- Per 6-hour slice of the dev window: −0.07 to +0.02 SOL (best slice
  +0.0206 SOL); the final is a single 6-hour draw, so the entry is a
  lottery ticket on catching a big runner in that window.
- For comparison the kit's own baselines all lose on dev: sniper −0.465
  SOL, reversion −3.806 SOL, momentum −9.503 SOL. The dev run also
  overstates the final (the memecoin winner scored +4.32 SOL on dev
  against +0.55 SOL in the real race).

The design is chosen for robustness (few knobs, all of them load-bearing)
rather than for overfitting one window: breadth clears the guardrail in
every 6-hour slice (22–60 coins), drawdown stays far under the cap, and
no take-profit means a genuine runner is never sold early.

## Run it

The grader runs it as `python3 -P -s main.py` with `PYTHONHASHSEED=0`.
`main.py` speaks `agent-fun/replay/v2` on stdin/stdout through the
vendored Python SDK shim (`vendor/makefun_bot.py`, a byte-identical copy
of the kit's `sdk/python/makefun_bot.py`). Stdlib only — no third-party
packages, so it also runs on the grader's bare Python runtime.

Grade it on the dev window with the kit's own grader:

```sh
node cli/makefun.mjs grade-local --kit <kit-dir> --bot <this-repo> --driver docker
```

## Bounty

- Bounty: https://make.fun/bounty/u-tidy-owl-94-9499-winner-takes-all-5-pump-fun-b82c82d3
- Pool: $5, winner takes all — $0.50 USDC entry fee + small SOL gas.

Built for make.fun — https://make.fun/r/ds1567x3?ref=ds1567x3
