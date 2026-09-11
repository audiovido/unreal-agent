// Copyright Epic Games, Inc. All Rights Reserved.
/*===========================================================================
	Generated code exported from UnrealHeaderTool.
	DO NOT modify this manually! Edit the corresponding .h files instead!
===========================================================================*/

#include "UObject/GeneratedCppIncludes.h"
#include "UnrealAgentBlueprintLibrary.h"

PRAGMA_DISABLE_DEPRECATION_WARNINGS
static_assert(!UE_WITH_CONSTINIT_UOBJECT, "This generated code can only be compiled with !UE_WITH_CONSTINIT_UOBJECT");
void EmptyLinkFunctionForGeneratedCodeUnrealAgentBlueprintLibrary() {}

// ********** Begin Cross Module References ********************************************************
ENGINE_API UClass* Z_Construct_UClass_UBlueprintFunctionLibrary(ETypeConstructPhase);
BLUEPRINTGRAPH_API UClass* Z_Construct_UClass_UK2Node_CallFunction(ETypeConstructPhase);
// ********** End Cross Module References **********************************************************

// ********** Begin Same Module References *********************************************************
UPackage* Z_Construct_UPackage__Script_UnrealAgentBridge(ETypeConstructPhase);
UNREALAGENTBRIDGE_API UClass* Z_Construct_UClass_UUnrealAgentBlueprintLibrary(ETypeConstructPhase);
UNREALAGENTBRIDGE_API UClass* Z_Construct_UClass_UUnrealAgentBlueprintLibrary(ETypeConstructPhase);
// ********** End Same Module References ***********************************************************
#define UHT_STRUCT_BASE(INIT) UE::CodeGen::ConstInit::TCompiledInObjectPtr<const FStructBaseChain>(UE::Private::AsStructBaseChain(INIT))

// ********** Begin Class UUnrealAgentBlueprintLibrary Function AddCallFunctionNode ****************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_AddCallFunctionNode_Statics
struct UHT_STATICS
{
	struct UnrealAgentBlueprintLibrary_eventAddCallFunctionNode_Parms
	{
		FString BlueprintAssetPath;
		FString GraphName;
		FString FunctionClassPath;
		FName FunctionName;
		int32 X;
		int32 Y;
		UK2Node_CallFunction* ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "Category", "Unreal Agent|Blueprint Graph" },
		{ "ModuleRelativePath", "Public/UnrealAgentBlueprintLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_BlueprintAssetPath_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_GraphName_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_FunctionClassPath_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_FunctionName_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function AddCallFunctionNode constinit property declarations *******************
	static const UECodeGen_Private::FStrPropertyParams NewProp_BlueprintAssetPath;
	static const UECodeGen_Private::FStrPropertyParams NewProp_GraphName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_FunctionClassPath;
	static const UECodeGen_Private::FNamePropertyParams NewProp_FunctionName;
	static const UECodeGen_Private::FIntPropertyParams NewProp_X;
	static const UECodeGen_Private::FIntPropertyParams NewProp_Y;
	static const UECodeGen_Private::FObjectPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function AddCallFunctionNode constinit property declarations *********************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function AddCallFunctionNode Property Definitions ******************************
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_BlueprintAssetPath = { "BlueprintAssetPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventAddCallFunctionNode_Parms, BlueprintAssetPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_BlueprintAssetPath_MetaData), NewProp_BlueprintAssetPath_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_GraphName = { "GraphName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventAddCallFunctionNode_Parms, GraphName), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_GraphName_MetaData), NewProp_GraphName_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_FunctionClassPath = { "FunctionClassPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventAddCallFunctionNode_Parms, FunctionClassPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_FunctionClassPath_MetaData), NewProp_FunctionClassPath_MetaData) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_FunctionName = { "FunctionName", nullptr, (EPropertyFlags)0x0010000000000082, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventAddCallFunctionNode_Parms, FunctionName), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_FunctionName_MetaData), NewProp_FunctionName_MetaData) };
const UECodeGen_Private::FIntPropertyParams UHT_STATICS::NewProp_X = { "X", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Int, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventAddCallFunctionNode_Parms, X), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FIntPropertyParams UHT_STATICS::NewProp_Y = { "Y", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Int, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventAddCallFunctionNode_Parms, Y), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FObjectPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Object, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventAddCallFunctionNode_Parms, ReturnValue), Z_Construct_UClass_UK2Node_CallFunction, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_BlueprintAssetPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_GraphName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_FunctionClassPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_FunctionName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_X,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_Y,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function AddCallFunctionNode Property Definitions ********************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UUnrealAgentBlueprintLibrary, nullptr, "AddCallFunctionNode", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::UnrealAgentBlueprintLibrary_eventAddCallFunctionNode_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::UnrealAgentBlueprintLibrary_eventAddCallFunctionNode_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_AddCallFunctionNode(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UUnrealAgentBlueprintLibrary::execAddCallFunctionNode)
{
	P_GET_PROPERTY(FStrProperty,Z_Param_BlueprintAssetPath);
	P_GET_PROPERTY(FStrProperty,Z_Param_GraphName);
	P_GET_PROPERTY(FStrProperty,Z_Param_FunctionClassPath);
	P_GET_PROPERTY(FNameProperty,Z_Param_FunctionName);
	P_GET_PROPERTY(FIntProperty,Z_Param_X);
	P_GET_PROPERTY(FIntProperty,Z_Param_Y);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(UK2Node_CallFunction**)Z_Param__Result=UUnrealAgentBlueprintLibrary::AddCallFunctionNode(Z_Param_BlueprintAssetPath,Z_Param_GraphName,Z_Param_FunctionClassPath,Z_Param_FunctionName,Z_Param_X,Z_Param_Y);
	P_NATIVE_END;
}
// ********** End Class UUnrealAgentBlueprintLibrary Function AddCallFunctionNode ******************

// ********** Begin Class UUnrealAgentBlueprintLibrary Function CaptureActiveViewport **************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_CaptureActiveViewport_Statics
struct UHT_STATICS
{
	struct UnrealAgentBlueprintLibrary_eventCaptureActiveViewport_Parms
	{
		FString OutputPath;
		bool ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "Category", "Unreal Agent|Viewport" },
		{ "ModuleRelativePath", "Public/UnrealAgentBlueprintLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_OutputPath_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function CaptureActiveViewport constinit property declarations *****************
	static const UECodeGen_Private::FStrPropertyParams NewProp_OutputPath;
	static void NewProp_ReturnValue_SetBit(void* Obj)
	{
		((UnrealAgentBlueprintLibrary_eventCaptureActiveViewport_Parms*)Obj)->ReturnValue = 1;
	}
	static const UECodeGen_Private::FBoolPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function CaptureActiveViewport constinit property declarations *******************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function CaptureActiveViewport Property Definitions ****************************
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_OutputPath = { "OutputPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventCaptureActiveViewport_Parms, OutputPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_OutputPath_MetaData), NewProp_OutputPath_MetaData) };
const UECodeGen_Private::FBoolPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Bool | UECodeGen_Private::EPropertyGenFlags::NativeBool, nullptr, nullptr, 1, sizeof(bool), sizeof(UnrealAgentBlueprintLibrary_eventCaptureActiveViewport_Parms), &UHT_STATICS::NewProp_ReturnValue_SetBit, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_OutputPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function CaptureActiveViewport Property Definitions ******************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UUnrealAgentBlueprintLibrary, nullptr, "CaptureActiveViewport", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::UnrealAgentBlueprintLibrary_eventCaptureActiveViewport_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::UnrealAgentBlueprintLibrary_eventCaptureActiveViewport_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_CaptureActiveViewport(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UUnrealAgentBlueprintLibrary::execCaptureActiveViewport)
{
	P_GET_PROPERTY(FStrProperty,Z_Param_OutputPath);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(bool*)Z_Param__Result=UUnrealAgentBlueprintLibrary::CaptureActiveViewport(Z_Param_OutputPath);
	P_NATIVE_END;
}
// ********** End Class UUnrealAgentBlueprintLibrary Function CaptureActiveViewport ****************

// ********** Begin Class UUnrealAgentBlueprintLibrary Function CaptureActiveViewportDetailed ******
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_CaptureActiveViewportDetailed_Statics
struct UHT_STATICS
{
	struct UnrealAgentBlueprintLibrary_eventCaptureActiveViewportDetailed_Parms
	{
		FString OutputPath;
		FString ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "Category", "Unreal Agent|Viewport" },
		{ "ModuleRelativePath", "Public/UnrealAgentBlueprintLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_OutputPath_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function CaptureActiveViewportDetailed constinit property declarations *********
	static const UECodeGen_Private::FStrPropertyParams NewProp_OutputPath;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function CaptureActiveViewportDetailed constinit property declarations ***********
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function CaptureActiveViewportDetailed Property Definitions ********************
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_OutputPath = { "OutputPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventCaptureActiveViewportDetailed_Parms, OutputPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_OutputPath_MetaData), NewProp_OutputPath_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventCaptureActiveViewportDetailed_Parms, ReturnValue), METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_OutputPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function CaptureActiveViewportDetailed Property Definitions **********************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UUnrealAgentBlueprintLibrary, nullptr, "CaptureActiveViewportDetailed", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::UnrealAgentBlueprintLibrary_eventCaptureActiveViewportDetailed_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::UnrealAgentBlueprintLibrary_eventCaptureActiveViewportDetailed_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_CaptureActiveViewportDetailed(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UUnrealAgentBlueprintLibrary::execCaptureActiveViewportDetailed)
{
	P_GET_PROPERTY(FStrProperty,Z_Param_OutputPath);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(FString*)Z_Param__Result=UUnrealAgentBlueprintLibrary::CaptureActiveViewportDetailed(Z_Param_OutputPath);
	P_NATIVE_END;
}
// ********** End Class UUnrealAgentBlueprintLibrary Function CaptureActiveViewportDetailed ********

// ********** Begin Class UUnrealAgentBlueprintLibrary Function CompileAndSaveBlueprint ************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_CompileAndSaveBlueprint_Statics
struct UHT_STATICS
{
	struct UnrealAgentBlueprintLibrary_eventCompileAndSaveBlueprint_Parms
	{
		FString BlueprintAssetPath;
		bool ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "Category", "Unreal Agent|Blueprint Graph" },
		{ "ModuleRelativePath", "Public/UnrealAgentBlueprintLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_BlueprintAssetPath_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function CompileAndSaveBlueprint constinit property declarations ***************
	static const UECodeGen_Private::FStrPropertyParams NewProp_BlueprintAssetPath;
	static void NewProp_ReturnValue_SetBit(void* Obj)
	{
		((UnrealAgentBlueprintLibrary_eventCompileAndSaveBlueprint_Parms*)Obj)->ReturnValue = 1;
	}
	static const UECodeGen_Private::FBoolPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function CompileAndSaveBlueprint constinit property declarations *****************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function CompileAndSaveBlueprint Property Definitions **************************
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_BlueprintAssetPath = { "BlueprintAssetPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventCompileAndSaveBlueprint_Parms, BlueprintAssetPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_BlueprintAssetPath_MetaData), NewProp_BlueprintAssetPath_MetaData) };
const UECodeGen_Private::FBoolPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Bool | UECodeGen_Private::EPropertyGenFlags::NativeBool, nullptr, nullptr, 1, sizeof(bool), sizeof(UnrealAgentBlueprintLibrary_eventCompileAndSaveBlueprint_Parms), &UHT_STATICS::NewProp_ReturnValue_SetBit, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_BlueprintAssetPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function CompileAndSaveBlueprint Property Definitions ****************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UUnrealAgentBlueprintLibrary, nullptr, "CompileAndSaveBlueprint", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::UnrealAgentBlueprintLibrary_eventCompileAndSaveBlueprint_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::UnrealAgentBlueprintLibrary_eventCompileAndSaveBlueprint_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_CompileAndSaveBlueprint(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UUnrealAgentBlueprintLibrary::execCompileAndSaveBlueprint)
{
	P_GET_PROPERTY(FStrProperty,Z_Param_BlueprintAssetPath);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(bool*)Z_Param__Result=UUnrealAgentBlueprintLibrary::CompileAndSaveBlueprint(Z_Param_BlueprintAssetPath);
	P_NATIVE_END;
}
// ********** End Class UUnrealAgentBlueprintLibrary Function CompileAndSaveBlueprint **************

// ********** Begin Class UUnrealAgentBlueprintLibrary Function ConnectPinsByTitle *****************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_ConnectPinsByTitle_Statics
struct UHT_STATICS
{
	struct UnrealAgentBlueprintLibrary_eventConnectPinsByTitle_Parms
	{
		FString BlueprintAssetPath;
		FString GraphName;
		FString FromNodeTitle;
		FName FromPinName;
		FString ToNodeTitle;
		FName ToPinName;
		bool ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "Category", "Unreal Agent|Blueprint Graph" },
		{ "ModuleRelativePath", "Public/UnrealAgentBlueprintLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_BlueprintAssetPath_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_GraphName_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_FromNodeTitle_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_FromPinName_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_ToNodeTitle_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_ToPinName_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function ConnectPinsByTitle constinit property declarations ********************
	static const UECodeGen_Private::FStrPropertyParams NewProp_BlueprintAssetPath;
	static const UECodeGen_Private::FStrPropertyParams NewProp_GraphName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_FromNodeTitle;
	static const UECodeGen_Private::FNamePropertyParams NewProp_FromPinName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ToNodeTitle;
	static const UECodeGen_Private::FNamePropertyParams NewProp_ToPinName;
	static void NewProp_ReturnValue_SetBit(void* Obj)
	{
		((UnrealAgentBlueprintLibrary_eventConnectPinsByTitle_Parms*)Obj)->ReturnValue = 1;
	}
	static const UECodeGen_Private::FBoolPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function ConnectPinsByTitle constinit property declarations **********************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function ConnectPinsByTitle Property Definitions *******************************
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_BlueprintAssetPath = { "BlueprintAssetPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventConnectPinsByTitle_Parms, BlueprintAssetPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_BlueprintAssetPath_MetaData), NewProp_BlueprintAssetPath_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_GraphName = { "GraphName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventConnectPinsByTitle_Parms, GraphName), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_GraphName_MetaData), NewProp_GraphName_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_FromNodeTitle = { "FromNodeTitle", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventConnectPinsByTitle_Parms, FromNodeTitle), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_FromNodeTitle_MetaData), NewProp_FromNodeTitle_MetaData) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_FromPinName = { "FromPinName", nullptr, (EPropertyFlags)0x0010000000000082, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventConnectPinsByTitle_Parms, FromPinName), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_FromPinName_MetaData), NewProp_FromPinName_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ToNodeTitle = { "ToNodeTitle", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventConnectPinsByTitle_Parms, ToNodeTitle), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_ToNodeTitle_MetaData), NewProp_ToNodeTitle_MetaData) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_ToPinName = { "ToPinName", nullptr, (EPropertyFlags)0x0010000000000082, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventConnectPinsByTitle_Parms, ToPinName), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_ToPinName_MetaData), NewProp_ToPinName_MetaData) };
const UECodeGen_Private::FBoolPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Bool | UECodeGen_Private::EPropertyGenFlags::NativeBool, nullptr, nullptr, 1, sizeof(bool), sizeof(UnrealAgentBlueprintLibrary_eventConnectPinsByTitle_Parms), &UHT_STATICS::NewProp_ReturnValue_SetBit, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_BlueprintAssetPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_GraphName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_FromNodeTitle,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_FromPinName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ToNodeTitle,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ToPinName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function ConnectPinsByTitle Property Definitions *********************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UUnrealAgentBlueprintLibrary, nullptr, "ConnectPinsByTitle", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::UnrealAgentBlueprintLibrary_eventConnectPinsByTitle_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::UnrealAgentBlueprintLibrary_eventConnectPinsByTitle_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_ConnectPinsByTitle(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UUnrealAgentBlueprintLibrary::execConnectPinsByTitle)
{
	P_GET_PROPERTY(FStrProperty,Z_Param_BlueprintAssetPath);
	P_GET_PROPERTY(FStrProperty,Z_Param_GraphName);
	P_GET_PROPERTY(FStrProperty,Z_Param_FromNodeTitle);
	P_GET_PROPERTY(FNameProperty,Z_Param_FromPinName);
	P_GET_PROPERTY(FStrProperty,Z_Param_ToNodeTitle);
	P_GET_PROPERTY(FNameProperty,Z_Param_ToPinName);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(bool*)Z_Param__Result=UUnrealAgentBlueprintLibrary::ConnectPinsByTitle(Z_Param_BlueprintAssetPath,Z_Param_GraphName,Z_Param_FromNodeTitle,Z_Param_FromPinName,Z_Param_ToNodeTitle,Z_Param_ToPinName);
	P_NATIVE_END;
}
// ********** End Class UUnrealAgentBlueprintLibrary Function ConnectPinsByTitle *******************

// ********** Begin Class UUnrealAgentBlueprintLibrary Function DeleteNodeByTitle ******************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_DeleteNodeByTitle_Statics
struct UHT_STATICS
{
	struct UnrealAgentBlueprintLibrary_eventDeleteNodeByTitle_Parms
	{
		FString BlueprintAssetPath;
		FString GraphName;
		FString NodeTitle;
		bool ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "Category", "Unreal Agent|Blueprint Graph" },
		{ "ModuleRelativePath", "Public/UnrealAgentBlueprintLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_BlueprintAssetPath_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_GraphName_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_NodeTitle_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function DeleteNodeByTitle constinit property declarations *********************
	static const UECodeGen_Private::FStrPropertyParams NewProp_BlueprintAssetPath;
	static const UECodeGen_Private::FStrPropertyParams NewProp_GraphName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_NodeTitle;
	static void NewProp_ReturnValue_SetBit(void* Obj)
	{
		((UnrealAgentBlueprintLibrary_eventDeleteNodeByTitle_Parms*)Obj)->ReturnValue = 1;
	}
	static const UECodeGen_Private::FBoolPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function DeleteNodeByTitle constinit property declarations ***********************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function DeleteNodeByTitle Property Definitions ********************************
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_BlueprintAssetPath = { "BlueprintAssetPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventDeleteNodeByTitle_Parms, BlueprintAssetPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_BlueprintAssetPath_MetaData), NewProp_BlueprintAssetPath_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_GraphName = { "GraphName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventDeleteNodeByTitle_Parms, GraphName), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_GraphName_MetaData), NewProp_GraphName_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_NodeTitle = { "NodeTitle", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventDeleteNodeByTitle_Parms, NodeTitle), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_NodeTitle_MetaData), NewProp_NodeTitle_MetaData) };
const UECodeGen_Private::FBoolPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Bool | UECodeGen_Private::EPropertyGenFlags::NativeBool, nullptr, nullptr, 1, sizeof(bool), sizeof(UnrealAgentBlueprintLibrary_eventDeleteNodeByTitle_Parms), &UHT_STATICS::NewProp_ReturnValue_SetBit, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_BlueprintAssetPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_GraphName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_NodeTitle,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function DeleteNodeByTitle Property Definitions **********************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UUnrealAgentBlueprintLibrary, nullptr, "DeleteNodeByTitle", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::UnrealAgentBlueprintLibrary_eventDeleteNodeByTitle_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::UnrealAgentBlueprintLibrary_eventDeleteNodeByTitle_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_DeleteNodeByTitle(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UUnrealAgentBlueprintLibrary::execDeleteNodeByTitle)
{
	P_GET_PROPERTY(FStrProperty,Z_Param_BlueprintAssetPath);
	P_GET_PROPERTY(FStrProperty,Z_Param_GraphName);
	P_GET_PROPERTY(FStrProperty,Z_Param_NodeTitle);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(bool*)Z_Param__Result=UUnrealAgentBlueprintLibrary::DeleteNodeByTitle(Z_Param_BlueprintAssetPath,Z_Param_GraphName,Z_Param_NodeTitle);
	P_NATIVE_END;
}
// ********** End Class UUnrealAgentBlueprintLibrary Function DeleteNodeByTitle ********************

// ********** Begin Class UUnrealAgentBlueprintLibrary Function ListGraphNodes *********************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_ListGraphNodes_Statics
struct UHT_STATICS
{
	struct UnrealAgentBlueprintLibrary_eventListGraphNodes_Parms
	{
		FString BlueprintAssetPath;
		FString GraphName;
		TArray<FString> ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "Category", "Unreal Agent|Blueprint Graph" },
		{ "ModuleRelativePath", "Public/UnrealAgentBlueprintLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_BlueprintAssetPath_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_GraphName_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function ListGraphNodes constinit property declarations ************************
	static const UECodeGen_Private::FStrPropertyParams NewProp_BlueprintAssetPath;
	static const UECodeGen_Private::FStrPropertyParams NewProp_GraphName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue_Inner;
	static const UECodeGen_Private::FArrayPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function ListGraphNodes constinit property declarations **************************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function ListGraphNodes Property Definitions ***********************************
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_BlueprintAssetPath = { "BlueprintAssetPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventListGraphNodes_Parms, BlueprintAssetPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_BlueprintAssetPath_MetaData), NewProp_BlueprintAssetPath_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_GraphName = { "GraphName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventListGraphNodes_Parms, GraphName), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_GraphName_MetaData), NewProp_GraphName_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue_Inner = { "ReturnValue", nullptr, (EPropertyFlags)0x0000000000000000, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, 0, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FArrayPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Array, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventListGraphNodes_Parms, ReturnValue), EArrayPropertyFlags::None, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_BlueprintAssetPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_GraphName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue_Inner,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function ListGraphNodes Property Definitions *************************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UUnrealAgentBlueprintLibrary, nullptr, "ListGraphNodes", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::UnrealAgentBlueprintLibrary_eventListGraphNodes_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::UnrealAgentBlueprintLibrary_eventListGraphNodes_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_ListGraphNodes(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UUnrealAgentBlueprintLibrary::execListGraphNodes)
{
	P_GET_PROPERTY(FStrProperty,Z_Param_BlueprintAssetPath);
	P_GET_PROPERTY(FStrProperty,Z_Param_GraphName);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(TArray<FString>*)Z_Param__Result=UUnrealAgentBlueprintLibrary::ListGraphNodes(Z_Param_BlueprintAssetPath,Z_Param_GraphName);
	P_NATIVE_END;
}
// ********** End Class UUnrealAgentBlueprintLibrary Function ListGraphNodes ***********************

// ********** Begin Class UUnrealAgentBlueprintLibrary Function ListNodePins ***********************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_ListNodePins_Statics
struct UHT_STATICS
{
	struct UnrealAgentBlueprintLibrary_eventListNodePins_Parms
	{
		FString BlueprintAssetPath;
		FString GraphName;
		FString NodeTitle;
		TArray<FString> ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "Category", "Unreal Agent|Blueprint Graph" },
		{ "ModuleRelativePath", "Public/UnrealAgentBlueprintLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_BlueprintAssetPath_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_GraphName_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_NodeTitle_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function ListNodePins constinit property declarations **************************
	static const UECodeGen_Private::FStrPropertyParams NewProp_BlueprintAssetPath;
	static const UECodeGen_Private::FStrPropertyParams NewProp_GraphName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_NodeTitle;
	static const UECodeGen_Private::FStrPropertyParams NewProp_ReturnValue_Inner;
	static const UECodeGen_Private::FArrayPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function ListNodePins constinit property declarations ****************************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function ListNodePins Property Definitions *************************************
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_BlueprintAssetPath = { "BlueprintAssetPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventListNodePins_Parms, BlueprintAssetPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_BlueprintAssetPath_MetaData), NewProp_BlueprintAssetPath_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_GraphName = { "GraphName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventListNodePins_Parms, GraphName), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_GraphName_MetaData), NewProp_GraphName_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_NodeTitle = { "NodeTitle", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventListNodePins_Parms, NodeTitle), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_NodeTitle_MetaData), NewProp_NodeTitle_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_ReturnValue_Inner = { "ReturnValue", nullptr, (EPropertyFlags)0x0000000000000000, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, 0, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FArrayPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Array, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventListNodePins_Parms, ReturnValue), EArrayPropertyFlags::None, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_BlueprintAssetPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_GraphName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_NodeTitle,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue_Inner,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function ListNodePins Property Definitions ***************************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UUnrealAgentBlueprintLibrary, nullptr, "ListNodePins", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::UnrealAgentBlueprintLibrary_eventListNodePins_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::UnrealAgentBlueprintLibrary_eventListNodePins_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_ListNodePins(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UUnrealAgentBlueprintLibrary::execListNodePins)
{
	P_GET_PROPERTY(FStrProperty,Z_Param_BlueprintAssetPath);
	P_GET_PROPERTY(FStrProperty,Z_Param_GraphName);
	P_GET_PROPERTY(FStrProperty,Z_Param_NodeTitle);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(TArray<FString>*)Z_Param__Result=UUnrealAgentBlueprintLibrary::ListNodePins(Z_Param_BlueprintAssetPath,Z_Param_GraphName,Z_Param_NodeTitle);
	P_NATIVE_END;
}
// ********** End Class UUnrealAgentBlueprintLibrary Function ListNodePins *************************

// ********** Begin Class UUnrealAgentBlueprintLibrary Function SetPinDefaultValueByTitle **********
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_SetPinDefaultValueByTitle_Statics
struct UHT_STATICS
{
	struct UnrealAgentBlueprintLibrary_eventSetPinDefaultValueByTitle_Parms
	{
		FString BlueprintAssetPath;
		FString GraphName;
		FString NodeTitle;
		FName PinName;
		FString Value;
		bool ReturnValue;
	};
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "Category", "Unreal Agent|Blueprint Graph" },
		{ "ModuleRelativePath", "Public/UnrealAgentBlueprintLibrary.h" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_BlueprintAssetPath_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_GraphName_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_NodeTitle_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_PinName_MetaData[] = {
		{ "NativeConst", "" },
	};
	static constexpr UECodeGen_Private::FMetaDataPairParam NewProp_Value_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif // WITH_METADATA

// ********** Begin Function SetPinDefaultValueByTitle constinit property declarations *************
	static const UECodeGen_Private::FStrPropertyParams NewProp_BlueprintAssetPath;
	static const UECodeGen_Private::FStrPropertyParams NewProp_GraphName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_NodeTitle;
	static const UECodeGen_Private::FNamePropertyParams NewProp_PinName;
	static const UECodeGen_Private::FStrPropertyParams NewProp_Value;
	static void NewProp_ReturnValue_SetBit(void* Obj)
	{
		((UnrealAgentBlueprintLibrary_eventSetPinDefaultValueByTitle_Parms*)Obj)->ReturnValue = 1;
	}
	static const UECodeGen_Private::FBoolPropertyParams NewProp_ReturnValue;
	static const UECodeGen_Private::FPropertyParamsBase* const PropPointers[];
// ********** End Function SetPinDefaultValueByTitle constinit property declarations ***************
	static const UECodeGen_Private::FFunctionParams FuncParams;
};

// ********** Begin Function SetPinDefaultValueByTitle Property Definitions ************************
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_BlueprintAssetPath = { "BlueprintAssetPath", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventSetPinDefaultValueByTitle_Parms, BlueprintAssetPath), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_BlueprintAssetPath_MetaData), NewProp_BlueprintAssetPath_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_GraphName = { "GraphName", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventSetPinDefaultValueByTitle_Parms, GraphName), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_GraphName_MetaData), NewProp_GraphName_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_NodeTitle = { "NodeTitle", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventSetPinDefaultValueByTitle_Parms, NodeTitle), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_NodeTitle_MetaData), NewProp_NodeTitle_MetaData) };
const UECodeGen_Private::FNamePropertyParams UHT_STATICS::NewProp_PinName = { "PinName", nullptr, (EPropertyFlags)0x0010000000000082, UECodeGen_Private::EPropertyGenFlags::Name, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventSetPinDefaultValueByTitle_Parms, PinName), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_PinName_MetaData), NewProp_PinName_MetaData) };
const UECodeGen_Private::FStrPropertyParams UHT_STATICS::NewProp_Value = { "Value", nullptr, (EPropertyFlags)0x0010000000000080, UECodeGen_Private::EPropertyGenFlags::Str, nullptr, nullptr, 1, STRUCT_OFFSET(UnrealAgentBlueprintLibrary_eventSetPinDefaultValueByTitle_Parms, Value), METADATA_PARAMS(UE_ARRAY_COUNT(NewProp_Value_MetaData), NewProp_Value_MetaData) };
const UECodeGen_Private::FBoolPropertyParams UHT_STATICS::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UECodeGen_Private::EPropertyGenFlags::Bool | UECodeGen_Private::EPropertyGenFlags::NativeBool, nullptr, nullptr, 1, sizeof(bool), sizeof(UnrealAgentBlueprintLibrary_eventSetPinDefaultValueByTitle_Parms), &UHT_STATICS::NewProp_ReturnValue_SetBit, METADATA_PARAMS(0, nullptr) };
const UECodeGen_Private::FPropertyParamsBase* const UHT_STATICS::PropPointers[] = {
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_BlueprintAssetPath,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_GraphName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_NodeTitle,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_PinName,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_Value,
	(const UECodeGen_Private::FPropertyParamsBase*)&UHT_STATICS::NewProp_ReturnValue,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::PropPointers) < 2048);
// ********** End Function SetPinDefaultValueByTitle Property Definitions **************************
const UECodeGen_Private::FFunctionParams UHT_STATICS::FuncParams = { { (FTypeConstructFunc*)Z_Construct_UClass_UUnrealAgentBlueprintLibrary, nullptr, "SetPinDefaultValueByTitle", UHT_STATICS::PropPointers, UE_ARRAY_COUNT(UHT_STATICS::PropPointers), DataSizeOf<UHT_STATICS::UnrealAgentBlueprintLibrary_eventSetPinDefaultValueByTitle_Parms>(), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)},  };
static_assert(sizeof(UHT_STATICS::UnrealAgentBlueprintLibrary_eventSetPinDefaultValueByTitle_Parms) < MAX_uint16);
UFunction* Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_SetPinDefaultValueByTitle(ETypeConstructPhase Phase)
{
	static UFunction* ReturnFunction = nullptr;
	if (!ReturnFunction)
	{
		UECodeGen_Private::ConstructUFunction(&ReturnFunction, UHT_STATICS::FuncParams);
	}
	return ReturnFunction;
}
#undef UHT_STATICS
DEFINE_FUNCTION(UUnrealAgentBlueprintLibrary::execSetPinDefaultValueByTitle)
{
	P_GET_PROPERTY(FStrProperty,Z_Param_BlueprintAssetPath);
	P_GET_PROPERTY(FStrProperty,Z_Param_GraphName);
	P_GET_PROPERTY(FStrProperty,Z_Param_NodeTitle);
	P_GET_PROPERTY(FNameProperty,Z_Param_PinName);
	P_GET_PROPERTY(FStrProperty,Z_Param_Value);
	P_FINISH;
	P_NATIVE_BEGIN;
	*(bool*)Z_Param__Result=UUnrealAgentBlueprintLibrary::SetPinDefaultValueByTitle(Z_Param_BlueprintAssetPath,Z_Param_GraphName,Z_Param_NodeTitle,Z_Param_PinName,Z_Param_Value);
	P_NATIVE_END;
}
// ********** End Class UUnrealAgentBlueprintLibrary Function SetPinDefaultValueByTitle ************

// ********** Begin Class UUnrealAgentBlueprintLibrary *********************************************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_Construct_UClass_UUnrealAgentBlueprintLibrary_Statics
struct UHT_STATICS
{
#if WITH_METADATA
	static constexpr UECodeGen_Private::FMetaDataPairParam Type_MetaData[] = {
		{ "IncludePath", "UnrealAgentBlueprintLibrary.h" },
		{ "ModuleRelativePath", "Public/UnrealAgentBlueprintLibrary.h" },
	};
#endif // WITH_METADATA

// ********** Begin Class UUnrealAgentBlueprintLibrary constinit property declarations *************
// ********** End Class UUnrealAgentBlueprintLibrary constinit property declarations ***************
	static constexpr UE::CodeGen::FClassNativeFunction Funcs[] = {
		{ .NameUTF8 = UTF8TEXT("AddCallFunctionNode"), .Pointer = &UUnrealAgentBlueprintLibrary::execAddCallFunctionNode },
		{ .NameUTF8 = UTF8TEXT("CaptureActiveViewport"), .Pointer = &UUnrealAgentBlueprintLibrary::execCaptureActiveViewport },
		{ .NameUTF8 = UTF8TEXT("CaptureActiveViewportDetailed"), .Pointer = &UUnrealAgentBlueprintLibrary::execCaptureActiveViewportDetailed },
		{ .NameUTF8 = UTF8TEXT("CompileAndSaveBlueprint"), .Pointer = &UUnrealAgentBlueprintLibrary::execCompileAndSaveBlueprint },
		{ .NameUTF8 = UTF8TEXT("ConnectPinsByTitle"), .Pointer = &UUnrealAgentBlueprintLibrary::execConnectPinsByTitle },
		{ .NameUTF8 = UTF8TEXT("DeleteNodeByTitle"), .Pointer = &UUnrealAgentBlueprintLibrary::execDeleteNodeByTitle },
		{ .NameUTF8 = UTF8TEXT("ListGraphNodes"), .Pointer = &UUnrealAgentBlueprintLibrary::execListGraphNodes },
		{ .NameUTF8 = UTF8TEXT("ListNodePins"), .Pointer = &UUnrealAgentBlueprintLibrary::execListNodePins },
		{ .NameUTF8 = UTF8TEXT("SetPinDefaultValueByTitle"), .Pointer = &UUnrealAgentBlueprintLibrary::execSetPinDefaultValueByTitle },
	};
	static FTypeConstructFunc* DependentSingletons[];
	static constexpr FClassFunctionLinkInfo FuncInfo[] = {
		{ &Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_AddCallFunctionNode, "AddCallFunctionNode" }, // 167ccb1f7f1b018aaa48764837048cae8f26571b
		{ &Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_CaptureActiveViewport, "CaptureActiveViewport" }, // 6114a9e81bd1b2b6ace61c75c43c39aebfabee0b
		{ &Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_CaptureActiveViewportDetailed, "CaptureActiveViewportDetailed" }, // e6d0f6d2d3d9038c381a24b5db4b975b61afa8c7
		{ &Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_CompileAndSaveBlueprint, "CompileAndSaveBlueprint" }, // 431c5a01ccecfc4f0601828410882230978d731b
		{ &Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_ConnectPinsByTitle, "ConnectPinsByTitle" }, // 6b875be3b9ffbc5ab0e9b61d7409e4276add0fe5
		{ &Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_DeleteNodeByTitle, "DeleteNodeByTitle" }, // 3b3df646e20c86fbb76c2294a95536b9fe3c90c8
		{ &Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_ListGraphNodes, "ListGraphNodes" }, // 48b618ee0c8fd31dbefd6a1f4c72749314a3bfc1
		{ &Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_ListNodePins, "ListNodePins" }, // 607cc02fd8c432d9e5c63d2fce9d5a08d13d4f66
		{ &Z_Construct_UFunction_UUnrealAgentBlueprintLibrary_SetPinDefaultValueByTitle, "SetPinDefaultValueByTitle" }, // d5f1a7024ff63e7ab45506f0c65f01bd7b72325e
	};
	static_assert(UE_ARRAY_COUNT(FuncInfo) < 2048);
	static constexpr FCppClassTypeInfoStatic StaticCppClassTypeInfo = {
		TCppClassTypeTraits<UUnrealAgentBlueprintLibrary>::IsAbstract,
	};
	static const UECodeGen_Private::FClassParams ClassParams;
}; // struct UHT_STATICS
FTypeConstructFunc* UHT_STATICS::DependentSingletons[] = {
	(FTypeConstructFunc*)Z_Construct_UClass_UBlueprintFunctionLibrary,
	(FTypeConstructFunc*)Z_Construct_UPackage__Script_UnrealAgentBridge,
};
static_assert(UE_ARRAY_COUNT(UHT_STATICS::DependentSingletons) < 16);
const UECodeGen_Private::FClassParams UHT_STATICS::ClassParams = {
	&Z_Construct_UClass_UUnrealAgentBlueprintLibrary,
	nullptr,
	&StaticCppClassTypeInfo,
	DependentSingletons,
	FuncInfo,
	nullptr,
	nullptr,
	UE_ARRAY_COUNT(DependentSingletons),
	UE_ARRAY_COUNT(FuncInfo),
	0,
	0,
	0x001000A0u,
	METADATA_PARAMS(UE_ARRAY_COUNT(UHT_STATICS::Type_MetaData), UHT_STATICS::Type_MetaData)
};
static void UUnrealAgentBlueprintLibrary_StaticRegisterNativesUUnrealAgentBlueprintLibrary()
{
	UClass* Class = UUnrealAgentBlueprintLibrary::StaticClass();
	FNativeFunctionRegistrar::RegisterFunctions(Class, 		MakeConstArrayView(UHT_STATICS::Funcs));
}
FClassRegistrationInfo Z_Registration_Info_UClass_UUnrealAgentBlueprintLibrary;
UClass* Z_Construct_UClass_UUnrealAgentBlueprintLibrary(ETypeConstructPhase Phase)
{
	if (Phase == ETypeConstructPhase::Inner)
	{
		using TClass = UUnrealAgentBlueprintLibrary;
		if (!Z_Registration_Info_UClass_UUnrealAgentBlueprintLibrary.InnerSingleton)
		{
			GetPrivateStaticClassBody(
				TClass::StaticPackage(),
				TEXT("UnrealAgentBlueprintLibrary"),
				Z_Registration_Info_UClass_UUnrealAgentBlueprintLibrary.InnerSingleton,
				UUnrealAgentBlueprintLibrary_StaticRegisterNativesUUnrealAgentBlueprintLibrary,
				DataSizeOf<TClass>(),
				alignof(TClass),
				TClass::StaticClassFlags,
				TClass::StaticClassCastFlags(),
				TClass::StaticConfigName(),
				(UClass::ClassConstructorType)InternalConstructor<TClass>,
				(UClass::ClassVTableHelperCtorCallerType)InternalVTableHelperCtorCaller<TClass>,
				UOBJECT_CPPCLASS_STATICFUNCTIONS_FORCLASS(TClass),
				&TClass::Super::StaticClass,
				&TClass::WithinClass::StaticClass
			);
		}
		return Z_Registration_Info_UClass_UUnrealAgentBlueprintLibrary.InnerSingleton;
	}
	if (!Z_Registration_Info_UClass_UUnrealAgentBlueprintLibrary.OuterSingleton)
	{
		UECodeGen_Private::ConstructUClass(Z_Registration_Info_UClass_UUnrealAgentBlueprintLibrary.OuterSingleton, UHT_STATICS::ClassParams);
	}
	return Z_Registration_Info_UClass_UUnrealAgentBlueprintLibrary.OuterSingleton;
}
#undef UHT_STATICS
UUnrealAgentBlueprintLibrary::UUnrealAgentBlueprintLibrary(const FObjectInitializer& ObjectInitializer) : Super(ObjectInitializer) {}
DEFINE_VTABLE_PTR_HELPER_CTOR_NS(, UUnrealAgentBlueprintLibrary);
UUnrealAgentBlueprintLibrary::~UUnrealAgentBlueprintLibrary() {}
// ********** End Class UUnrealAgentBlueprintLibrary ***********************************************

// ********** Begin Registration *******************************************************************
#ifdef UHT_STATICS
#error UHT_STATICS already defined
#endif
#define UHT_STATICS Z_CompiledInDeferFile_FID_AudioVidoLivingCity_Plugins_UnrealAgentBridge_Source_UnrealAgentBridge_Public_UnrealAgentBlueprintLibrary_h__Script_UnrealAgentBridge_Statics
struct UHT_STATICS
{
	static constexpr FClassRegisterCompiledInInfo ClassInfo[] = {
		{ Z_Construct_UClass_UUnrealAgentBlueprintLibrary, TEXT("UUnrealAgentBlueprintLibrary"), &Z_Registration_Info_UClass_UUnrealAgentBlueprintLibrary, CONSTRUCT_RELOAD_VERSION_INFO(FClassReloadVersionInfo, sizeof(UUnrealAgentBlueprintLibrary), 1856094279U) },
	};
}; // UHT_STATICS 
static FRegisterCompiledInInfo Z_CompiledInDeferFile_FID_AudioVidoLivingCity_Plugins_UnrealAgentBridge_Source_UnrealAgentBridge_Public_UnrealAgentBlueprintLibrary_h__Script_UnrealAgentBridge_a0aa1e861bdc0718865dba83c1bd5ec9bf746994{
	TEXT("/Script/UnrealAgentBridge"),
	UHT_STATICS::ClassInfo, UE_ARRAY_COUNT(UHT_STATICS::ClassInfo),
	nullptr, 0,
	nullptr, 0,
	nullptr, 0,
};
#undef UHT_STATICS
// ********** End Registration *********************************************************************
#undef UHT_STRUCT_BASE

PRAGMA_ENABLE_DEPRECATION_WARNINGS
