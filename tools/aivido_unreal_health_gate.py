#!/usr/bin/env python3
import argparse, json, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def remember(event):
    p=ROOT/"runtime"/"unreal_guardrail_memory.json"
    try: d=json.loads(p.read_text()) if p.exists() else {}
    except Exception: d={}
    d.setdefault("rules",[])
    d.setdefault("events",[])
    for r in [
      {"id":"live_evidence_required","description":"Never graduate Unreal work without live bridge/map/actor evidence."},
      {"id":"zero_actor_hard_fail","description":"Zero-actor scene is a hard failure."},
      {"id":"exit_zero_not_success","description":"Process/build exit 0 is not proof of Unreal success."}
    ]:
        if not any(x.get("id")==r["id"] for x in d["rules"]): d["rules"].append(r)
    d["events"].append(event)
    d["events"]=d["events"][-200:]
    p.write_text(json.dumps(d,indent=2))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--min-actors",type=int,default=1)
    ap.add_argument("--expected-map",default="")
    ap.add_argument("--json-out",default="")
    a=ap.parse_args()
    r={"ok":False,"bridge":False,"map":None,"actor_count":None,"reasons":[],"time":time.time()}
    try:
        import app.api as api
        api.BRIDGE.ping()
        r["bridge"]=True
        shot=str(Path.home()/"Desktop"/"AIVIDO_MAC_LOGS"/"aivido_live_gate.png")
        code="import unreal\nworld=unreal.EditorLevelLibrary.get_editor_world()\nactors=unreal.EditorLevelLibrary.get_all_level_actors()\nworld_name=world.get_name() if world else \'\'\nactor_count=len(actors)\n__bridge_result__={\'world\':world_name,\'actor_count\':actor_count}\n"
        live=api.BRIDGE.execute_python(code)
        p=live if isinstance(live,dict) else {"raw":live}
        for k in ("result","data","bridge_result"):
            if isinstance(p.get(k),dict): p=p[k]; break
        r["map"]=p.get("world") or p.get("map")
        try: r["actor_count"]=int(p.get("actor_count"))
        except Exception: r["actor_count"]=None
        if not r["map"]: r["reasons"].append("LIVE_MAP_MISSING")
        if r["actor_count"] is None: r["reasons"].append("ACTOR_COUNT_MISSING")
        elif r["actor_count"] < a.min_actors: r["reasons"].append(f"ACTOR_COUNT_TOO_LOW:{r['actor_count']}<{a.min_actors}")
        if a.expected_map:
            e=a.expected_map.split("/")[-1]
            if e not in str(r["map"] or ""): r["reasons"].append(f"WRONG_MAP:{r['map']}!=~{e}")
        r["ok"]=not r["reasons"]
    except Exception as e:
        r["reasons"].append("LIVE_VERIFY_ERROR:"+repr(e))
    remember({"time":r["time"],"kind":"pass" if r["ok"] else "block","map":r["map"],"actor_count":r["actor_count"],"reasons":r["reasons"]})
    text=json.dumps(r,indent=2)
    print(text)
    if a.json_out: Path(a.json_out).write_text(text)
    return 0 if r["ok"] else 42

if __name__=="__main__": raise SystemExit(main())
