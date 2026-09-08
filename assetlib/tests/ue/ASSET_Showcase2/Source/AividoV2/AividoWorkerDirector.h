// Aivido V2 — background worker behavior driven by REAL runtime state.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "AividoWorkerDirector.generated.h"

class USkeletalMeshComponent;

/**
 * Maps each background worker to its real runtime state and applies the
 * matching visible behavior:
 *
 *   idle    -> frozen pose at station (rest, no fake work motion)
 *   working -> role-appropriate looped work animation (avatar _Anim sequence)
 *   error   -> standing still + flagged in HUD banner
 *
 * States come from the backend /api/aivido/agents endpoint when reachable
 * (real roster), otherwise every worker is treated as idle (truthful default:
 * we never invent work activity that is not happening).
 */
UCLASS()
class AIVIDOV2_API AAividoWorkerDirector : public AActor
{
	GENERATED_BODY()

public:
	AAividoWorkerDirector();

	/** Query the backend for the worker roster + states (async HTTP). */
	void RequestStates();

	/** Apply a state map (agent label -> state token) to placed workers. */
	void ApplyStates(const TMap<FString, FString>& AgentStates);

	/** Lines for the HUD banner describing current worker activity. */
	const TArray<FString>& GetStateLines() const { return StateLines; }

protected:
	virtual void BeginPlay() override;

private:
	struct FWorker
	{
		TWeakObjectPtr<AActor> Actor;
		FString AgentId;
		FString State;
	};

	void CollectWorkers();
	void ApplyToWorker(FWorker& W, const FString& NewState);
	static FString NormalizeLabel(const FString& Raw);

	// C++-only runtime state (not reflected): workers + their current states.
	TArray<FWorker> Workers;

	TArray<FString> StateLines;

	FTimerHandle PollTimer;
};
