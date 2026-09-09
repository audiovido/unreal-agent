// Aivido V2 — master director implementation.

#include "AividoDirector.h"
#include "Components/SkeletalMeshComponent.h"
#include "Camera/CameraComponent.h"
#include "Engine/SkeletalMesh.h"
#include "Animation/AnimSequenceBase.h"
#include "UObject/Package.h"

AAividoDirector::AAividoDirector()
{
	PrimaryActorTick.bCanEverTick = false;

	Mesh = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Mesh"));
	RootComponent = Mesh;

	// Conversation framing camera. Its transform is placed per-conversation
	// (PlaceConversationCamera); same FOV as the gameplay follow camera so
	// the blend between the two is seamless.
	ConversationCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("ConversationCamera"));
	ConversationCamera->SetupAttachment(RootComponent);
	ConversationCamera->SetFieldOfView(65.f);

	// Resolve the Master RocketBox avatar (imported by Worker 2) at runtime so
	// the actor works identically in editor PIE and in a packaged build.
	static const TCHAR* MeshCandidates[] = {
		TEXT("/Game/AividoHQ/Characters/Master/Business_Male_01.Business_Male_01"),
		TEXT("/Game/AividoHQ/Characters/Master/Business_Male_01"),
	};
	for (const TCHAR* Path : MeshCandidates)
	{
		if (USkeletalMesh* Found = LoadObject<USkeletalMesh>(nullptr, Path))
		{
			Mesh->SetSkeletalMesh(Found);
			break;
		}
	}

	// Idle animation from the avatar import (same folder, _Anim suffix).
	if (USkeletalMesh* Current = Mesh->GetSkeletalMeshAsset())
	{
		const FString MeshName = Current->GetName();
		const FString AnimPath =
			FString::Printf(TEXT("/Game/AividoHQ/Characters/Master/%s_Anim.%s_Anim"), *MeshName, *MeshName);
		if (UAnimationAsset* Anim = LoadObject<UAnimationAsset>(nullptr, *AnimPath))
		{
			Mesh->SetAnimationMode(EAnimationMode::AnimationSingleNode);
			Mesh->SetAnimation(Anim);
			Mesh->PlayAnimation(Anim, true); // looped idle
		}
	}

	// Ship with collisions so the interaction trace and blocking work.
	Mesh->SetCollisionEnabled(ECollisionEnabled::QueryOnly);
	Mesh->SetCollisionResponseToAllChannels(ECR_Ignore);
	Mesh->SetCollisionResponseToChannel(ECC_Visibility, ECR_Block);
	Mesh->SetCollisionResponseToChannel(ECC_WorldStatic, ECR_Block);
	Mesh->SetGenerateOverlapEvents(false);
}

void AAividoDirector::Focus()
{
	// Real state change hooks land with the conversation flow; the physical
	// turn toward the player is done by FacePlayer() when the conversation
	// camera is set up. (Kept minimal and non-faking: no canned "speaking"
	// animation.)
}

void AAividoDirector::SetConversationState(int32 State)
{
	// Placeholder for MIC-driven ring color; state is surfaced truthfully in
	// the HUD banner instead of pretending the mesh itself emotes.
	(void)State;
}

void AAividoDirector::FacePlayer(AActor* PlayerPawn)
{
	if (!PlayerPawn) return;

	FVector ToPlayer = PlayerPawn->GetActorLocation() - GetActorLocation();
	ToPlayer.Z = 0.f;
	if (ToPlayer.SizeSquared() > 1.f)
	{
		SetActorRotation(ToPlayer.Rotation());
	}
}

void AAividoDirector::PlaceConversationCamera(AActor* PlayerPawn)
{
	if (!ConversationCamera || !PlayerPawn) return;

	// Aim at the director's head (mesh root Z + face offset).
	const FVector FacePos = GetActorLocation() + FVector(0.f, 0.f, 150.f);

	FVector ToPlayer = PlayerPawn->GetActorLocation() - FacePos;
	ToPlayer.Z = 0.f;
	if (ToPlayer.SizeSquared() < 1.f)
	{
		ToPlayer = FVector(0.f, 1.f, 0.f);
	}
	ToPlayer.Normalize();

	// Over-the-shoulder framing: stand the camera just behind the player
	// (beyond them, away from the director) at head height, aiming at the
	// director's face.
	const FVector CamPos =
		PlayerPawn->GetActorLocation() + ToPlayer * 150.f + FVector(0.f, 0.f, 20.f);
	ConversationCamera->SetWorldLocation(CamPos);
	ConversationCamera->SetWorldRotation((FacePos - CamPos).Rotation());
}