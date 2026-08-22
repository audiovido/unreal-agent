from tools.unreal.unreal_bridge import UnrealBridge

b = UnrealBridge()

def inner(r):
    return r.get("result", {}) if isinstance(r, dict) else {}

print("1 PING:", b.ping())

spawn = b.spawn_actor("StaticMeshActor", [100, 200, 300], [0, 0, 0])
print("2 SPAWN:", spawn)

s = inner(spawn)
assert s.get("ok") is True, f"SPAWN FAILED: {spawn}"

name = s.get("name")
assert name, f"NO INTERNAL NAME: {spawn}"
print("   INTERNAL NAME:", name)

g = b.get_actor(name)
print("3 GET:", g)
assert inner(g).get("ok") is True

m = b.move_actor(name, [400, 500, 600])
print("4 MOVE:", m)
assert inner(m).get("ok") is True

g = b.get_actor(name)
print("5 MOVE VERIFY:", g)
assert inner(g).get("location") == [400.0, 500.0, 600.0]

r = b.rotate_actor(name, [10, 20, 30])
print("6 ROTATE:", r)
assert inner(r).get("ok") is True

g = b.get_actor(name)
print("7 ROTATE VERIFY:", g)

scl = b.scale_actor(name, [2, 3, 4])
print("8 SCALE:", scl)
assert inner(scl).get("ok") is True

g = b.get_actor(name)
print("9 SCALE VERIFY:", g)
assert inner(g).get("scale") == [2.0, 3.0, 4.0]

sv = b.save_level()
print("10 SAVE:", sv)
assert inner(sv).get("ok") is True

d = b.delete_actor(name)
print("11 DELETE:", d)
assert inner(d).get("ok") is True

g = b.get_actor(name)
print("12 DELETE VERIFY:", g)
assert inner(g).get("ok") is False

print()
print("FINAL SMOKE TEST: PASS")
