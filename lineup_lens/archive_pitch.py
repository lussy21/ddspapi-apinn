"""Deterministic pitch layout from REAL archived starting-position codes.

No guessed formations, no internet access, no lineup updates.
11footy positions classify into goalkeeper, defence, midfield, attacking
midfield and forwards. The output formation is DERIVED from position codes,
and is not claimed as the official manager's published tactical shape.
"""
from collections import Counter

ROLE = {
    "G":"G",
    "DL":"D","LB":"D","CD-L":"D","CD":"D","CD-R":"D","RB":"D","SW":"D",
    "LM":"M","CM-L":"M","CM":"M","DM":"M","CM-R":"M","RM":"M",
    "AM-L":"A","AM":"A","AM-R":"A",
    "LF":"F","CF-L":"F","F":"F","CF-R":"F","RF":"F","RCF":"F",
}
X = {
    "DL":0,"LB":0, "CD-L":1, "CD":2, "SW":2, "CD-R":3,"RB":4,
    "LM":0,"CM-L":1,"CM":2,"DM":2,"CM-R":3,"RM":4,
    "AM-L":0,"AM":2,"AM-R":4,
    "LF":0,"CF-L":1,"F":2,"CF-R":3,"RCF":3,"RF":4,
    "G":2
}
ORDER = {"G":0,"D":1,"M":2,"A":3,"F":4}


def pitch_from_codes(records):
    """Return (formation, ordered records) if exactly 11 well-defined starters."""
    if not isinstance(records,(list,tuple)) or len(records)!=11:
        raise ValueError("Archive needs exactly eleven starting players")
    keys=[r.get("player_id") for r in records]
    if len(set(keys))!=11 or any(x is None for x in keys):
        raise ValueError("Archive has duplicate or missing players")
    codes=[r.get("position_code") for r in records]
    if any(code not in ROLE for code in codes):
        raise ValueError("Archive has an unrecognised pitch position")
    counts=Counter(ROLE[code] for code in codes)
    if counts["G"]!=1 or sum(counts.values())!=11:
        raise ValueError("Archive must have one goalkeeper and ten outfield starters")
    lineup=sorted(records,key=lambda p:(ORDER[ROLE[p["position_code"]]],
                                     X[p["position_code"]],str(p["player_id"])))
    formation="-".join(str(counts[x]) for x in ("D","M","A","F") if counts[x])
    return formation,lineup
