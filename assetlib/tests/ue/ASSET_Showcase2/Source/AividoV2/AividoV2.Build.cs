// Aivido V2 runtime module — build descriptor.
// Public dependencies: gameplay, input (player input/EnhancedInput),
// umg (HUD widgets), http (director chat round-trips to the backend).

using UnrealBuildTool;

public class AividoV2 : ModuleRules
{
	public AividoV2(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"InputCore",
			"EnhancedInput",
			"UMG",
			"HTTP",
			"Json",
			"Kismet"
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"Slate",
			"SlateCore"
		});
	}
}
