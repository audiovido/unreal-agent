#!/usr/bin/env python3
import argparse,json,subprocess,sys,time,urllib.request,urllib.error,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
GATE=ROOT/"tools"/"aivido_unreal_health_gate.py"
BASE="http://127.0.0.1:8765"

def ensure_backend():
    try:
        urllib.request.urlopen(BASE+"/api/status", timeout=2).read()
        return
    except Exception:
        pass

    backend=str(ROOT)
    log=str(Path.home()/"Desktop"/"AIVIDO_MAC_LOGS"/"backend_autorecover.log")

    subprocess.Popen(
        [
            "/opt/local/bin/python3.12","-m","uvicorn",
            "app.api:app","--host","127.0.0.1","--port","8765"
        ],
        cwd=backend,
        env={
            **os.environ,
            "PYTHONPATH": backend+"/.venv-mac/lib/python3.12/site-packages:"+backend
        },
        stdout=open(log,"a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    for _ in range(30):
        try:
            urllib.request.urlopen(BASE+"/api/status", timeout=2).read()
            return
        except Exception:
            time.sleep(1)

    raise RuntimeError("BACKEND_AUTO_RECOVERY_FAILED")

def req(method,path,body=None):
    last=None

    for attempt in range(3):
        try:
            ensure_backend()
            data=None if body is None else json.dumps(body).encode()
            q=urllib.request.Request(
                BASE+path,
                data=data,
                method=method,
                headers={"Content-Type":"application/json"}
            )
            with urllib.request.urlopen(q,timeout=10) as r:
                return json.loads(r.read().decode())

        except (urllib.error.URLError,ConnectionError,OSError) as e:
            last=e
            time.sleep(2)

    raise RuntimeError(f"BACKEND_UNAVAILABLE_AFTER_RECOVERY: {last}")

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
def package_evidence(job, ev: Path, expected_map: str, executor_ok: bool) -> dict:
    """Assemble fresh-frame + SceneDiff evidence and run the honest packager.

    Returns {"ok": bool, "verdict": str, "dir": str, "detail": str}.
    The capture provenance (capture_metadata.json) is written by the backend
    capture adapter next to the frame; the packager rejects any frame that is
    not provably fresh, and an empty SceneDiff is a FAIL.
    """
    import shutil
    sys.path.insert(0, str(ROOT))
    from scripts.aivido_evidence import main as evidence_main

    result = (job.get("result") or {}).get("pipeline_v2") or {}
    capture = result.get("capture") or {}
    cap_path = capture.get("path")
    if not cap_path or not os.path.isfile(cap_path):
        return {"ok": False, "verdict": "FAIL", "dir": "",
                "detail": "no_capture_path_in_job_result"}
    stamp = time.strftime("%Y%m%d-%H%M%S")
    ev_dir = ev / f"evidence_{stamp}"
    ev_dir.mkdir(parents=True, exist_ok=True)
    final = ev_dir / "FINAL.png"
    shutil.copyfile(cap_path, final)
    meta_src = os.path.join(os.path.dirname(cap_path), "capture_metadata.json")
    if os.path.isfile(meta_src):
        # Rewrite provenance for the packaged frame name: the backend wrote
        # metadata for the original capture filename (e.g. viewport_latest.png
        # or a _trimmed variant), but the evidence dir presents it as
        # FINAL.png. The packager rejects metadata describing a different
        # frame, so the frame/path fields must match the packaged copy while
        # sha256/size/timestamp/map stay byte-pinned to the original capture.
        try:
            meta = json.loads(Path(meta_src).read_text())
            meta["frame"] = "FINAL.png"
            meta["path"] = str(final)
            (ev_dir / "capture_metadata.json").write_text(json.dumps(meta, indent=2))
        except Exception:
            shutil.copyfile(meta_src, ev_dir / "capture_metadata.json")
    # SceneDiff from before/after snapshots (empty diff must FAIL).
    before = result.get("snapshot_before")
    after = result.get("snapshot_after")
    if before is not None and after is not None:
        (ev_dir / "scenediff.json").write_text(json.dumps(
            {"before": before, "after": after}, default=str))
    argv = ["aivido_evidence", str(ev_dir), "--expected-map", expected_map,
            "--max-age", "3600"]
    if executor_ok:
        argv.append("--executor-ok")
    old = sys.argv
    sys.argv = argv
    try:
        rc = evidence_main()
    finally:
        sys.argv = old
    verdict = "PASS"
    try:
        verdict = json.loads((ev_dir / "verdict.json").read_text()).get("verdict", "FAIL")
    except Exception:
        pass
    return {"ok": rc == 0, "verdict": verdict, "dir": str(ev_dir), "detail": ""}


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
            pkg = package_evidence(st, ev, a.expected_map or "/Game/AIVIDO_Showcase",
                                   executor_ok=True)
            print("EVIDENCE_PACKAGER:", json.dumps(pkg, default=str))
            if not pkg["ok"]:
                print("VERDICT: BLOCKED"); print("REASON: EVIDENCE_PACKAGER_FAILED:"+pkg["verdict"])
                return 30
            print("VERDICT: GRADUATED"); print("LIVE_UNREAL_EVIDENCE: PASS"); print("ATTEMPT:",i); return 0
        if i>=a.attempts:
            print("VERDICT: BLOCKED"); print("REASON: FALSE_PASS_OR_COMMAND_FAILURE"); return 40
        rr=req("POST",f"/api/command/{job}/retry",{})
        job=rr.get("job_id",job)
    return 50

if __name__=="__main__": raise SystemExit(main())
