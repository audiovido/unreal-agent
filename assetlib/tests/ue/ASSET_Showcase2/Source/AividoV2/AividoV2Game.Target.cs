// Aivido V2 — game target.

using UnrealBuildTool;
using System.Collections.Generic;

public class AividoV2GameTarget : TargetRules
{
	public AividoV2GameTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("AividoV2");
	}
}
