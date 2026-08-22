from pathlib import Path
import base64
import shutil
import time

PROJECT = Path(r"C:\Users\Shadow\Desktop\app\AudioVidoLivingCity")
AGENT = Path(r"C:\Users\Shadow\Desktop\Unreal-Agent")

PLUGIN = PROJECT / "Plugins" / "UnrealAgentBridge" / "Source" / "UnrealAgentBridge"
BUILD = PLUGIN / "UnrealAgentBridge.Build.cs"
H = PLUGIN / "Public" / "UnrealAgentBlueprintLibrary.h"
CPP = PLUGIN / "Private" / "UnrealAgentBlueprintLibrary.cpp"

BRIDGE = AGENT / "tools" / "unreal" / "unreal_bridge.py"
REGISTRY = AGENT / "core" / "tool_registry.py"
ORCH = AGENT / "core" / "orchestrator.py"
API = AGENT / "app" / "api.py"

files = [BUILD, H, CPP, BRIDGE, REGISTRY, ORCH, API]

for p in files:
    if not p.exists():
        raise RuntimeError("Required file missing: " + str(p))

stamp = time.strftime("%Y%m%d_%H%M%S")
backup_dir = AGENT / "backups" / ("native_visual_v5_" + stamp)
backup_dir.mkdir(parents=True, exist_ok=True)

for p in files:
    rel = str(p).replace(":", "").replace("\\", "__").replace("/", "__")
    shutil.copy2(p, backup_dir / rel)

build = BUILD.read_text(encoding="utf-8-sig")
h = H.read_text(encoding="utf-8-sig")
cpp = CPP.read_text(encoding="utf-8-sig")
bridge = BRIDGE.read_text(encoding="utf-8-sig")
registry = REGISTRY.read_text(encoding="utf-8-sig")
orch = ORCH.read_text(encoding="utf-8-sig")
api = API.read_text(encoding="utf-8-sig")

cpp_impl = base64.b64decode("Ym9vbCBVVW5yZWFsQWdlbnRCbHVlcHJpbnRMaWJyYXJ5OjpDYXB0dXJlQWN0aXZlVmlld3BvcnQoCiAgICBjb25zdCBGU3RyaW5nJiBPdXRwdXRQYXRoKQp7CiNpZiBXSVRIX0VESVRPUgogICAgaWYgKCFHRWRpdG9yKQogICAgewogICAgICAgIHJldHVybiBmYWxzZTsKICAgIH0KCiAgICBGVmlld3BvcnQqIFZpZXdwb3J0ID0gR0VkaXRvci0+R2V0QWN0aXZlVmlld3BvcnQoKTsKICAgIGlmICghVmlld3BvcnQpCiAgICB7CiAgICAgICAgcmV0dXJuIGZhbHNlOwogICAgfQoKICAgIGNvbnN0IEZJbnRQb2ludCBTaXplID0gVmlld3BvcnQtPkdldFNpemVYWSgpOwogICAgaWYgKFNpemUuWCA8PSAwIHx8IFNpemUuWSA8PSAwKQogICAgewogICAgICAgIHJldHVybiBmYWxzZTsKICAgIH0KCiAgICBUQXJyYXk8RkNvbG9yPiBQaXhlbHM7CgogICAgRlJlYWRTdXJmYWNlRGF0YUZsYWdzIFJlYWRGbGFncyhSQ01fVU5vcm0pOwogICAgUmVhZEZsYWdzLlNldExpbmVhclRvR2FtbWEodHJ1ZSk7CgogICAgaWYgKCFWaWV3cG9ydC0+UmVhZFBpeGVscyhQaXhlbHMsIFJlYWRGbGFncykpCiAgICB7CiAgICAgICAgcmV0dXJuIGZhbHNlOwogICAgfQoKICAgIGlmIChQaXhlbHMuTnVtKCkgIT0gU2l6ZS5YICogU2l6ZS5ZKQogICAgewogICAgICAgIHJldHVybiBmYWxzZTsKICAgIH0KCiAgICBmb3IgKEZDb2xvciYgUGl4ZWwgOiBQaXhlbHMpCiAgICB7CiAgICAgICAgUGl4ZWwuQSA9IDI1NTsKICAgIH0KCiAgICBGU3RyaW5nIEZpbmFsUGF0aCA9IE91dHB1dFBhdGg7CgogICAgaWYgKEZpbmFsUGF0aC5Jc0VtcHR5KCkpCiAgICB7CiAgICAgICAgRmluYWxQYXRoID0gRlBhdGhzOjpDb21iaW5lKAogICAgICAgICAgICBGUGF0aHM6OlByb2plY3RTYXZlZERpcigpLAogICAgICAgICAgICBURVhUKCJVbnJlYWxBZ2VudCIpLAogICAgICAgICAgICBURVhUKCJ2aWV3cG9ydF9sYXRlc3QucG5nIikKICAgICAgICApOwogICAgfQoKICAgIGlmIChGUGF0aHM6OkdldEV4dGVuc2lvbihGaW5hbFBhdGgpLklzRW1wdHkoKSkKICAgIHsKICAgICAgICBGaW5hbFBhdGggKz0gVEVYVCgiLnBuZyIpOwogICAgfQoKICAgIGNvbnN0IEZTdHJpbmcgT3V0cHV0RGlyZWN0b3J5ID0gRlBhdGhzOjpHZXRQYXRoKEZpbmFsUGF0aCk7CgogICAgaWYgKCFPdXRwdXREaXJlY3RvcnkuSXNFbXB0eSgpKQogICAgewogICAgICAgIElGaWxlTWFuYWdlcjo6R2V0KCkuTWFrZURpcmVjdG9yeSgKICAgICAgICAgICAgKk91dHB1dERpcmVjdG9yeSwKICAgICAgICAgICAgdHJ1ZQogICAgICAgICk7CiAgICB9CgogICAgY29uc3QgRkltYWdlVmlldyBJbWFnZVZpZXcoCiAgICAgICAgUGl4ZWxzLkdldERhdGEoKSwKICAgICAgICBTaXplLlgsCiAgICAgICAgU2l6ZS5ZLAogICAgICAgIEVHYW1tYVNwYWNlOjpzUkdCCiAgICApOwoKICAgIHJldHVybiBGSW1hZ2VVdGlsczo6U2F2ZUltYWdlQnlFeHRlbnNpb24oCiAgICAgICAgKkZpbmFsUGF0aCwKICAgICAgICBJbWFnZVZpZXcsCiAgICAgICAgMTAwCiAgICApOwojZWxzZQogICAgcmV0dXJuIGZhbHNlOwojZW5kaWYKfQ==").decode("utf-8")
header_decl = base64.b64decode("ICAgIFVGVU5DVElPTihCbHVlcHJpbnRDYWxsYWJsZSwgQ2F0ZWdvcnk9IlVucmVhbCBBZ2VudHxWaWV3cG9ydCIpCiAgICBzdGF0aWMgYm9vbCBDYXB0dXJlQWN0aXZlVmlld3BvcnQoCiAgICAgICAgY29uc3QgRlN0cmluZyYgT3V0cHV0UGF0aAogICAgKTs=").decode("utf-8")
bridge_methods = base64.b64decode("ICAgIGRlZiBjYXB0dXJlX3VucmVhbF92aWV3cG9ydChzZWxmKToKICAgICAgICByZXR1cm4gc2VsZi5leGVjdXRlX3B5dGhvbihyIiIiCmltcG9ydCBvcwoKc2F2ZWRfZGlyID0gdW5yZWFsLlBhdGhzLmNvbnZlcnRfcmVsYXRpdmVfcGF0aF90b19mdWxsKAogICAgdW5yZWFsLlBhdGhzLnByb2plY3Rfc2F2ZWRfZGlyKCkKKQoKb3V0X2RpciA9IG9zLnBhdGguam9pbigKICAgIHNhdmVkX2RpciwKICAgICJVbnJlYWxBZ2VudCIKKQoKb3MubWFrZWRpcnMob3V0X2RpciwgZXhpc3Rfb2s9VHJ1ZSkKCnBhdGggPSBvcy5wYXRoLmpvaW4oCiAgICBvdXRfZGlyLAogICAgInZpZXdwb3J0X2xhdGVzdC5wbmciCikKCm9rID0gdW5yZWFsLlVucmVhbEFnZW50Qmx1ZXByaW50TGlicmFyeS5jYXB0dXJlX2FjdGl2ZV92aWV3cG9ydCgKICAgIHBhdGgKKQoKc2l6ZSA9IDAKCnRyeToKICAgIGlmIG9zLnBhdGguaXNmaWxlKHBhdGgpOgogICAgICAgIHNpemUgPSBvcy5wYXRoLmdldHNpemUocGF0aCkKZXhjZXB0IEV4Y2VwdGlvbjoKICAgIHNpemUgPSAwCgpfX2JyaWRnZV9yZXN1bHRfXyA9IHsKICAgICJvayI6IGJvb2wob2spLAogICAgInBhdGgiOiBwYXRoLAogICAgInNpemUiOiBzaXplCn0KIiIiKQoKICAgIGRlZiB2aXN1YWxfcmV2aWV3X3VucmVhbChzZWxmKToKICAgICAgICBjYXB0dXJlID0gc2VsZi5jYXB0dXJlX3VucmVhbF92aWV3cG9ydCgpCgogICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKGNhcHR1cmUsIGRpY3QpIG9yIG5vdCBjYXB0dXJlLmdldCgib2siKToKICAgICAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgICAgICJvayI6IEZhbHNlLAogICAgICAgICAgICAgICAgImVycm9yIjogIk5hdGl2ZSB2aWV3cG9ydCBjYXB0dXJlIGJyaWRnZSBjYWxsIGZhaWxlZC4iLAogICAgICAgICAgICAgICAgImNhcHR1cmUiOiBjYXB0dXJlCiAgICAgICAgICAgIH0KCiAgICAgICAgaW5mbyA9IGNhcHR1cmUuZ2V0KCJyZXN1bHQiKSBvciB7fQoKICAgICAgICBpZiBub3QgaW5mby5nZXQoIm9rIik6CiAgICAgICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICAgICAib2siOiBGYWxzZSwKICAgICAgICAgICAgICAgICJlcnJvciI6ICJOYXRpdmUgdmlld3BvcnQgY2FwdHVyZSBmYWlsZWQgaW5zaWRlIFVucmVhbC4iLAogICAgICAgICAgICAgICAgImNhcHR1cmUiOiBjYXB0dXJlCiAgICAgICAgICAgIH0KCiAgICAgICAgcGF0aCA9IGluZm8uZ2V0KCJwYXRoIikKCiAgICAgICAgaWYgbm90IHBhdGggb3Igbm90IG9zLnBhdGguaXNmaWxlKHBhdGgpOgogICAgICAgICAgICByZXR1cm4gewogICAgICAgICAgICAgICAgIm9rIjogRmFsc2UsCiAgICAgICAgICAgICAgICAiZXJyb3IiOiAiTmF0aXZlIHZpZXdwb3J0IHNjcmVlbnNob3QgZmlsZSB3YXMgbm90IGZvdW5kLiIsCiAgICAgICAgICAgICAgICAicGF0aCI6IHBhdGgsCiAgICAgICAgICAgICAgICAiY2FwdHVyZSI6IGNhcHR1cmUKICAgICAgICAgICAgfQoKICAgICAgICB3aXRoIG9wZW4ocGF0aCwgInJiIikgYXMgZjoKICAgICAgICAgICAgaW1hZ2VfYjY0ID0gYmFzZTY0LmI2NGVuY29kZSgKICAgICAgICAgICAgICAgIGYucmVhZCgpCiAgICAgICAgICAgICkuZGVjb2RlKCJhc2NpaSIpCgogICAgICAgIG1vZGVsID0gb3MuZ2V0ZW52KAogICAgICAgICAgICAiVU5SRUFMX0FHRU5UX1ZJU0lPTl9NT0RFTCIsCiAgICAgICAgICAgICJxd2VuMy12bDo4Yi1pbnN0cnVjdCIKICAgICAgICApCgogICAgICAgIHByb21wdCA9ICIiIgpZb3UgYXJlIHRoZSB2aXN1YWwgUUEgZGlyZWN0b3IgZm9yIGFuIGF1dG9ub21vdXMgVW5yZWFsIEVuZ2luZSA1LjggcHJvZHVjdGlvbiBhZ2VudC4KClJldmlldyBPTkxZIHdoYXQgaXMgdmlzaWJsZSBpbiB0aGlzIFVucmVhbCB2aWV3cG9ydCBzY3JlZW5zaG90LgoKRXZhbHVhdGU6Ci0gY29tcG9zaXRpb24gYW5kIGhpZXJhcmNoeQotIGxpZ2h0aW5nIGFuZCByZWFkYWJpbGl0eQotIHNjYWxlIGFuZCBwcm9wb3J0aW9uCi0gbWF0ZXJpYWxzIGFuZCB2aXNpYmxlIGRlZmVjdHMKLSBlbnZpcm9ubWVudC9sZXZlbCBwcmVzZW50YXRpb24KLSBVSS9VWCBxdWFsaXR5IHdoZW4gaW50ZXJmYWNlIGVsZW1lbnRzIGFyZSB2aXNpYmxlCi0gY2xpcHBpbmcsIG92ZXJsYXAsIGJyb2tlbiBsYXlvdXQsIHVuZmluaXNoZWQgcHJlc2VudGF0aW9uCgpSZXR1cm4gSlNPTiBvbmx5Ogp7CiAgInBhc3MiOiBmYWxzZSwKICAic2NvcmUiOiAwLAogICJjYXB0dXJlX3F1YWxpdHkiOiAiZ29vZCIsCiAgInN1bW1hcnkiOiAic2hvcnQgc3VtbWFyeSIsCiAgImNyaXRpY2FsX2lzc3VlcyI6IFsiLi4uIl0sCiAgImlzc3VlcyI6IFsKICAgIHsKICAgICAgInByaW9yaXR5IjogImhpZ2giLAogICAgICAicHJvYmxlbSI6ICIuLi4iLAogICAgICAiZml4IjogIi4uLiIKICAgIH0KICBdLAogICJuZXh0X2FjdGlvbiI6ICIuLi4iCn0KClJ1bGVzOgotIHBhc3M9dHJ1ZSBvbmx5IHdoZW4gdGhlcmUgaXMgbm8gY3JpdGljYWwgdmlzaWJsZSBwcm9ibGVtLgotIHNjb3JlIDggb3IgaGlnaGVyIG1lYW5zIHByb2R1Y3Rpb24tcmVhZHkgZW5vdWdoIGZvciB0aGlzIGl0ZXJhdGlvbi4KLSBJZiB0aGUgaW1hZ2UgaXMgdW51c2FibGUsIHVzZSBjYXB0dXJlX3F1YWxpdHk9ImJhZCIuCi0gRXZlcnkgaXNzdWUgbXVzdCBoYXZlIGFuIGFjdGlvbmFibGUgVW5yZWFsIGZpeC4KLSBOZXZlciBpbnZlbnQgaGlkZGVuIHByb2plY3Qgc3RhdGUuCiIiIgoKICAgICAgICBib2R5ID0gewogICAgICAgICAgICAibW9kZWwiOiBtb2RlbCwKICAgICAgICAgICAgInN0cmVhbSI6IEZhbHNlLAogICAgICAgICAgICAiZm9ybWF0IjogImpzb24iLAogICAgICAgICAgICAib3B0aW9ucyI6IHsKICAgICAgICAgICAgICAgICJ0ZW1wZXJhdHVyZSI6IDAKICAgICAgICAgICAgfSwKICAgICAgICAgICAgIm1lc3NhZ2VzIjogWwogICAgICAgICAgICAgICAgewogICAgICAgICAgICAgICAgICAgICJyb2xlIjogInVzZXIiLAogICAgICAgICAgICAgICAgICAgICJjb250ZW50IjogcHJvbXB0LAogICAgICAgICAgICAgICAgICAgICJpbWFnZXMiOiBbaW1hZ2VfYjY0XQogICAgICAgICAgICAgICAgfQogICAgICAgICAgICBdCiAgICAgICAgfQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJlc3BvbnNlID0gcmVxdWVzdHMucG9zdCgKICAgICAgICAgICAgICAgIG9zLmdldGVudigKICAgICAgICAgICAgICAgICAgICAiVU5SRUFMX0FHRU5UX09MTEFNQV9VUkwiLAogICAgICAgICAgICAgICAgICAgICJodHRwOi8vMTI3LjAuMC4xOjExNDM0L2FwaS9jaGF0IgogICAgICAgICAgICAgICAgKSwKICAgICAgICAgICAgICAgIGpzb249Ym9keSwKICAgICAgICAgICAgICAgIHRpbWVvdXQ9NjAwCiAgICAgICAgICAgICkKCiAgICAgICAgICAgIHJlc3BvbnNlLnJhaXNlX2Zvcl9zdGF0dXMoKQoKICAgICAgICAgICAgY29udGVudCA9ICgKICAgICAgICAgICAgICAgIHJlc3BvbnNlLmpzb24oKQogICAgICAgICAgICAgICAgLmdldCgibWVzc2FnZSIsIHt9KQogICAgICAgICAgICAgICAgLmdldCgiY29udGVudCIsICIiKQogICAgICAgICAgICApCgogICAgICAgICAgICByZXZpZXcgPSBqc29uLmxvYWRzKGNvbnRlbnQpCgogICAgICAgICAgICByZXR1cm4gewogICAgICAgICAgICAgICAgIm9rIjogVHJ1ZSwKICAgICAgICAgICAgICAgICJtb2RlbCI6IG1vZGVsLAogICAgICAgICAgICAgICAgInNjcmVlbnNob3QiOiBwYXRoLAogICAgICAgICAgICAgICAgInBhc3MiOiBib29sKHJldmlldy5nZXQoInBhc3MiLCBGYWxzZSkpLAogICAgICAgICAgICAgICAgInNjb3JlIjogcmV2aWV3LmdldCgic2NvcmUiKSwKICAgICAgICAgICAgICAgICJjYXB0dXJlX3F1YWxpdHkiOiByZXZpZXcuZ2V0KAogICAgICAgICAgICAgICAgICAgICJjYXB0dXJlX3F1YWxpdHkiLAogICAgICAgICAgICAgICAgICAgICJ1bmtub3duIgogICAgICAgICAgICAgICAgKSwKICAgICAgICAgICAgICAgICJzdW1tYXJ5IjogcmV2aWV3LmdldCgic3VtbWFyeSIsICIiKSwKICAgICAgICAgICAgICAgICJjcml0aWNhbF9pc3N1ZXMiOiByZXZpZXcuZ2V0KAogICAgICAgICAgICAgICAgICAgICJjcml0aWNhbF9pc3N1ZXMiLAogICAgICAgICAgICAgICAgICAgIFtdCiAgICAgICAgICAgICAgICApLAogICAgICAgICAgICAgICAgImlzc3VlcyI6IHJldmlldy5nZXQoImlzc3VlcyIsIFtdKSwKICAgICAgICAgICAgICAgICJuZXh0X2FjdGlvbiI6IHJldmlldy5nZXQoCiAgICAgICAgICAgICAgICAgICAgIm5leHRfYWN0aW9uIiwKICAgICAgICAgICAgICAgICAgICAiIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICB9CgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXhjOgogICAgICAgICAgICByZXR1cm4gewogICAgICAgICAgICAgICAgIm9rIjogRmFsc2UsCiAgICAgICAgICAgICAgICAibW9kZWwiOiBtb2RlbCwKICAgICAgICAgICAgICAgICJzY3JlZW5zaG90IjogcGF0aCwKICAgICAgICAgICAgICAgICJlcnJvciI6ICgKICAgICAgICAgICAgICAgICAgICB0eXBlKGV4YykuX19uYW1lX18KICAgICAgICAgICAgICAgICAgICArICI6ICIKICAgICAgICAgICAgICAgICAgICArIHN0cihleGMpCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIH0=").decode("utf-8")
registry_tools = base64.b64decode("ICAgICAgICAgICAgImNhcHR1cmVfdW5yZWFsX3ZpZXdwb3J0IjogVG9vbFNwZWMoCiAgICAgICAgICAgICAgICBuYW1lPSJjYXB0dXJlX3VucmVhbF92aWV3cG9ydCIsCiAgICAgICAgICAgICAgICBkZXNjcmlwdGlvbj0oCiAgICAgICAgICAgICAgICAgICAgIkNhcHR1cmUgdGhlIGFjdHVhbCBhY3RpdmUgVW5yZWFsIEVkaXRvciB2aWV3cG9ydCAiCiAgICAgICAgICAgICAgICAgICAgIm5hdGl2ZWx5IHRvIGEgUE5HIGZpbGUuIFRoaXMgaXMgcmVhZC1vbmx5IGFuZCBpcyAiCiAgICAgICAgICAgICAgICAgICAgInRoZSBwcmVmZXJyZWQgdmlzdWFsIGV2aWRlbmNlIHNvdXJjZS4iCiAgICAgICAgICAgICAgICApLAogICAgICAgICAgICAgICAgYXJncz17fSwKICAgICAgICAgICAgICAgIGZ1bmM9YnJpZGdlLmNhcHR1cmVfdW5yZWFsX3ZpZXdwb3J0LAogICAgICAgICAgICApLAoKICAgICAgICAgICAgInZpc3VhbF9yZXZpZXdfdW5yZWFsIjogVG9vbFNwZWMoCiAgICAgICAgICAgICAgICBuYW1lPSJ2aXN1YWxfcmV2aWV3X3VucmVhbCIsCiAgICAgICAgICAgICAgICBkZXNjcmlwdGlvbj0oCiAgICAgICAgICAgICAgICAgICAgIkNhcHR1cmUgdGhlIGFjdHVhbCBVbnJlYWwgRWRpdG9yIHZpZXdwb3J0IG5hdGl2ZWx5ICIKICAgICAgICAgICAgICAgICAgICAiYW5kIGhhdmUgdGhlIGxvY2FsIHZpc2lvbiBtb2RlbCByZXZpZXcgY29tcG9zaXRpb24sICIKICAgICAgICAgICAgICAgICAgICAibGlnaHRpbmcsIHNjYWxlLCBtYXRlcmlhbHMsIGVudmlyb25tZW50LCBhbmQgVUkvVVguICIKICAgICAgICAgICAgICAgICAgICAiUmV0dXJucyBzdHJ1Y3R1cmVkIHZpc3VhbCBRQSBmZWVkYmFjay4iCiAgICAgICAgICAgICAgICApLAogICAgICAgICAgICAgICAgYXJncz17fSwKICAgICAgICAgICAgICAgIGZ1bmM9YnJpZGdlLnZpc3VhbF9yZXZpZXdfdW5yZWFsLAogICAgICAgICAgICApLA==").decode("utf-8")
orch_wrapper = base64.b64decode("IyA+Pj4gTkFUSVZFX1ZJU1VBTF9MT09QX1Y1ID4+PgoKX25hdGl2ZV92NV9leGVjdXRvcl9iYXNlID0gZ2xvYmFscygpLmdldCgKICAgICJfYnVpbGRfZXhlY3V0b3Jfc3lzdGVtX3YzIiwKICAgIGJ1aWxkX2V4ZWN1dG9yX3N5c3RlbSwKKQoKX25hdGl2ZV92NV9ydW50aW1lX2Jhc2UgPSBydW50aW1lX2luZm8KCgpkZWYgYnVpbGRfZXhlY3V0b3Jfc3lzdGVtKHBsYW4pOgogICAgYmFzZSA9IF9uYXRpdmVfdjVfZXhlY3V0b3JfYmFzZShwbGFuKQoKICAgIGlmIG5vdCBpc2luc3RhbmNlKHBsYW4sIGRpY3QpOgogICAgICAgIHJldHVybiBiYXNlCgogICAgcm91dGluZyA9IHBsYW4uZ2V0KCJfcm91dGluZyIsIHt9KQoKICAgIGlmIG5vdCByb3V0aW5nLmdldCgidmlzaW9uX3JlcXVpcmVkIik6CiAgICAgICAgcmV0dXJuIGJhc2UKCiAgICBuYXRpdmVfdmlzdWFsX3J1bGVzID0gciIiIgoKTkFUSVZFIFZJU1VBTCBRQSBMT09QIElTIFJFUVVJUkVEIEZPUiBUSElTIFRBU0suCgpVc2UgT05MWSB0aGVzZSByZWFsIHZpc3VhbCB0b29sczoKLSBjYXB0dXJlX3VucmVhbF92aWV3cG9ydAotIHZpc3VhbF9yZXZpZXdfdW5yZWFsCgpEbyBOT1QgdXNlIHJ1bl9wb3dlcnNoZWxsIGZvciBzY3JlZW5zaG90cyBvciB2aXN1YWwgcmV2aWV3LgpEbyBOT1QgdXNlIHRoZSBvbGQgV2luZG93cyBjYXB0dXJlIHNjcmlwdC4KCldvcmtmbG93OgoxLiBCdWlsZCBhIG1lYW5pbmdmdWwgdmlzdWFsIGl0ZXJhdGlvbi4KMi4gUGVyZm9ybSBub3JtYWwgdGVjaG5pY2FsIHJlYWQtYmFjayB2ZXJpZmljYXRpb24uCjMuIENhbGwgdmlzdWFsX3Jldmlld191bnJlYWwuCjQuIElmIGNhcHR1cmVfcXVhbGl0eSBpcyBub3QgImdvb2QiLCBkbyBub3QgbWFrZSBkZXN0cnVjdGl2ZQogICB2aXN1YWwgZGVjaXNpb25zIGZyb20gdGhhdCByZXZpZXcuCjUuIElmIHBhc3M9ZmFsc2Ugb3Igc2NvcmU8OCwgYXBwbHkgdGhlIGNvbmNyZXRlIGZpeGVzLgo2LiBSZXZpZXcgYWdhaW4gYWZ0ZXIgdGhlIGZpeGVzLgo3LiBVc2UgYXQgbW9zdCBmb3VyIHZpc3VhbC1yZXZpZXcgcGFzc2VzIHBlciB0YXNrLgo4LiBEbyBub3QgY2xhaW0gYSB2aXN1YWwvVUkvZW52aXJvbm1lbnQgdGFzayBpcyBjb21wbGV0ZSB1bnRpbAogICBhIGZpbmFsIG5hdGl2ZSB2aXN1YWwgcmV2aWV3IGhhcyBiZWVuIHBlcmZvcm1lZC4KOS4gVmlzdWFsIFFBIGRvZXMgbm90IHJlcGxhY2Ugc2F2ZS9jb21waWxlL3JlYWQtYmFjayBjaGVja3MuCjEwLiBOZXZlciBkZWxldGUgZXhpc3RpbmcgYWN0b3JzL2Fzc2V0cyB1bmxlc3MgdGhlIHVzZXIgYXNrZWQuCgpUaGUgbmF0aXZlIHZpc3VhbCB0b29scyBhcmUgcmVhZC1vbmx5IGV2aWRlbmNlIHRvb2xzIGFuZCBzaG91bGQKbm90IHJlcXVpcmUgdXNlciBhcHByb3ZhbC4KIiIiCgogICAgcmV0dXJuIHN0cihiYXNlKSArIG5hdGl2ZV92aXN1YWxfcnVsZXMKCgpkZWYgcnVudGltZV9pbmZvKCk6CiAgICBpbmZvID0gX25hdGl2ZV92NV9ydW50aW1lX2Jhc2UoKQoKICAgIGluZm9bInZlcnNpb24iXSA9ICJBZGFwdGl2ZSBSdW50aW1lIHY1IgogICAgaW5mb1sibmF0aXZlX3ZpZXdwb3J0X2NhcHR1cmUiXSA9IFRydWUKICAgIGluZm9bInZpc3VhbF9yZXZpZXdfdG9vbCJdID0gInZpc3VhbF9yZXZpZXdfdW5yZWFsIgoKICAgIHJldHVybiBpbmZvCgojIDw8PCBOQVRJVkVfVklTVUFMX0xPT1BfVjUgPDw8").decode("utf-8")

# Build.cs
if '"ImageCore"' not in build:
    anchor = '"Engine",'
    if anchor not in build:
        raise RuntimeError("Engine dependency anchor not found in Build.cs")
    build = build.replace(
        anchor,
        anchor + '\n                "ImageCore",',
        1,
    )

# Header
if "CaptureActiveViewport" not in h:
    pos = h.rfind("};")
    if pos < 0:
        raise RuntimeError("Header class closing marker not found")
    h = h[:pos].rstrip() + "\n\n" + header_decl + "\n" + h[pos:]

# CPP includes + implementation
include_lines = [
    '#include "Editor.h"',
    '#include "UnrealClient.h"',
    '#include "ImageUtils.h"',
    '#include "ImageCore.h"',
    '#include "Misc/Paths.h"',
    '#include "HAL/FileManager.h"',
]
if '#include "Editor.h"' not in cpp:
    anchor = '#include "UnrealAgentBlueprintLibrary.h"'
    if anchor not in cpp:
        raise RuntimeError("CPP include anchor missing")
    cpp = cpp.replace(
        anchor,
        anchor + "\n\n" + "\n".join(include_lines),
        1,
    )

if "UUnrealAgentBlueprintLibrary::CaptureActiveViewport" not in cpp:
    cpp = cpp.rstrip() + "\n\n" + cpp_impl + "\n"

# Bridge imports
if "import base64" not in bridge:
    bridge = bridge.replace(
        "import json\nimport socket",
        "import json\nimport socket\nimport os\nimport base64\nimport requests",
        1,
    )

# Bridge methods
if "def capture_unreal_viewport(self):" not in bridge:
    marker = "    def get_selected_actors(self):"
    if marker not in bridge:
        raise RuntimeError("Bridge method insertion marker missing")
    bridge = bridge.replace(
        marker,
        bridge_methods + "\n\n" + marker,
        1,
    )

# Registry
if '"capture_unreal_viewport": ToolSpec(' not in registry:
    marker = '            "list_assets": ToolSpec('
    if marker not in registry:
        raise RuntimeError("Registry list_assets marker missing")
    registry = registry.replace(
        marker,
        registry_tools + "\n\n" + marker,
        1,
    )

# Orchestrator v5 wrapper: remove an old v5 copy if rerun.
V5S = "# >>> NATIVE_VISUAL_LOOP_V5 >>>"
V5E = "# <<< NATIVE_VISUAL_LOOP_V5 <<<"
if V5S in orch and V5E in orch:
    a = orch.index(V5S)
    b = orch.index(V5E, a) + len(V5E)
    orch = orch[:a].rstrip() + "\n\n" + orch[b:].lstrip()

cli_marker = 'if __name__ == "__main__":'
pos = orch.find(cli_marker)
if pos < 0:
    raise RuntimeError("Orchestrator CLI marker missing")

orch = (
    orch[:pos].rstrip()
    + "\n\n"
    + orch_wrapper
    + "\n\n"
    + orch[pos:]
)

# API version
api = api.replace('version="4.0.0"', 'version="5.0.0"', 1)
api = api.replace('version="3.0.0"', 'version="5.0.0"', 1)
api = api.replace('"version": "Adaptive API v4"', '"version": "Adaptive API v5"', 1)
api = api.replace('"version": "Adaptive API v3"', '"version": "Adaptive API v5"', 1)

# Python validation before writing.
compile(bridge, str(BRIDGE), "exec")
compile(registry, str(REGISTRY), "exec")
compile(orch, str(ORCH), "exec")
compile(api, str(API), "exec")

BUILD.write_text(build, encoding="utf-8")
H.write_text(h, encoding="utf-8")
CPP.write_text(cpp, encoding="utf-8")
BRIDGE.write_text(bridge, encoding="utf-8")
REGISTRY.write_text(registry, encoding="utf-8")
ORCH.write_text(orch, encoding="utf-8")
API.write_text(api, encoding="utf-8")

print("PATCH_SOURCE_VALID=PASS")
print("BACKUP_DIR=" + str(backup_dir))
