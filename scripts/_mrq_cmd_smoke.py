import unreal
out = r"C:/Users/Shadow/Desktop/Unreal-Agent/cinematic-v2/reports/cinematic/headless_mrq/_cmd_smoke.txt"
try:
    ver = unreal.SystemLibrary.get_engine_version()
    with open(out, "w") as f:
        f.write("SMOKE_OK " + str(ver))
    unreal.log("MRQ_SMOKE_WROTE")
except Exception as exc:
    with open(out, "w") as f:
        f.write("SMOKE_ERR " + repr(exc))
    unreal.log_error("MRQ_SMOKE_ERR " + repr(exc))