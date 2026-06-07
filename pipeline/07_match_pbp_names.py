"""
Fill canonical_name and position in outputs/{season}/pbp_names.csv from participation data.

Primary source: participation.csv (per-game rosters, full team coverage).
Supplementary: players.csv (position lookup only, after canonical name is resolved).

Rules:
  - Confident unique match -> canonical_name = exact participation player_name, position from players.csv if available
  - Two or more confident matches -> canonical_name = pbp_name, flagged = ambiguous
  - No confident match -> canonical_name = pbp_name, flagged = no_match
  - flagged = no_roster rows are preserved as-is

Usage:
    python pipeline/07_match_pbp_names.py --season 2025-26
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher


FIELDS = ["team", "role", "pbp_name", "canonical_name", "position", "flagged", "review_flag"]
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
NICKNAMES = {
    "alex": {"alexander"},
    "anthony": {"tony"},
    "ben": {"benjamin"},
    "brad": {"bradley"},
    "cam": {"cameron"},
    "charlie": {"charles"},
    "chris": {"christopher"},
    "dan": {"daniel"},
    "dj": {"deejay", "d.j"},
    "eli": {"elijah"},
    "jake": {"jacob"},
    "jay": {"jason", "jayden", "jaden"},
    "joe": {"joseph", "joey"},
    "john": {"johnny", "jonathan", "johnathan"},
    "josh": {"joshua"},
    "kenny": {"kenneth"},
    "matt": {"matthew", "matteo", "mattheo"},
    "mike": {"michael", "mikey"},
    "nick": {"nicholas", "nikolas"},
    "rob": {"robert"},
    "sam": {"samuel"},
    "tj": {"t.j"},
    "tom": {"thomas", "tommy"},
    "tony": {"anthony"},
    "tre": {"trey"},
    "will": {"william"},
    "zach": {"zachary"},
}


def ascii_text(value: str) -> str:
    return unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")


def normalize_name(value: str) -> str:
    value = ascii_text(value).lower()
    value = value.replace("'", "")
    value = re.sub(r"[.,]", " ", value)
    value = value.replace("-", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def tokenize_name(value: str) -> list[str]:
    tokens = [token for token in normalize_name(value).split() if token]
    return tokens


def strip_suffix_tokens(tokens: list[str]) -> list[str]:
    return [token for token in tokens if token not in SUFFIXES]


def equivalent_first_name(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) == 1 and b.startswith(a):
        return True
    if len(b) == 1 and a.startswith(b):
        return True
    if a in NICKNAMES and b in NICKNAMES[a]:
        return True
    if b in NICKNAMES and a in NICKNAMES[b]:
        return True
    return False


def is_prefix_variant(a: str, b: str, *, max_missing: int = 3, min_len: int = 5) -> bool:
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) < min_len:
        return False
    if not longer.startswith(shorter):
        return False
    return len(longer) - len(shorter) <= max_missing


def close_spelling(a: str, b: str, *, min_ratio: float = 0.88) -> bool:
    if a == b:
        return True
    if not a or not b or a[0] != b[0]:
        return False
    ratio = SequenceMatcher(None, a, b).ratio()
    if ratio < min_ratio:
        return False
    return abs(len(a) - len(b)) <= 2


@dataclass(frozen=True)
class Candidate:
    player_name: str
    position: str
    reason: str


def build_player_entry(player_name: str, position: str = "") -> dict[str, object]:
    tokens = tokenize_name(player_name)
    base_tokens = strip_suffix_tokens(tokens)
    first = base_tokens[0] if base_tokens else ""
    last = base_tokens[-1] if len(base_tokens) >= 2 else ""
    middle = tuple(base_tokens[1:-1]) if len(base_tokens) > 2 else ()
    return {
        "player_name": player_name,
        "position": position,
        "tokens": tokens,
        "base_tokens": base_tokens,
        "first": first,
        "last": last,
        "middle": middle,
        "normalized": " ".join(base_tokens),
    }


def normalized_match(name_tokens: list[str], player: dict[str, object]) -> bool:
    return strip_suffix_tokens(name_tokens) == player["base_tokens"]


def suffix_letter_match(name_tokens: list[str], player: dict[str, object]) -> bool:
    if len(name_tokens) != len(player["base_tokens"]) + 1:
        return False
    if name_tokens[-1] not in {"j", "s"}:
        return False
    if strip_suffix_tokens(name_tokens[:-1]) != player["base_tokens"]:
        return False
    player_tokens = player["tokens"]
    return any(token in SUFFIXES for token in player_tokens)


def first_last_match(name_tokens: list[str], player: dict[str, object]) -> bool:
    base_tokens = strip_suffix_tokens(name_tokens)
    if len(base_tokens) < 2 or len(player["base_tokens"]) < 2:
        return False
    pbp_first = base_tokens[0]
    pbp_last = base_tokens[-1]
    roster_first = player["first"]
    roster_last = player["last"]

    if not (
        equivalent_first_name(pbp_first, roster_first)
        or is_prefix_variant(pbp_first, roster_first, max_missing=2, min_len=4)
        or close_spelling(pbp_first, roster_first, min_ratio=0.84)
    ):
        return False

    if not (
        is_prefix_variant(pbp_last, roster_last, max_missing=4, min_len=5)
        or close_spelling(pbp_last, roster_last, min_ratio=0.90)
    ):
        return False

    pbp_middle = tuple(base_tokens[1:-1]) if len(base_tokens) > 2 else ()
    roster_middle = player["middle"]
    if pbp_middle and roster_middle and pbp_middle != roster_middle:
        return False
    return True


def last_name_initial_match(name_tokens: list[str], player: dict[str, object]) -> bool:
    base_tokens = strip_suffix_tokens(name_tokens)
    if len(base_tokens) != 2 or len(player["base_tokens"]) < 2:
        return False
    pbp_first, pbp_last = base_tokens
    roster_first = player["first"]
    roster_last = player["last"]
    if len(pbp_first) != 1:
        return False
    if pbp_first != roster_first[:1]:
        return False
    return is_prefix_variant(pbp_last, roster_last, max_missing=3, min_len=5) or close_spelling(
        pbp_last, roster_last, min_ratio=0.92
    )


def find_candidates(pbp_name: str, roster: list[dict[str, object]]) -> list[Candidate]:
    name_tokens = tokenize_name(pbp_name)
    candidates: dict[tuple[str, str], Candidate] = {}

    for player in roster:
        if normalize_name(pbp_name) == normalize_name(player["player_name"]):
            key = (player["player_name"], player["position"])
            candidates[key] = Candidate(player["player_name"], player["position"], "exact")
            continue

        if normalized_match(name_tokens, player):
            key = (player["player_name"], player["position"])
            candidates[key] = Candidate(player["player_name"], player["position"], "normalized")
            continue

        if suffix_letter_match(name_tokens, player):
            key = (player["player_name"], player["position"])
            candidates[key] = Candidate(player["player_name"], player["position"], "suffix_letter")
            continue

        if first_last_match(name_tokens, player):
            key = (player["player_name"], player["position"])
            candidates[key] = Candidate(player["player_name"], player["position"], "first_last")
            continue

        if last_name_initial_match(name_tokens, player):
            key = (player["player_name"], player["position"])
            candidates[key] = Candidate(player["player_name"], player["position"], "initial_last")

    return sorted(candidates.values(), key=lambda item: (item.player_name, item.position))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default="2025-26")
    parser.add_argument("--out", default="outputs")
    args = parser.parse_args()

    out_dir = os.path.join(args.out, args.season)
    pbp_path = os.path.join(out_dir, "pbp_names.csv")
    participation_path = os.path.join(out_dir, "participation.csv")
    players_path = os.path.join(out_dir, "players.csv")

    # Primary: participation.csv — unique player names per team (no position)
    participation_by_team: dict[str, list[dict[str, object]]] = defaultdict(list)
    seen_participation: dict[str, set[str]] = defaultdict(set)
    with open(participation_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            team = row["team_name"]
            name = row["player_name"]
            if name not in seen_participation[team]:
                seen_participation[team].add(name)
                participation_by_team[team].append(build_player_entry(name))

    # Supplementary: players.csv — position lookup by (team, canonical_name)
    pos_lookup: dict[tuple[str, str], str] = {}
    if os.path.exists(players_path):
        with open(players_path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("pos"):
                    pos_lookup[(row["team_name"], row["player_name"])] = row["pos"]

    with open(pbp_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    stats: Counter[str] = Counter()
    for row in rows:
        row.setdefault("review_flag", "")
        if row["flagged"] == "no_roster":
            stats["no_roster"] += 1
            continue

        roster = participation_by_team.get(row["team"], [])
        candidates = find_candidates(row["pbp_name"], roster)

        if len(candidates) == 1:
            candidate = candidates[0]
            row["canonical_name"] = candidate.player_name
            row["position"] = pos_lookup.get((row["team"], candidate.player_name), "")
            row["flagged"] = ""
            row["review_flag"] = ""
            stats[f"matched_{candidate.reason}"] += 1
            continue

        row["canonical_name"] = row["pbp_name"]
        if len(candidates) > 1:
            row["position"] = "/".join(dict.fromkeys(
                pos_lookup.get((row["team"], c.player_name), "") for c in candidates
            ))
            row["flagged"] = "ambiguous"
            row["review_flag"] = "needs_review"
            stats["ambiguous"] += 1
        else:
            row["position"] = ""
            row["flagged"] = "no_match"
            row["review_flag"] = "needs_review"
            stats["no_match"] += 1

    with open(pbp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Updated {pbp_path}")
    for key, value in sorted(stats.items()):
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
