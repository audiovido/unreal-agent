// Aivido V2 — the master director: primary conversation character.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "AividoDirector.generated.h"

class USkeletalMeshComponent;
class USkeletalMesh;
class UAnimationAsset;
class UBillboardComponent;

/**
 * Primary conversational agent of Aivido HQ.
 *
 * Wears the Master/Business_Male_01 RocketBox mesh + its idle AnimSequence
 * when found in /Game/AividoHQ/Characters/Master/. Visual conversation state
 * (listening / thinking / speaking) is represented by the interaction ring
 * billboard color + HUD, driven by real chat round-trip state.
 */
UCLASS()
class AIVIDOV2_API AAividoDirector : public AActor
{
	GENERATED_BODY()

public:
	AAividoDirector();

	/** Visual/audio reaction when the player starts a conversation. */
	void Focus();

	/** Set conversation state: 0 idle, 1 listening, 2 thinking, 3 speaking. */
	void SetConversationState(int32 State);

	UPROPERTY(VisibleAnywhere, Category = "Aivido")
	USkeletalMeshComponent* Mesh;

private:
	UPROPERTY()
	TWeakObjectPtr<UMaterialInstanceDynamic> RingMaterial;
};
