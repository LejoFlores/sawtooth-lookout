"""Turn latest.json alerts into GitHub issues: open one per basin and event when it starts, comment while it holds,
close it when it clears. Needs GITHUB_TOKEN and GITHUB_REPOSITORY (both set in GitHub Actions).

Run (from the repository root): python3 -m ews.notify [--dry-run]
"""
import argparse
import json
import os

import pandas as pd
import requests

from . import common as C
from .page import EV_LABEL

LABEL = "early-warning"


def title(basin, event):
    return f"Week-2 alarm: {EV_LABEL[event]}, {C.CFG['basins'][basin]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    o = json.load(open(C.PRODUCTS / "latest.json"))
    want = {title(a["basin"], a["event"]): a for a in o["alerts"]}
    repo, tok = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if args.dry_run or not (repo and tok):
        for t, a in want.items():
            print("would alert:", t, f"{a['odds']:.0%}")
        return
    api = f"https://api.github.com/repos/{repo}"
    s = requests.Session()
    s.headers.update(Authorization=f"Bearer {tok}", Accept="application/vnd.github+json")
    s.post(f"{api}/labels", json=dict(name=LABEL, color="b91c1c", description="Week-2 tail-risk alarm"))
    open_ = {i["title"]: i for i in s.get(f"{api}/issues", params=dict(labels=LABEL, state="open", per_page=100)).json()
             if "pull_request" not in i}
    page = os.environ.get("EWS_PAGE_URL", "")
    hist = pd.read_csv(C.PRODUCTS / "history.csv")
    hist = hist[hist.init < o["init"]].sort_values("init")
    for t, a in want.items():
        b = o["basins"][a["basin"]]["week2"][a["event"]]
        prev = hist[(hist.basin == a["basin"]) & (hist.event == a["event"])].tail(1)
        was = ""
        if len(prev):
            d = a["odds"] - float(prev.odds.iloc[0])
            how = "up" if d >= 0.03 else ("down" if d <= -0.03 else "about level")
            was = f" ({how} from {float(prev.odds.iloc[0]):.0%} in the {prev.init.iloc[0]} run)"
        body = (f"Start {o['init']}: week 2 ({o['week2_dates'][0]} to {o['week2_dates'][1]}) odds **{a['odds']:.0%}**{was} "
                f"against a usual {b['base_rate']:.0%}. GEFS member share {b['share_gefs']:.0%}"
                + ("" if b["share_ecmwf"] is None else f", ECMWF {b['share_ecmwf']:.0%}") + "."
                + (f"\n\n{page}" if page else "")
                + "\n\n_Experimental research product (Sawtooth Lookout, Boise State University). Not an official "
                "forecast; see the National Weather Service for official forecasts and warnings._")
        if t in open_:
            s.post(f"{api}/issues/{open_[t]['number']}/comments", json=dict(body="Still on. " + body)).raise_for_status()
        else:
            s.post(f"{api}/issues", json=dict(title=t, body=body, labels=[LABEL])).raise_for_status()
        print("alert:", t)
    for t, i in open_.items():
        if t not in want:
            s.post(f"{api}/issues/{i['number']}/comments",
                   json=dict(body=f"Cleared with start {o['init']}.")).raise_for_status()
            s.patch(f"{api}/issues/{i['number']}", json=dict(state="closed")).raise_for_status()
            print("cleared:", t)


if __name__ == "__main__":
    main()
