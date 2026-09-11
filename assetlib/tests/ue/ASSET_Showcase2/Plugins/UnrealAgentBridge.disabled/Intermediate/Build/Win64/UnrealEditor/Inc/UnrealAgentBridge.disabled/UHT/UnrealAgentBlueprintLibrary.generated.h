// Copyright Epic Games, Inc. All Rights Reserved.
/*===========================================================================
	Generated code exported from UnrealHeaderTool.
	DO NOT modify this manually! Edit the corresponding .h files instead!
===========================================================================*/

// IWYU pragma: private, include "UnrealAgentBlueprintLibrary.h"

#ifdef UNREALAGENTBRIDGE_UnrealAgentBlueprintLibrary_generated_h
#error "UnrealAgentBlueprintLibrary.generated.h already included, missing '#pragma once' in UnrealAgentBlueprintLibrary.h"
#endif
#define UNREALAGENTBRIDGE_UnrealAgentBlueprintLibrary_generated_h

#include "UObject/ObjectMacros.h"
#include "UObject/ReflectedTypeAccessors.h"
#include "UObject/ScriptMacros.h"

PRAGMA_DISABLE_DEPRECATION_WARNINGS
class UK2Node_CallFunction;

// ********** Begin Class UUnrealAgentBlueprintLibrary *********************************************
#define FID_AudioVidoLivingCity_Plugins_UnrealAgentBridge_Source_UnrealAgentBridge_Public_UnrealAgentBlueprintLibrary_h_13_RPC_WRAPPERS_NO_PURE_DECLS \
	DECLARE_FUNCTION(execCaptureActiveViewportDetailed); \
	DECLARE_FUNCTION(execCaptureActiveViewport); \
	DECLARE_FUNCTION(execDeleteNodeByTitle); \
	DECLARE_FUNCTION(execListGraphNodes); \
	DECLARE_FUNCTION(execListNodePins); \
	DECLARE_FUNCTION(execCompileAndSaveBlueprint); \
	DECLARE_FUNCTION(execSetPinDefaultValueByTitle); \
	DECLARE_FUNCTION(execConnectPinsByTitle); \
	DECLARE_FUNCTION(execAddCallFunctionNode);


struct Z_Construct_UClass_UUnrealAgentBlueprintLibrary_Statics;
UNREALAGENTBRIDGE_API UClass* Z_Construct_UClass_UUnrealAgentBlueprintLibrary(ETypeConstructPhase);

#define FID_AudioVidoLivingCity_Plugins_UnrealAgentBridge_Source_UnrealAgentBridge_Public_UnrealAgentBlueprintLibrary_h_13_INCLASS_NO_PURE_DECLS \
private: \
	friend struct ::Z_Construct_UClass_UUnrealAgentBlueprintLibrary_Statics; \
	friend UNREALAGENTBRIDGE_API UClass* ::Z_Construct_UClass_UUnrealAgentBlueprintLibrary(ETypeConstructPhase); \
public: \
	DECLARE_CLASS2(UUnrealAgentBlueprintLibrary, UBlueprintFunctionLibrary, COMPILED_IN_FLAGS(0), CASTCLASS_None, TEXT("/Script/UnrealAgentBridge"), Z_Construct_UClass_UUnrealAgentBlueprintLibrary) \
	DECLARE_SERIALIZER(UUnrealAgentBlueprintLibrary)


#define FID_AudioVidoLivingCity_Plugins_UnrealAgentBridge_Source_UnrealAgentBridge_Public_UnrealAgentBlueprintLibrary_h_13_ENHANCED_CONSTRUCTORS \
	/** Standard constructor, called after all reflected properties have been initialized */ \
	NO_API UUnrealAgentBlueprintLibrary(const FObjectInitializer& ObjectInitializer = FObjectInitializer::Get()); \
	/** Deleted move- and copy-constructors, should never be used */ \
	UUnrealAgentBlueprintLibrary(UUnrealAgentBlueprintLibrary&&) = delete; \
	UUnrealAgentBlueprintLibrary(const UUnrealAgentBlueprintLibrary&) = delete; \
	DECLARE_VTABLE_PTR_HELPER_CTOR(NO_API, UUnrealAgentBlueprintLibrary); \
	DEFINE_VTABLE_PTR_HELPER_CTOR_CALLER(UUnrealAgentBlueprintLibrary); \
	DEFINE_DEFAULT_OBJECT_INITIALIZER_CONSTRUCTOR_CALL(UUnrealAgentBlueprintLibrary) \
	NO_API virtual ~UUnrealAgentBlueprintLibrary();


#define FID_AudioVidoLivingCity_Plugins_UnrealAgentBridge_Source_UnrealAgentBridge_Public_UnrealAgentBlueprintLibrary_h_9_PROLOG
#define FID_AudioVidoLivingCity_Plugins_UnrealAgentBridge_Source_UnrealAgentBridge_Public_UnrealAgentBlueprintLibrary_h_13_GENERATED_BODY \
PRAGMA_DISABLE_DEPRECATION_WARNINGS \
public: \
	FID_AudioVidoLivingCity_Plugins_UnrealAgentBridge_Source_UnrealAgentBridge_Public_UnrealAgentBlueprintLibrary_h_13_RPC_WRAPPERS_NO_PURE_DECLS \
	FID_AudioVidoLivingCity_Plugins_UnrealAgentBridge_Source_UnrealAgentBridge_Public_UnrealAgentBlueprintLibrary_h_13_INCLASS_NO_PURE_DECLS \
	FID_AudioVidoLivingCity_Plugins_UnrealAgentBridge_Source_UnrealAgentBridge_Public_UnrealAgentBlueprintLibrary_h_13_ENHANCED_CONSTRUCTORS \
private: \
PRAGMA_ENABLE_DEPRECATION_WARNINGS


class UUnrealAgentBlueprintLibrary;

// ********** End Class UUnrealAgentBlueprintLibrary ***********************************************

#undef CURRENT_FILE_ID
#define CURRENT_FILE_ID FID_AudioVidoLivingCity_Plugins_UnrealAgentBridge_Source_UnrealAgentBridge_Public_UnrealAgentBlueprintLibrary_h

PRAGMA_ENABLE_DEPRECATION_WARNINGS
