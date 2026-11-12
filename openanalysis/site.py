"""Build the website's data from a snapshot: python3 -m openanalysis.site

The snapshot keeps every model any source lists. The site shows the current market:
models released in the last CURRENT_DAYS days that have a score and a price or a cost
per task, one row per Artificial Analysis entry. Everything the pages need (the spread
map, the cheapest model per level, the Australian gap, what changed) is worked out here
so the site only renders it.
"""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from . import config, metrics

CURRENT_DAYS = 90
SITE_DATA = config.ROOT / "site" / "src" / "data" / "today.json"
# A model released this recently is flagged as new.
NEW_DAYS = 14
# Price and score moves smaller than these are not reported as changes.
PRICE_MOVE = 0.05
SCORE_MOVE = 0.5
# Levels below this are not compared in the Australian gap table.
GAP_FLOOR = 30
# Gateway rows are preferred in this order when two rows share an Artificial Analysis entry.
MATCH_RANK = {"exact": 0, "override": 0, "relaxed": 1, "vercel_only": 2, "openrouter_only": 3, "artificial_analysis_only": 4}


def _current(snapshot, days=CURRENT_DAYS):
    """The current market: recent, scored, priced or costed, one row per AA entry."""
    cutoff = (date.fromisoformat(snapshot["snapshot_date"]) - timedelta(days=days)).isoformat()
    rows = [m for m in snapshot["models"]
            if m["intelligence"] and (m.get("release_date") or "") >= cutoff
            and (m["price_aud"] or m["cost_per_task_aud"])]
    best = {}
    for model in rows:
        key = model["ids"]["artificial_analysis"] or model["id"]
        held = best.get(key)
        if held is None or MATCH_RANK.get(model["gateway_match"], 9) < MATCH_RANK.get(held["gateway_match"], 9):
            best[key] = model
    return sorted(best.values(), key=lambda m: (-m["intelligence"]["index"], m["id"])), cutoff


def _cost(model):
    return (model["cost_per_task_aud"] or {}).get("aud")


def _points(model):
    return metrics.whole_points(model["intelligence"]["index"])


def _hosted(model):
    return bool((model["providers_in_australia"] or {}).get("count"))


def _spread(models):
    costed = [m for m in models if _cost(m)]
    summary, per_model = metrics.spread_map(
        [{"id": m["id"], "cost": _cost(m), "intelligence": _points(m), "index": m["intelligence"]["index"]}
         for m in costed], "cost_per_task_aud")
    return costed, summary, per_model


def _ref(model):
    return {"id": model["id"], "name": model["name"], "creator": model["creator"], "points": _points(model),
            "intelligence": model["intelligence"]["index"], "cost_per_task_aud": _cost(model)}


def _row(model, per_model, by_id, snapshot_date):
    price = model["price_aud"] or {}
    cheapest = price.get("cheapest_available") or {}
    australia = model["providers_in_australia"] or {}
    stats = per_model.get(model["id"])
    swap = by_id.get(stats["dominated_by"]) if stats and stats["dominated_by"] else None
    released = model.get("release_date")
    return {
        "id": model["id"],
        "name": model["name"],
        "creator": model["creator"],
        "release_date": released,
        "new": bool(released) and (date.fromisoformat(snapshot_date) - date.fromisoformat(released)).days <= NEW_DAYS,
        "intelligence": model["intelligence"]["index"],
        "points": _points(model),
        "open_weights": model["open_weights"],
        "on_gateways": model["on_gateways"],
        "cost_per_task_aud": _cost(model),
        "cost_per_task_source": (model["cost_per_task_aud"] or {}).get("source"),
        "price": {
            "input_aud_per_1m": price.get("input_per_1m"),
            "output_aud_per_1m": price.get("output_per_1m"),
            "blended_aud_per_1m": price.get("blended_3to1_per_1m"),
            "source": price.get("source"),
            "cheapest_blended_aud_per_1m": cheapest.get("blended_3to1_per_1m"),
            "cheapest_provider": cheapest.get("provider"),
            "cheapest_gateway": cheapest.get("gateway"),
        } if price else None,
        "australia": {
            "hosted": _hosted(model),
            "providers": sorted({f"{p['provider']} {p['region']}" for p in australia.get("providers", [])}),
            "blended_aud_per_1m": (australia.get("cheapest") or {}).get("blended_aud_per_1m"),
            "vs_list_price": australia.get("vs_list_price"),
        } if australia else None,
        "spread": {
            "on_frontier": stats["on_frontier"],
            "dominates": stats["dominates_count"],
            "beaten_by": stats["dominated_by_count"],
            "better_swap": _ref(swap) if swap else None,
        } if stats else None,
    }


def _ladder(summary, by_id):
    return [{"from": level["intelligence_from"], "to": level["intelligence_to"], **_ref(by_id[level["id"]])}
            for level in summary["cheapest_per_intelligence_level"]]


def _australian_gap(summary, hosted_summary, by_id):
    """At each score where the cheapest choice changes, what staying in Australia costs."""
    needs = sorted({level["intelligence_to"] for s in (summary, hosted_summary)
                    for level in s["cheapest_per_intelligence_level"] if level["intelligence_to"] >= GAP_FLOOR})
    rows = []
    for need in needs:
        onshore_id = metrics.cheapest_at_least(hosted_summary, need)
        anywhere_id = metrics.cheapest_at_least(summary, need)
        if not anywhere_id:
            continue
        onshore = by_id[onshore_id] if onshore_id else None
        anywhere = by_id[anywhere_id]
        rows.append({
            "need": need,
            "australia": _ref(onshore) if onshore else None,
            "anywhere": _ref(anywhere),
            "multiple": round(_cost(onshore) / _cost(anywhere), 1) if onshore else None,
        })
    return rows


def _insights(costed, summary, gap):
    insights = {}
    frontier = summary["frontier"]
    if frontier:
        top = frontier[-1]
        insights["top"] = {"id": top["id"], "points": metrics.whole_points(top["intelligence_index"]),
                           "cost_per_task_aud": top["cost_per_task_aud"]}
    # The sweet spot: the frontier model just before the steepest price jump, from GAP_FLOOR points up.
    steps = [(b["cost_per_task_aud"] / a["cost_per_task_aud"], a, b) for a, b in zip(frontier, frontier[1:])
             if metrics.whole_points(a["intelligence_index"]) >= GAP_FLOOR]
    if steps:
        ratio, before, after = max(steps, key=lambda s: s[0])
        insights["sweet_spot"] = {"id": before["id"], "points": metrics.whole_points(before["intelligence_index"]),
                                  "cost_per_task_aud": before["cost_per_task_aud"], "next_id": after["id"],
                                  "next_points": metrics.whole_points(after["intelligence_index"]),
                                  "next_cost_per_task_aud": after["cost_per_task_aud"], "jump": round(ratio, 1)}
    # Biggest same-score overpay.
    pairs = []
    for model in costed:
        same = [o for o in costed if _points(o) == _points(model) and _cost(o) < _cost(model)]
        if same:
            cheaper = min(same, key=_cost)
            pairs.append((_cost(model) / _cost(cheaper), model, cheaper))
    if pairs:
        ratio, dear, cheap = max(pairs, key=lambda p: p[0])
        insights["overpay"] = {"id": dear["id"], "cheaper_id": cheap["id"], "points": _points(dear),
                               "cost_per_task_aud": _cost(dear), "cheaper_cost_per_task_aud": _cost(cheap),
                               "multiple": round(ratio, 1)}
    worst = max((row for row in gap if row["multiple"]), key=lambda r: r["multiple"], default=None)
    if worst:
        insights["australia_gap"] = worst
    insights["dominated_share"] = round(summary["dominated"] / summary["models"], 3) if summary["models"] else None
    return insights


def _changes(models, previous):
    """What moved since the previous snapshot, among today's current models."""
    if previous is None:
        return None
    before = {m["id"]: m for m in previous["models"]}
    before_slugs = {m["ids"]["artificial_analysis"] for m in previous["models"] if m["ids"]["artificial_analysis"]}
    new, prices, scores = [], [], []
    for model in models:
        old = before.get(model["id"])
        if old is None and model["ids"]["artificial_analysis"] not in before_slugs:
            new.append({"id": model["id"], "name": model["name"], "points": _points(model)})
            continue
        if old is None:
            continue
        now_price = (model["price_aud"] or {}).get("blended_3to1_per_1m")
        was_price = (old["price_aud"] or {}).get("blended_3to1_per_1m")
        if now_price and was_price and abs(now_price / was_price - 1) >= PRICE_MOVE:
            prices.append({"id": model["id"], "name": model["name"], "was": was_price, "now": now_price,
                           "change": round(now_price / was_price - 1, 3)})
        if old["intelligence"] and abs(model["intelligence"]["index"] - old["intelligence"]["index"]) >= SCORE_MOVE:
            scores.append({"id": model["id"], "name": model["name"], "was": old["intelligence"]["index"],
                           "now": model["intelligence"]["index"]})
    return {
        "since": previous["snapshot_date"],
        "new_models": sorted(new, key=lambda m: -m["points"]),
        "price_changes": sorted(prices, key=lambda p: p["change"]),
        "score_changes": scores,
    }


def build(snapshot, previous=None):
    models, cutoff = _current(snapshot)
    costed, summary, per_model = _spread(models)
    hosted_costed = [m for m in costed if _hosted(m)]
    hosted_summary, hosted_per = metrics.spread_map(
        [{"id": m["id"], "cost": _cost(m), "intelligence": _points(m)} for m in hosted_costed])
    by_id = {m["id"]: m for m in models}
    ladder = _ladder(summary, by_id)
    gap = _australian_gap(summary, hosted_summary, by_id)
    rows = [_row(m, per_model, by_id, snapshot["snapshot_date"]) for m in models]
    for row in rows:
        if row["spread"] is not None and row["id"] in hosted_per:
            row["spread"]["on_australian_frontier"] = hosted_per[row["id"]]["on_frontier"]

    everything = snapshot["models"]
    return {
        "date": snapshot["snapshot_date"],
        "generated_at": snapshot["generated_at"],
        "fx": {k: snapshot["fx"][k] for k in ("aud_usd", "usd_to_aud", "rate_date")},
        "current_rule": {"days": CURRENT_DAYS, "released_on_or_after": cutoff},
        "counts": {
            "all_models": len(everything),
            "on_gateways": sum(1 for m in everything if m["on_gateways"]),
            "current": len(models),
            "current_with_cost_per_task": len(costed),
            "current_open_weights": sum(1 for m in models if m["open_weights"]),
            "hosted_in_australia": sum(1 for m in everything if _hosted(m)),
            "current_hosted_in_australia": sum(1 for m in models if _hosted(m)),
            "frontier": len(summary["frontier"]),
            "dominated": summary["dominated"],
        },
        "insights": _insights(costed, summary, gap),
        "frontier": [e["id"] for e in summary["frontier"]],
        "ladder": ladder,
        "australia": {
            "gap": gap,
            "frontier": [e["id"] for e in hosted_summary["frontier"]],
            # Every model a gateway lists in Australia, current or not.
            "hosted": [{"id": m["id"], "name": m["name"], "creator": m["creator"],
                        "intelligence": (m["intelligence"] or {}).get("index"),
                        "current": m["id"] in by_id,
                        "deployments": [{"gateway": p["gateway"], "provider": p["provider"], "region": p["region"]}
                                        for p in m["providers_in_australia"]["providers"]],
                        "blended_aud_per_1m": (m["providers_in_australia"]["cheapest"] or {}).get("blended_aud_per_1m"),
                        "vs_list_price": m["providers_in_australia"]["vs_list_price"]}
                       for m in everything if _hosted(m)],
        },
        "changes": _changes(models, previous),
        "models": rows,
        "attribution": snapshot["attribution"],
    }


def _previous(snapshot_dir, day):
    earlier = sorted(p for p in snapshot_dir.glob("*.json") if p.stem < day)
    return json.loads(earlier[-1].read_text()) if earlier else None


def main(argv=None):
    parser = argparse.ArgumentParser(prog="openanalysis.site", description="Build the website's data from a snapshot.")
    parser.add_argument("--snapshot", type=Path, default=config.DATA_DIR / "latest.json")
    parser.add_argument("--out", type=Path, default=SITE_DATA)
    args = parser.parse_args(argv)

    snapshot = json.loads(args.snapshot.read_text())
    previous = _previous(config.DATA_DIR / "snapshots", snapshot["snapshot_date"])
    data = build(snapshot, previous)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    counts = data["counts"]
    print(f"Site data {data['date']} -> {args.out}: {counts['current']} current models "
          f"({counts['current_with_cost_per_task']} with cost per task), {counts['frontier']} on the frontier")
    return 0


if __name__ == "__main__":
    sys.exit(main())
