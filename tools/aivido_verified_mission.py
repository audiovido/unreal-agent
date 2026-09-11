#!/usr/bin/env python3
import argparse,json,subprocess,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
GATE=ROOT/"tools"/"aivido_unreal_health_gate.py"
BASE="http://127.0.0.1:8765"

def req(method,path,body=None):
    data=None if body is None else json.dumps(body).encode()
    q=urllib.request.Request(BASE+path,data=data,method=method,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(q,timeout=10) as r: return json.loads(r.read().decode())

def gate(min_actors,expected,out):
    c=[sys.executable,str(GATE),"--min-actors",str(min_actors),"--json-out",str(out)]
    if expected: c += ["--expected-map",expected]
    return subprocess.run(c).returncode==0

def wait(job,timeout):
    end=time.time()+timeout
    while time.time()<end:
        s=req("GET",f"/api/command/{job}")
        st=str(s.get("state","")).lower()
        if st in {"pass","complete","completed","failed","cancelled","canceled"}: return s
        time.sleep(2)
    raise TimeoutError(job)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("message")
    ap.add_argument("--min-actors",type=int,default=1)
    ap.add_argument("--expected-map",default="")
    ap.add_argument("--attempts",type=int,default=3)
    ap.add_argument("--timeout",type=int,default=900)
    a=ap.parse_args()
    ev=Path.home()/"Desktop"/"AIVIDO_MAC_LOGS"; ev.mkdir(parents=True,exist_ok=True)
    if not gate(1,"",ev/"verified_precheck.json"):
        print("VERDICT: BLOCKED\nREASON: LIVE_UNREAL_PRECHECK_FAILED"); return 20
    sub=req("POST","/api/command",{"message":a.message,"request_id":f"verified-{int(time.time())}"})
    job=sub.get("job_id")
    if not job: raise RuntimeError("job_id missing")
    for i in range(1,a.attempts+1):
        st=wait(job,a.timeout); state=str(st.get("state","")).lower()
        if state in {"pass","complete","completed"} and gate(a.min_actors,a.expected_map,ev/f"verified_gate_{i}.json"):
            print("VERDICT: GRADUATED"); print("LIVE_UNREAL_EVIDENCE: PASS"); print("ATTEMPT:",i); return 0
        if i>=a.attempts:
            print("VERDICT: BLOCKED"); print("REASON: FALSE_PASS_OR_COMMAND_FAILURE"); return 40
        rr=req("POST",f"/api/command/{job}/retry",{})
        job=rr.get("job_id",job)
    return 50

if __name__=="__main__": raise SystemExit(main())
