// Aivido V2 — the master director: primary conversation character.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "AividoDirector.generated.h"

class USkeletalMeshComponent;
class USkeletalMesh;
class UAnimationAsset;
class UBillboardComponent;
class UCameraComponent;

/**
 * Primary conversational agent of Aivido HQ.
 *
 * Wears the Master/Business_Male_01 RocketBox mesh + its idle AnimSequence
 * when found in /Game/AividoHQ/Characters/Master/. Visual conversation state
 * (listening / thinking / speaking) is represented by the interaction ring
 * billboard color + HUD, driven by real chat round-trip state.
 *
 * Also owns the conversation camera: when the player starts a conversation
 * the GameMode asks the director to face the player and place the framing
 * camera (over-the-shoulder toward the director), then blends the view
 * target to this actor.
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

	/** Turn the director toward the player (conversation framing). */
	void FacePlayer(AActor* PlayerPawn);

	/**
	 * Place the conversation camera for an over-the-shoulder framing of the
	 * director, standing just behind the player.
	 */
	void PlaceConversationCamera(AActor* PlayerPawn);

	/** Conversation framing camera (view target while the panel is open). */
	UPROPERTY(VisibleAnywhere, Category = "Aivido|Camera")
	UCameraComponent* ConversationCamera;

	UPROPERTY(VisibleAnywhere, Category = "Aivido")
	USkeletalMeshComponent* Mesh;

private:
	UPROPERTY()
	TWeakObjectPtr<UMaterialInstanceDynamic> RingMaterial;
};