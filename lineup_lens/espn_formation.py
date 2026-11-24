"""ESPN formationPlace decoding, using formation-specific Opta slot layouts.
Reference: mplsoccer Opta formation tables, and sdvplot ESPN lineup tutorial.
No inferred formations from jersey numbers or roster order.
"""
import re

SLOTS = {
  "343": [
    [
      1
    ],
    [
      4,
      5,
      6
    ],
    [
      3,
      8,
      7,
      2
    ],
    [
      11,
      9,
      10
    ]
  ],
  "352": [
    [
      1
    ],
    [
      4,
      5,
      6
    ],
    [
      3,
      8,
      11,
      7,
      2
    ],
    [
      9,
      10
    ]
  ],
  "424": [
    [
      1
    ],
    [
      3,
      6,
      5,
      2
    ],
    [
      8,
      4
    ],
    [
      11,
      10,
      9,
      7
    ]
  ],
  "433": [
    [
      1
    ],
    [
      3,
      6,
      5,
      2
    ],
    [
      8,
      4,
      7
    ],
    [
      11,
      9,
      10
    ]
  ],
  "442": [
    [
      1
    ],
    [
      3,
      6,
      5,
      2
    ],
    [
      11,
      8,
      4,
      7
    ],
    [
      9,
      10
    ]
  ],
  "451": [
    [
      1
    ],
    [
      3,
      6,
      5,
      2
    ],
    [
      11,
      8,
      10,
      4,
      7
    ],
    [
      9
    ]
  ],
  "532": [
    [
      1
    ],
    [
      3,
      4,
      5,
      6,
      2
    ],
    [
      11,
      8,
      7
    ],
    [
      9,
      10
    ]
  ],
  "541": [
    [
      1
    ],
    [
      3,
      4,
      5,
      6,
      2
    ],
    [
      11,
      10,
      8,
      7
    ],
    [
      9
    ]
  ],
  "3142": [
    [
      1
    ],
    [
      6,
      4,
      5
    ],
    [
      8
    ],
    [
      3,
      11,
      7,
      2
    ],
    [
      10,
      9
    ]
  ],
  "3241": [
    [
      1
    ],
    [
      4,
      5,
      6
    ],
    [
      3,
      2
    ],
    [
      11,
      8,
      7,
      10
    ],
    [
      9
    ]
  ],
  "3412": [
    [
      1
    ],
    [
      4,
      5,
      6
    ],
    [
      3,
      8,
      7,
      2
    ],
    [
      9
    ],
    [
      11,
      10
    ]
  ],
  "3421": [
    [
      1
    ],
    [
      4,
      5,
      6
    ],
    [
      3,
      8,
      7,
      2
    ],
    [
      11,
      10
    ],
    [
      9
    ]
  ],
  "3511": [
    [
      1
    ],
    [
      4,
      6,
      5
    ],
    [
      3,
      8,
      11,
      7,
      2
    ],
    [
      10
    ],
    [
      9
    ]
  ],
  "4132": [
    [
      1
    ],
    [
      3,
      6,
      5,
      2
    ],
    [
      4
    ],
    [
      11,
      8,
      7
    ],
    [
      10,
      9
    ]
  ],
  "4141": [
    [
      1
    ],
    [
      3,
      6,
      5,
      2
    ],
    [
      4
    ],
    [
      11,
      10,
      8,
      7
    ],
    [
      9
    ]
  ],
  "4222": [
    [
      1
    ],
    [
      3,
      6,
      5,
      2
    ],
    [
      8,
      4
    ],
    [
      11,
      7
    ],
    [
      9,
      10
    ]
  ],
  "4231": [
    [
      1
    ],
    [
      3,
      6,
      5,
      2
    ],
    [
      4,
      8
    ],
    [
      11,
      10,
      7
    ],
    [
      9
    ]
  ],
  "4312": [
    [
      1
    ],
    [
      3,
      6,
      5,
      2
    ],
    [
      11,
      4,
      7
    ],
    [
      8
    ],
    [
      10,
      9
    ]
  ],
  "4321": [
    [
      1
    ],
    [
      3,
      6,
      5,
      2
    ],
    [
      7,
      4,
      8
    ],
    [
      11,
      10
    ],
    [
      9
    ]
  ],
  "4411": [
    [
      1
    ],
    [
      3,
      6,
      5,
      2
    ],
    [
      11,
      8,
      4,
      7
    ],
    [
      10
    ],
    [
      9
    ]
  ],
  "31213": [
    [
      1
    ],
    [
      4,
      5,
      6
    ],
    [
      8
    ],
    [
      3,
      2
    ],
    [
      7
    ],
    [
      11,
      9,
      10
    ]
  ],
  "41212": [
    [
      1
    ],
    [
      3,
      6,
      5,
      2
    ],
    [
      4
    ],
    [
      11,
      7
    ],
    [
      8
    ],
    [
      9,
      10
    ]
  ]
}

def decode(group, players):
    raw=str(group.get("formation") or "").strip()
    if not re.fullmatch(r"[1-5](?:-?[1-5]){1,5}",raw):
        return None
    key=raw.replace("-","")
    rows=SLOTS.get(key)
    if not rows:
        return None
    starters=[p for p in group.get("roster",[]) if p.get("starter") is True]
    if len(starters)!=11 or len(players)!=11:
        return None
    slots={}
    for p in starters:
        place=str(p.get("formationPlace") or "")
        athlete=str((p.get("athlete") or {}).get("id") or "")
        if not place.isdigit() or not athlete.isdigit() or int(place) in slots:
            return None
        slots[int(place)]=1500000000+int(athlete)
    if set(slots)!=set(range(1,12)) or set(slots.values())!={p["player_id"] for p in players}:
        return None
    return {"formation":"-".join(key),"position_order":[slots[s] for row in rows for s in row],
            "position_source":"ESPN formation + Opta formationPlace",
            "position_unavailable":False}

def explicit_pitch(team):
    source=team.get("position_source")
    formation=team.get("formation")
    order=team.get("position_order")
    players=team["players"]
    if not source or not isinstance(formation,str) or not re.fullmatch(r"[1-5](?:-[1-5]){1,5}",formation):
        return None
    by_id={p["player_id"]:p for p in players}
    if sum(map(int,formation.split("-")))!=10 or len(players)!=11 or len(by_id)!=11 or not isinstance(order,list) or len(order)!=11 or set(order)!=set(by_id):
        return None
    return formation,[by_id[pid] for pid in order]
