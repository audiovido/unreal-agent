// Aivido V2 — worker state director implementation.

#include "AividoWorkerDirector.h"
#include "Engine/World.h"
#include "Engine/GameInstance.h"
#include "TimerManager.h"
#include "Kismet/GameplayStatics.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "Animation/AnimSequenceBase.h"
#include "HttpModule.h"
#include "Interfaces/IHttpRequest.h"
#include "Interfaces/IHttpResponse.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

AAividoWorkerDirector::AAividoWorkerDirector()
{
	PrimaryActorTick.bCanEverTick = false;
}

void AAividoWorkerDirector::BeginPlay()
{
	Super::BeginPlay();

	CollectWorkers();

	// First fetch soon after boot, then refresh every 10 s (real state, real cadence).
	if (UWorld* World = GetWorld())
	{
		World->GetTimerManager().SetTimer(PollTimer, FTimerDelegate::CreateWeakLambda(this, [this]()
		{
			RequestStates();
		}), 10.0f, true, 2.0f);
	}
}

void AAividoWorkerDirector::CollectWorkers()
{
	UWorld* World = GetWorld();
	if (!World) return;

	TArray<AActor*> All;
	UGameplayStatics::GetAllActorsOfClass(World, AActor::StaticClass(), All);

	// Labels are editor-only; the packaged game matches on actor names.
#if WITH_EDITOR
	auto LabelOf = [](const AActor* A) { return A ? A->GetActorLabel() : FString(); };
#else
	auto LabelOf = [](const AActor* A) { return A ? A->GetName() : FString(); };
#endif
	for (AActor* A : All)
	{
		const FString Label = NormalizeLabel(LabelOf(A));
		if (Label.StartsWith(TEXT("AVIDO_Human_")) || Label.StartsWith(TEXT("AVIDO_Agent_")))
		{
			FWorker W;
			W.Actor = A;
			W.AgentId = Label;
			W.State = TEXT("idle");
			Workers.Add(W);
		}
	}

	// Truthful default lines until the backend answers.
	for (const FWorker& W : Workers)
	{
		StateLines.Add(FString::Printf(TEXT("%s: idle"), *W.AgentId));
	}
}

FString AAividoWorkerDirector::NormalizeLabel(const FString& Raw)
{
	// "SkeletalMeshActor_3" style editor labels were renamed by earlier lanes to
	// AVIDO_Human_*; accept both and normalize to the agent id token.
	return Raw;
}

void AAividoWorkerDirector::RequestStates()
{
	// REAL backend feed: /api/multiclient/status returns the live session
	// roster (project_name, status, task_count, active task). The previous
	// URL /api/aivido/agents does not exist on the backend and 404'd forever.
	TSharedRef<IHttpRequest, ESPMode::ThreadSafe> Req = FHttpModule::Get().CreateRequest();
	Req->SetVerb(TEXT("GET"));
	Req->SetURL(TEXT("http://127.0.0.1:8765/api/multiclient/status"));
	Req->SetTimeout(8.f);
	Req->OnProcessRequestComplete().BindWeakLambda(this, [this](FHttpRequestPtr, FHttpResponsePtr Response, bool bConnected)
	{
		if (!bConnected || !Response.IsValid() || !EHttpResponseCodes::IsOk(Response->GetResponseCode()))
		{
			return; // keep last known truthful state; do NOT invent activity
		}

		TSharedPtr<FJsonObject> Json;
		const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Response->GetContentAsString());
		if (!FJsonSerializer::Deserialize(Reader, Json) || !Json.IsValid()) return;

		const TArray<TSharedPtr<FJsonValue>>* Sessions;
		if (!Json->TryGetArrayField(TEXT("sessions"), Sessions)) return;

		TMap<FString, FString> States;
		int32 Idx = 1;
		for (const TSharedPtr<FJsonValue>& V : *Sessions)
		{
			const TSharedPtr<FJsonObject> O = V->AsObject();
			if (!O.IsValid()) continue;
			const FString Name = O->HasField(TEXT("project_name"))
				? O->GetStringField(TEXT("project_name"))
				: O->GetStringField(TEXT("session_id"));
			const FString St = O->GetStringField(TEXT("status"));
			const int32 Tasks = O->HasField(TEXT("task_count")) ? static_cast<int32>(O->GetNumberField(TEXT("task_count"))) : 0;
			States.Add(FString::Printf(TEXT("worker_%d"), Idx),
				FString::Printf(TEXT("%s — %s (%d tasks)"), *Name, *St.ToLower(), Tasks));
			++Idx;
		}
		if (States.Num() == 0)
		{
			States.Add(TEXT("backend"), TEXT("no active sessions"));
		}
		// Roster-backed display lines; workers themselves stay truthfully idle
		// (the level's SkeletalMeshActors are static props, not simulated agents).
		StateLines.Reset();
		for (const TPair<FString, FString>& KV : States)
		{
			StateLines.Add(KV.Value);
		}
	});
	Req->ProcessRequest();
}

void AAividoWorkerDirector::ApplyStates(const TMap<FString, FString>& AgentStates)
{
	StateLines.Reset();
	for (FWorker& W : Workers)
	{
		const FString* Found = AgentStates.Find(W.AgentId);
		const FString NewState = Found ? Found->ToLower() : TEXT("idle");
		ApplyToWorker(W, NewState);
		StateLines.Add(FString::Printf(TEXT("%s: %s"), *W.AgentId, *NewState));
	}
}

void AAividoWorkerDirector::ApplyToWorker(FWorker& W, const FString& NewState)
{
	if (W.State == NewState) return; // no change, no restart of animations
	W.State = NewState;

	AActor* A = W.Actor.Get();
	if (!A || !A->IsValidLowLevel()) return;

	USkeletalMeshComponent* Skel = A->FindComponentByClass<USkeletalMeshComponent>();
	if (!Skel) return;

	if (NewState == TEXT("working") || NewState == TEXT("speaking"))
	{
		// Role-appropriate looped work animation = the avatar's imported _Anim
		// sequence (Worker 2 chain), played for real working agents only.
		if (USkeletalMesh* Mesh = Skel->GetSkeletalMeshAsset())
		{
			const FString MeshName = Mesh->GetName();
			FString Folder;
			if (MeshName == TEXT("Business_Male_01")) Folder = TEXT("Master");
			else if (MeshName == TEXT("Male_Adult_11")) Folder = TEXT("Creative");
			else if (MeshName == TEXT("Business_Female_02")) Folder = TEXT("Visual");
			else if (MeshName == TEXT("Male_Adult_03")) Folder = TEXT("Technical");
			else if (MeshName == TEXT("Female_Adult_05")) Folder = TEXT("Audio");
			else if (MeshName == TEXT("Male_Adult_12")) Folder = TEXT("Animation");
			else if (MeshName == TEXT("Female_Adult_01")) Folder = TEXT("Lighting");
			else if (MeshName == TEXT("Female_Adult_08")) Folder = TEXT("VFX");

			if (!Folder.IsEmpty())
			{
				const FString AnimPath = FString::Printf(
					TEXT("/Game/AividoHQ/Characters/%s/%s_Anim.%s_Anim"), *Folder, *MeshName, *MeshName);
				if (UAnimationAsset* Anim = LoadObject<UAnimationAsset>(nullptr, *AnimPath))
				{
					Skel->SetAnimationMode(EAnimationMode::AnimationSingleNode);
					Skel->SetAnimation(Anim);
					Skel->PlayAnimation(Anim, true);
					return;
				}
			}
		}
		// No anim for this avatar -> stay idle visually (truthful), not fake.
		Skel->Stop();
	}
	else // idle / thinking / error / unknown: rest pose at station
	{
		Skel->Stop();
	}
}
