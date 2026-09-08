#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "UnrealAgentBlueprintLibrary.generated.h"

class UK2Node_CallFunction;

UCLASS()
class UNREALAGENTBRIDGE_API UUnrealAgentBlueprintLibrary
    : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:

    UFUNCTION(BlueprintCallable, Category="Unreal Agent|Blueprint Graph")
    static UK2Node_CallFunction* AddCallFunctionNode(
        const FString& BlueprintAssetPath,
        const FString& GraphName,
        const FString& FunctionClassPath,
        const FName FunctionName,
        int32 X,
        int32 Y
    );

    UFUNCTION(BlueprintCallable, Category="Unreal Agent|Blueprint Graph")
    static bool ConnectPinsByTitle(
        const FString& BlueprintAssetPath,
        const FString& GraphName,
        const FString& FromNodeTitle,
        const FName FromPinName,
        const FString& ToNodeTitle,
        const FName ToPinName
    );

    UFUNCTION(BlueprintCallable, Category="Unreal Agent|Blueprint Graph")
    static bool SetPinDefaultValueByTitle(
        const FString& BlueprintAssetPath,
        const FString& GraphName,
        const FString& NodeTitle,
        const FName PinName,
        const FString& Value
    );

    UFUNCTION(BlueprintCallable, Category="Unreal Agent|Blueprint Graph")
    static bool CompileAndSaveBlueprint(
        const FString& BlueprintAssetPath
    );
    UFUNCTION(BlueprintCallable, Category="Unreal Agent|Blueprint Graph")
    static TArray<FString> ListNodePins(
        const FString& BlueprintAssetPath,
        const FString& GraphName,
        const FString& NodeTitle
    );



    UFUNCTION(BlueprintCallable, Category="Unreal Agent|Blueprint Graph")
    static TArray<FString> ListGraphNodes(
        const FString& BlueprintAssetPath,
        const FString& GraphName
    );

    UFUNCTION(BlueprintCallable, Category="Unreal Agent|Blueprint Graph")
    static bool DeleteNodeByTitle(
        const FString& BlueprintAssetPath,
        const FString& GraphName,
        const FString& NodeTitle
    );

    UFUNCTION(BlueprintCallable, Category="Unreal Agent|Viewport")
    static bool CaptureActiveViewport(
        const FString& OutputPath
    );

    UFUNCTION(BlueprintCallable, Category="Unreal Agent|Viewport")
    static FString CaptureActiveViewportDetailed(
        const FString& OutputPath
    );
};



