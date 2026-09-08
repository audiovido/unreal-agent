import sys, pathlib, json, socket, subprocess, os, importlib
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
sys.dont_write_bytecode = True
os.environ['UA_DISABLE_WORKBOARD_AUTOPILOT'] = '1'
def denied(*args, **kwargs):
    raise RuntimeError('Network/process activity disabled for offline package smoke')
socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied
def audit(event, args):
    if event in ('subprocess.Popen', 'os.system', 'socket.connect', 'socket.bind'):
        denied()
sys.addaudithook(audit)
results = []
for name in ['fastapi','uvicorn','PIL','numpy','pydantic','requests','rich',
             'qa.checks','core.mission','core.orchestrator','app.served',
             'scripts.aivido_runtime','scripts.acceptance.second_system_checks']:
    try:
        m = importlib.import_module(name)
        if name.split('.')[0] in ('qa','core','app','scripts'):
            assert pathlib.Path(m.__file__).resolve().is_relative_to(root)
        results.append({'module':name,'status':'PASS'})
    except Exception as exc:
        results.append({'module':name,'status':'FAIL','error':type(exc).__name__+': '+str(exc)})
print(json.dumps({'checks':results, 'status':'PASS' if all(x['status']=='PASS' for x in results) else 'FAIL'}))
sys.exit(0 if all(x['status']=='PASS' for x in results) else 1)
