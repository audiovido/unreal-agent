using UnrealBuildTool;

public class UnrealAgentBridge : ModuleRules
{
    public UnrealAgentBridge(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(
            new string[]
            {
                "Core"
            }
        );

        PrivateDependencyModuleNames.AddRange(
            new string[]
            {
                "CoreUObject",
                "Engine",
                "ImageCore",
                "UnrealEd",
                "BlueprintGraph",
                "Kismet",
                "KismetCompiler"
            }
        );
    }
}
