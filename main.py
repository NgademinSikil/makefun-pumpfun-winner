#!/usr/bin/env python3
"""Moonshot Sniper — a pump.fun replay bot for make.fun's
"Winner Takes All — $5 Pump.fun Replay Sprint" (u-tidy-owl-94-9499-winner-takes-all-5-pump-fun-b82c82d3).

Strategy (chosen from ~90 configurations tested on the kit's dev window with a
faithful local replay, validated byte-for-byte against the kit's own grade-local):
tiny 0.03 SOL scout buys across as many launches as possible, held at most
3 slots, no take-profit and no stop-loss. The dev window teaches that the
median coin runs ~18% in its first two slots and then fades back to its create
price, so the average launch loses to fees; the money, when it comes, comes
from the few coins that keep running. A fixed take-profit caps that tail and
throws the edge away, long holds bleed, and adding into a run-up loses — so
the bot buys small, holds briefly, and exits at once when the creator sells.
Breadth is deliberate: every buy is at least 0.01 SOL (real SOL >= 1.0 at
decision), so every round trip counts toward the 20-coin guardrail, and the
bot clears it in every 6-hour slice of the dev window (22-60 coins).
Stdlib only. Speaks agent-fun/replay/v2 via the vendored Python SDK shim.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bot  # noqa: E402

BPS = 10_000
FEE_BPS = 125  # protocol 95 + creator 30

DEFAULTS = {
    "min_age": 0,
    "max_age": 3,
    "stake_lamports": 30_000_000,
    "min_buy_lamports": 5_000_000,
    "min_real_sol": 1_000_000_000,
    "max_real_sol": 30_000_000_000,
    "min_dev_buy": 0,
    "max_dev_buy": 2_500_000_000,
    "min_buyers": 0,
    "max_buyers": 3,
    "min_runup_bps": 0,
    "max_runup_bps": 1_000_000,
    "min_flow_lamports": -10**15,
    "flow_window": 10,
    "skip_dev_sold": True,
    "buy_slippage_bps": 10_000,
    "tp_bps": 1_000_000,
    "sl_bps": 10_000,
    "trail_arm_bps": 1_000_000,
    "trail_bps": 1000,
    "max_hold": 3,
    "exit_on_dev_sell": True,
    "stale_slots": 1_000_000,
    "max_adds": 0,
    "add_delay": 2,
    "add_step_bps": 0,
    "add_lamports": 50_000_000,
    "add_min_flow_lamports": 0,
    "add_max_age": 13,
}


def load_params():
    return dict(DEFAULTS)


P = load_params()
coins = {}
held = {}
selling = set()


def sell_value(tokens, vq, vt):
    if tokens <= 0 or vt <= 0:
        return 0
    q = (tokens * vq) // (vt + tokens)
    return q - (q * FEE_BPS + BPS - 1) // BPS


class Coin:
    __slots__ = ("mint", "create_slot", "creator", "vq0", "vt0", "dev_buy", "trades",
                 "buyers", "bought", "sold_by_others", "big_sell_bps", "dev_sold",
                 "last_trade_slot", "recent", "buys_sent", "spent_sent", "done", "complete",
                 "last_buy_vq", "last_buy_vt", "last_buy_slot")

    def __init__(self, mint, slot, creator, vq0, vt0):
        self.mint = mint
        self.create_slot = slot
        self.creator = creator
        self.vq0 = vq0
        self.vt0 = vt0
        self.dev_buy = 0
        self.trades = 0
        self.buyers = set()
        self.bought = 0
        self.sold_by_others = 0
        self.big_sell_bps = 0
        self.dev_sold = False
        self.last_trade_slot = slot
        self.recent = []  # (slot, is_buy, sol, user)
        self.buys_sent = 0
        self.spent_sent = 0
        self.done = False
        self.complete = False
        self.last_buy_vq = 0
        self.last_buy_vt = 1
        self.last_buy_slot = 0


def read_events(batch):
    for e in batch["events"]:
        if e["event"] == "CreateEvent":
            coins[e["mint"]] = Coin(e["mint"], e["slot"], e["creator"],
                                    int(e["virtual_quote_reserves"]),
                                    int(e["virtual_token_reserves"]))
        elif e["event"] == "TradeEvent":
            c = coins.get(e["mint"])
            if c is None:
                continue
            sol = int(e["sol_amount"])
            c.trades += 1
            c.last_trade_slot = e["slot"]
            c.recent.append((e["slot"], e["is_buy"], sol, e["user"]))
            is_dev = e["user"] == c.creator
            if e["is_buy"]:
                c.bought += sol
                if is_dev and e["slot"] == c.create_slot:
                    c.dev_buy += sol
                elif not is_dev:
                    c.buyers.add(e["user"])
            elif is_dev:
                c.dev_sold = True
            else:
                c.sold_by_others += sol
                rq_before = int(e["real_quote_reserves"]) + sol
                if rq_before > 0:
                    bps = (sol * BPS) // rq_before
                    if bps > c.big_sell_bps:
                        c.big_sell_bps = bps
        else:  # CompleteEvent
            c = coins.get(e["mint"])
            if c is not None:
                c.complete = True
                c.done = True


def flow(c, slot):
    frm = slot - P["flow_window"]
    while c.recent and c.recent[0][0] <= frm:
        c.recent.pop(0)
    net = 0
    buyers = set()
    for _, is_buy, sol, user in c.recent:
        if is_buy:
            net += sol
            if user != c.creator:
                buyers.add(user)
        else:
            net -= sol
    return net, len(buyers)


def has_pending(state, mint, side):
    for p in state.pending.values():
        if p.order["mint"] == mint and p.order["side"] == side:
            return True
    return False


def on_batch(state, batch):
    read_events(batch)
    orders = []
    cap = state.hello["caps"]["max_orders_per_batch"]
    tx = state.tx_fee_lamports()
    marks = {}
    for m in batch["marks"]:
        marks[m["mint"]] = (int(m["virtual_quote_reserves"]), int(m["virtual_token_reserves"]))

    for f in batch["fills"]:
        if f["client_id"].startswith("_"):
            held.pop(f["mint"], None)
            selling.discard(f["mint"])
            continue
        h = held.get(f["mint"])
        if h is not None and f["status"] != "rejected":
            h["tx_paid"] += int(f["tx_fee_lamports"])
        if f["side"] == "buy" and f["status"] == "filled" and f["mint"] not in held:
            c = coins.get(f["mint"])
            held[f["mint"]] = {"opened_slot": f["slot"], "tx_paid": int(f["tx_fee_lamports"]),
                               "best": 0, "dev_sold_at_open": c.dev_sold if c else False}
    for mint in list(selling):
        if not has_pending(state, mint, "sell"):
            selling.discard(mint)
    for mint in list(held.keys()):
        if mint not in state.positions and mint not in selling and not has_pending(state, mint, "buy"):
            del held[mint]

    # Exits first.
    for mint, pos in list(state.positions.items()):
        if len(orders) >= cap:
            break
        if mint in selling:
            continue
        c = coins.get(mint)
        h = held.get(mint)
        if h is None:
            h = {"opened_slot": state.slot, "tx_paid": tx, "best": 0,
                 "dev_sold_at_open": c.dev_sold if c else False}
            held[mint] = h
        mk = marks.get(mint)
        if mk is None:
            cv = state.curves.get(mint)
            if cv is None:
                continue
            mk = (cv.virtual_quote_reserves, cv.virtual_token_reserves)
        value = sell_value(pos.token_amount, mk[0], mk[1]) - tx
        basis = pos.cost_lamports + h["tx_paid"]
        if value > h["best"]:
            h["best"] = value
        exit_ = False
        if basis > 0:
            if value * BPS >= basis * (BPS + P["tp_bps"]):
                exit_ = True
            if value * BPS <= basis * (BPS - P["sl_bps"]):
                exit_ = True
            if (h["best"] * BPS >= basis * (BPS + P["trail_arm_bps"])
                    and value * BPS <= h["best"] * (BPS - P["trail_bps"])):
                exit_ = True
        if state.slot - h["opened_slot"] >= P["max_hold"]:
            exit_ = True
        if c is not None:
            if P["exit_on_dev_sell"] and c.dev_sold and not h["dev_sold_at_open"]:
                exit_ = True
            if state.slot - c.last_trade_slot >= P["stale_slots"]:
                exit_ = True
        if not exit_:
            continue
        orders.append({"side": "sell", "mint": mint, "token_amount": pos.token_amount,
                       "max_slippage_bps": 10_000})
        selling.add(mint)
        if c is not None:
            c.done = True

    # Entries.
    free = state.free_cash_lamports() - tx * len(orders)
    open_count = state.committed_position_count()
    stake = P["stake_lamports"]
    min_buy = P["min_buy_lamports"]
    for c in list(coins.values()):
        if len(orders) >= cap:
            break
        if c.done or c.complete:
            continue
        age = state.slot - c.create_slot
        if age < P["min_age"]:
            continue
        if c.buys_sent == 0 and age > P["max_age"]:
            c.done = True
            continue
        if c.buys_sent > 0 and age > P["add_max_age"]:
            c.done = True
            continue
        curve = state.curves.get(c.mint)
        if curve is None or curve.complete:
            continue
        vq = curve.virtual_quote_reserves
        vt = curve.virtual_token_reserves
        rq = curve.real_quote_reserves
        if c.buys_sent > 0:
            # Add a tranche while the launch keeps running up.
            if c.buys_sent > P["max_adds"]:
                continue
            if c.mint not in state.positions or c.mint in selling or has_pending(state, c.mint, "buy"):
                continue
            if state.slot - c.last_buy_slot < P["add_delay"]:
                continue
            if vq * c.last_buy_vt * BPS < c.last_buy_vq * vt * (BPS + P["add_step_bps"]):
                continue
            net2, _ = flow(c, state.slot)
            if net2 < P["add_min_flow_lamports"]:
                continue
            max_add = state.max_buy_lamports(c.mint)
            amount = P["add_lamports"] if P["add_lamports"] < max_add else max_add
            if amount < min_buy or free < amount + tx:
                continue
            orders.append({"side": "buy", "mint": c.mint, "quote_lamports": amount,
                           "max_slippage_bps": P["buy_slippage_bps"]})
            free -= amount + tx
            c.buys_sent += 1
            c.spent_sent += amount
            c.last_buy_vq = vq
            c.last_buy_vt = vt
            c.last_buy_slot = state.slot
            continue
        if open_count >= state.hello["caps"]["max_open_positions"]:
            continue
        if c.dev_sold and P["skip_dev_sold"]:
            c.done = True
            continue
        if rq < P["min_real_sol"] or rq > P["max_real_sol"]:
            continue
        if c.dev_buy < P["min_dev_buy"] or c.dev_buy > P["max_dev_buy"]:
            continue
        if c.trades < 0 or len(c.buyers) < P["min_buyers"] or len(c.buyers) > P["max_buyers"]:
            continue
        if c.bought > 0 and c.sold_by_others * BPS > c.bought * 10_000:
            continue
        runup = (vq * c.vt0 * BPS) // (vt * c.vq0)
        if runup > P["max_runup_bps"] or runup < P["min_runup_bps"]:
            continue
        net, nbuyers = flow(c, state.slot)
        if net < P["min_flow_lamports"]:
            continue
        room = stake - c.spent_sent
        if room < min_buy:
            continue
        max_buy = state.max_buy_lamports(c.mint)
        amount = room if room < max_buy else max_buy
        if amount < min_buy:
            continue
        if free < amount + tx:
            continue
        orders.append({"side": "buy", "mint": c.mint, "quote_lamports": amount,
                       "max_slippage_bps": P["buy_slippage_bps"]})
        free -= amount + tx
        c.buys_sent += 1
        c.spent_sent += amount
        c.last_buy_vq = vq
        c.last_buy_vt = vt
        c.last_buy_slot = state.slot
        open_count += 1
    return orders


if __name__ == "__main__":
    makefun_bot.run(on_batch)
