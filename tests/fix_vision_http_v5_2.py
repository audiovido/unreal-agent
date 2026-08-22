from pathlib import Path
import shutil, time, re, base64

AGENT = Path(r"C:\Users\Shadow\Desktop\Unreal-Agent")
BRIDGE = AGENT / "tools" / "unreal" / "unreal_bridge.py"
API = AGENT / "app" / "api.py"

stamp = time.strftime("%Y%m%d_%H%M%S")
backup = AGENT / "backups" / f"vision_http_fix_v5_2_{stamp}"
backup.mkdir(parents=True, exist_ok=True)
shutil.copy2(BRIDGE, backup / "unreal_bridge.py")
shutil.copy2(API, backup / "api.py")

bridge = BRIDGE.read_text(encoding="utf-8-sig")
api = API.read_text(encoding="utf-8-sig")

bridge = bridge.replace('            "format": "json",\n', '', 1)

if not re.search(r"^import re\s*$", bridge, re.M):
    bridge = bridge.replace("import requests\n", "import requests\nimport re\n", 1)

old = "            review = json.loads(content)\n"
new = base64.b64decode("ICAgICAgICAgICAgY29udGVudCA9IHN0cihjb250ZW50KS5zdHJpcCgpCgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICByZXZpZXcgPSBqc29uLmxvYWRzKGNvbnRlbnQpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBjbGVhbmVkID0gY29udGVudAoKICAgICAgICAgICAgICAgIGlmIGNsZWFuZWQuc3RhcnRzd2l0aCgiYGBgIik6CiAgICAgICAgICAgICAgICAgICAgY2xlYW5lZCA9IHJlLnN1YigKICAgICAgICAgICAgICAgICAgICAgICAgciJeYGBgKD86anNvbik/XHMqIiwKICAgICAgICAgICAgICAgICAgICAgICAgIiIsCiAgICAgICAgICAgICAgICAgICAgICAgIGNsZWFuZWQsCiAgICAgICAgICAgICAgICAgICAgICAgIGNvdW50PTEsCiAgICAgICAgICAgICAgICAgICAgICAgIGZsYWdzPXJlLklHTk9SRUNBU0UsCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIGNsZWFuZWQgPSByZS5zdWIoCiAgICAgICAgICAgICAgICAgICAgICAgIHIiXHMqYGBgJCIsCiAgICAgICAgICAgICAgICAgICAgICAgICIiLAogICAgICAgICAgICAgICAgICAgICAgICBjbGVhbmVkLAogICAgICAgICAgICAgICAgICAgICAgICBjb3VudD0xLAogICAgICAgICAgICAgICAgICAgICkKCiAgICAgICAgICAgICAgICBzdGFydCA9IGNsZWFuZWQuZmluZCgieyIpCiAgICAgICAgICAgICAgICBlbmQgPSBjbGVhbmVkLnJmaW5kKCJ9IikKCiAgICAgICAgICAgICAgICBpZiBzdGFydCA+PSAwIGFuZCBlbmQgPiBzdGFydDoKICAgICAgICAgICAgICAgICAgICBjbGVhbmVkID0gY2xlYW5lZFtzdGFydDplbmQgKyAxXQoKICAgICAgICAgICAgICAgIHJldmlldyA9IGpzb24ubG9hZHMoY2xlYW5lZCkK").decode("utf-8")

if old not in bridge:
    raise RuntimeError("Could not find visual review JSON parser.")

bridge = bridge.replace(old, new, 1)

api = api.replace('version="5.1.0"', 'version="5.2.0"', 1)
api = api.replace('"version": "Adaptive API v5.1"', '"version": "Adaptive API v5.2"', 1)

compile(bridge, str(BRIDGE), "exec")
compile(api, str(API), "exec")

BRIDGE.write_text(bridge, encoding="utf-8")
API.write_text(api, encoding="utf-8")

print("VISION_HTTP_FIX_SOURCE=PASS")
print("BACKUP_DIR=" + str(backup))
