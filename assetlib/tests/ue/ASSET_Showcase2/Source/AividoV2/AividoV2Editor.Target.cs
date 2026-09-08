// Aivido V2 — editor target.

using UnrealBuildTool;
using System.Collections.Generic;

public class AividoV2EditorTarget : TargetRules
{
	public AividoV2EditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("AividoV2");
	}
}
