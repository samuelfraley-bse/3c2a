"""
Apply a conservative in-session review pass to unresolved pbp player names.

This script is intentionally narrow: it only updates rows that were manually
reviewed against the team roster and still looked like clear matches after
considering role, position, and truncation/typo patterns.

Usage:
    python pipeline/10_review_pbp_names_local.py --season 2025-26
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import unicodedata
from collections import Counter, defaultdict


FIELDS = ["team", "role", "pbp_name", "canonical_name", "position", "flagged", "review_flag"]

# (team, pbp_name) -> canonical roster name hint
REVIEWED_MATCHES: dict[tuple[str, str], str] = {
    ("American River", "Jaden Beamon-Sa"): "Jaden Beamon-Santos",
    ("American River", "Kristopher Butt"): "Kristopher Butters",
    ("American River", "MarQuay King-Jo"): "MarQuay King-Johnson",
    ("Bakersfield", "Briton Brown"): "Brenton Brown",
    ("Cerritos", "Dylan Fitu Fale"): "Dylan Fitu Falefitu",
    ("Cerritos", "DeVaughn Garner"): "DeVaughn Garner-Egans",
    ("Canyons", "Damjan Mitrovi&"): "Damjan Mitrović",
    ("Canyons", "Damjan Mitrovi?"): "Damjan Mitrović",
    ("Cerritos", "Elijah Nuhi-Yan"): "Elijah Nuhi-Yandall",
    ("Chabot", "E. Ferrell-Ayer"): "Elijah Ferrell-Ayers",
    ("Chabot", "Elijah Ferrell-"): "Elijah Ferrell-Ayers",
    ("Chaffey", "Christopher Lew"): "Christopher Lewis",
    ("Chaffey", "Joel Avila-Lope"): "Joel Avila-Lopez",
    ("Chaffey", "Laray King-Trot"): "Laray King-Trotter",
    ("Citrus", "Grant Yari"): "Grant Yary",
    ("Coalinga", "Christopher Coo"): "Christopher Cooper",
    ("De Anza", "Diego Ortega-Ge"): "Diego Ortega-Gerow",
    ("De Anza", "My?Zel Br"): "My’Zel Brunson",
    ("De Anza", "Va?inga M"): "Va’inga Mahe Jr.",
    ("Desert", "Jordan Ramirez-"): "Jordan Ramirez-Gomez",
    ("Desert", "Noah Vaughn-Isr"): "Noah Vaughn-Israel",
    ("El Camino", "Christopher Pat"): "Christopher Patino",
    ("Feather River", "J. Hurtado-Pere"): "Julio Hurtado-Perez",
    ("Feather River", "E. Stafford-McN"): "Elijah Stafford-McNutt",
    ("Feather River", "Julio Hurtado-P"): "Julio Hurtado-Perez",
    ("Foothill", "Aaron Davis-Bec"): "Aaron Davis-Beckford",
    ("Foothill", "Boxer Kopcsak-Y"): "Boxer Kopcsak-Yeung",
    ("Fresno City", "Peyton Van Wort"): "Peyton Van Worth",
    ("Fresno City", "Tevita Leka Tuk"): "Tevita Leka Tukimaka",
    ("Fullerton", "Jared Harris-Ca"): "Jared Harris-Cason",
    ("Gavilan", "Dei'Maujae Moor"): "Dei'Maujae Moore",
    ("Gavilan", "Houstyn Lee-Per"): "Houstyn Lee-Perry",
    ("Gavilan", "Israel Chavez-S"): "Israel Chavez-Strand",
    ("Glendale", "Alexander Shirv"): "Alexander Shirvanian",
    ("Glendale", "Zamondre Merriw"): "Zamondre Merriweather",
    ("Golden West", "Kendric Thompso"): "Kendric Thomas",
    ("Golden West", "Kauna'oa Kamaka"): "Kauna'oa Kamakawiwo'ole",
    ("Golden West", "Tanner Schimdt"): "Tanner Schmidt",
    ("Grossmont", "Melvin Spicer I"): "Melvin Spicer IV",
    ("Grossmont", "Tu'ufa'atasi Lu"): "Tu'ufa'atasi Lutau",
    ("Hartnell", "Bryan Ortega-Ba"): "Bryan Ortega-Bautista",
    ("Hartnell", "Efraim Macias R"): "Efraim Macias Reyes",
    ("Long Beach", "Christopher Jac"): "Christopher Jackson",
    ("Modesto", "Sean-Kingston T"): "Sean-Kingston Teu",
    ("Mt. San Antonio", "Sebastian Talam"): "Sebastian Talamantes",
    ("Mt. San Jacinto", "Alijah Sio-Leva"): "Alijah Levao",
    ("Mt. San Jacinto", "Estevon De La T"): "Estevon De La Torre",
    ("Mt. San Jacinto", "Jedi Gbaja-Biam"): "Jedi Gbaja-Biamila",
    ("Orange Coast", "O. Nihipali-Ses"): "Ocean Nihipali-Sesson",
    ("Palomar", "Kayvion Jones-B"): "Kayvion Jones-Bell",
    ("Reedley", "Christopher Cla"): "Christopher Clark",
    ("Riverside", "Devon Nofoa-Mas"): "Devon Nofoa-Masoe",
    ("Riverside", "Jontavious Jame"): "Jontavious James",
    ("Saddleback", "J. Beverly-Rush"): "Jaylen Beverly-Rushing",
    ("San Bernardino Valley", "Duke Annie-Davi"): "Duke Annie-Davis",
    ("San Bernardino Valley", "Dylon Lambert-D"): "Dylon Lambert-Dunn",
    ("San Bernardino Valley", "Dylan Webb-Denn"): "Dylan Webb-Dennis",
    ("San Diego Mesa", "Makai Gray-Virg"): "Makai Gray-Virgil",
    ("San Mateo", "Charleston Waug"): "Charleston Waugh",
    ("San Mateo", "Malakai Ross-Gr"): "Malakai Ross-Graves",
    ("Santa Monica", "Chistopher Thom"): "Chistopher Thompkins",
    ("Santa Monica", "Christopher Was"): "Christopher Washington",
    ("Santa Monica", "Mikael King-Haa"): "Mikael King-Haagen",
    ("Santa Rosa", "Kaylen Baker"): "Kaylan Baker",
    ("Shasta", "Jared Rick Cuen"): "Jared Rick Cuenca",
    ("Shasta", "Malcom I'aukual"): "Malcom I'aulualo",
    ("Shasta", "Porter Lane"): "Porter Layne",
    ("Shasta", 'Rodel "Ivan" Mo'): 'Rodel "Ivan" Morales',
    ("Shasta", "Rodel 'Ivan' Mo"): 'Rodel "Ivan" Morales',
    ("Shasta", "Shavon Gramps-G"): "Shavon Gramps-Green",
    ("Shasta", "Talan Leon Guer"): "Talan Leon Guerrero",
    ("Sierra", "Braden Rohde"): "Braden Rhode",
    ("Sierra", "Christopher O'N"): "Christopher O'Neal",
    ("Siskiyous", "Domenick Barten"): "Domenick Bartenstien",
    ("Ventura", "Love Adabeyo"): "Love Adebayo",
    ("Ventura", "Mason Coso"): "Masen Coso",
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii").lower()
    value = value.replace("'", "")
    value = re.sub(r"[.,()/-]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def resolve_roster_name(team_players: list[dict[str, str]], canonical_hint: str) -> tuple[str, str]:
    hint = normalize(canonical_hint)
    exact = [player for player in team_players if normalize(player["player_name"]) == hint]
    if len(exact) == 1:
        return exact[0]["player_name"], exact[0]["pos"]

    prefix = [
        player
        for player in team_players
        if normalize(player["player_name"]).startswith(hint) or hint.startswith(normalize(player["player_name"]))
    ]
    if len(prefix) == 1:
        return prefix[0]["player_name"], prefix[0]["pos"]

    contains = [player for player in team_players if hint in normalize(player["player_name"])]
    if len(contains) == 1:
        return contains[0]["player_name"], contains[0]["pos"]

    raise ValueError(f"Could not uniquely resolve roster player for hint={canonical_hint!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default="2025-26")
    parser.add_argument("--out", default="outputs")
    args = parser.parse_args()

    out_dir = os.path.join(args.out, args.season)
    pbp_path = os.path.join(out_dir, "pbp_names.csv")
    players_path = os.path.join(out_dir, "players.csv")

    roster_by_team: dict[str, list[dict[str, str]]] = defaultdict(list)
    with open(players_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            roster_by_team[row["team_name"]].append(row)

    with open(pbp_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    stats: Counter[str] = Counter()
    for row in rows:
        row.setdefault("review_flag", "")
        key = (row["team"], row["pbp_name"])
        canonical_hint = REVIEWED_MATCHES.get(key)
        if not canonical_hint:
            continue
        if row["flagged"] not in {"no_match", "ambiguous"}:
            stats["skipped_already_resolved"] += 1
            continue

        player_name, position = resolve_roster_name(roster_by_team[row["team"]], canonical_hint)
        row["canonical_name"] = player_name
        row["position"] = position
        row["flagged"] = ""
        row["review_flag"] = ""
        stats["applied"] += 1

    with open(pbp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Updated {pbp_path}")
    for key, value in sorted(stats.items()):
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
