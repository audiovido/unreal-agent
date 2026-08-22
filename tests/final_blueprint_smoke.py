from tools.unreal.unreal_bridge import UnrealBridge
from tools.unreal.blueprint_tools import BlueprintTools
import pprint

bridge = UnrealBridge()
bp = BlueprintTools(bridge)

asset = "/Game/AgentTests/BP_AgentSmoke"

steps = []

# 1) Create
r1 = bp.create_blueprint(asset, "Actor")
steps.append(("create", r1))

# 2) Add variable
r2 = bp.add_blueprint_variable(
    asset,
    "TestSpeed",
    "Float"
)
steps.append(("variable", r2))

# 3) Add component
r3 = bp.add_blueprint_component(
    asset,
    "StaticMeshComponent",
    "TestMesh"
)
steps.append(("component", r3))

# 4) Compile
r4 = bp.compile_blueprint(asset)
steps.append(("compile", r4))

# 5) Save
r5 = bp.save_blueprint(asset)
steps.append(("save", r5))

# 6) Inspect / verify
r6 = bp.inspect_blueprint(asset)
steps.append(("inspect", r6))

for name, result in steps:
    print(f"\n=== {name.upper()} ===")
    pprint.pp(result)

inner = r6.get("result", {})
if not inner.get("ok"):
    raise SystemExit("FINAL BLUEPRINT SMOKE TEST: FAIL - inspect failed")

variables = inner.get("variables", [])
components = inner.get("components", [])

has_var = any("TestSpeed" in str(v) for v in variables)
has_component = any(
    c.get("name") == "TestMesh"
    or "TestMesh" in c.get("name", "")
    for c in components
)

if not has_var:
    raise SystemExit(
        "FINAL BLUEPRINT SMOKE TEST: FAIL - TestSpeed variable not verified"
    )

if not has_component:
    raise SystemExit(
        "FINAL BLUEPRINT SMOKE TEST: FAIL - TestMesh component not verified"
    )

print("\nFINAL BLUEPRINT SMOKE TEST: PASS")
