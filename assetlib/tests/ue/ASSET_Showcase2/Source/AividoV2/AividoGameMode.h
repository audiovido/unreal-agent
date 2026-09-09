// Aivido V2 — production GameMode: boots the playable HQ experience.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "AividoGameMode.generated.h"

class AAividoCharacter;
class UAividoHUD;
class AAividoDirector;
class AAividoWorkerDirector;
class UUserWidget;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnMenuStateChanged, bool, bMenuOpen);

/**
 * Deterministic UI state of the whole experience. Every input-mode, cursor
 * and camera transition is driven from this single state (see SetUIState).
 */
UENUM(BlueprintType)
enum class EAividoUIState : uint8
{
	Gameplay    UMETA(DisplayName = "Gameplay"),
	MainMenu    UMETA(DisplayName = "Main Menu"),
	Pause       UMETA(DisplayName = "Pause"),
	Conversation UMETA(DisplayName = "Conversation")
};

/** Camera framing mode. Gameplay = third-person follow; ConversationFocus = director framing. */
UENUM(BlueprintType)
enum class EAividoCameraMode : uint8
{
	Gameplay         UMETA(DisplayName = "Gameplay"),
	ConversationFocus UMETA(DisplayName = "Conversation Focus")
};

/**
 * Aivido HQ GameMode.
 *
 * Owns the production flow AND the central UI/camera state machine:
 *  - spawns the playable character at the PlayerStart
 *  - creates the native UMG HUD (state banner + interaction prompt)
 *  - shows the main menu at boot (Start Session / Quit)
 *  - handles [E] interaction with the master director (opens conversation)
 *  - owns the conversation panel (open/close, submit, real backend reply)
 *  - blends to the director conversation camera on open and back to the
 *    pawn on close
 *  - ESC steps down: conversation -> pause/menu -> gameplay
 *  - every input-mode/cursor/movement-lock change goes through SetUIState
 */
UCLASS()
class AIVIDOV2_API AAividoGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	AAividoGameMode();

	/** Fired when the ESC menu opens/closes (HUD listens). */
	UPROPERTY(BlueprintAssignable, Category = "Aivido|Menu")
	FOnMenuStateChanged OnMenuStateChanged;

	/** Current UI state (single source of truth for input/camera mode). */
	UFUNCTION(BlueprintPure, Category = "Aivido|State")
	EAividoUIState GetUIState() const { return UIState; }

	/** Current camera framing mode. */
	UFUNCTION(BlueprintPure, Category = "Aivido|State")
	EAividoCameraMode GetCameraMode() const { return CameraMode; }

	/** Handle [E]: open conversation with the focused actor. */
	void HandleInteract(AActor* InstigatorActor, AActor* Target);

	/** ESC handler: steps down conversation -> menu -> gameplay. */
	UFUNCTION(BlueprintCallable, Category = "Aivido|Menu")
	void ToggleMenu();
	UFUNCTION(BlueprintCallable, Category = "Aivido|Menu")
	bool IsMenuOpen() const
	{
		return UIState == EAividoUIState::MainMenu || UIState == EAividoUIState::Pause;
	}
	UFUNCTION(BlueprintPure, Category = "Aivido|Menu")
	bool IsMainMenuOpen() const { return UIState == EAividoUIState::MainMenu; }

	/** Boot start screen (shown by BeginPlay). */
	UFUNCTION(BlueprintCallable, Category = "Aivido|Menu")
	void ShowMainMenu();

	/** Close the menu overlay (Resume / Start Session) and return to gameplay. */
	UFUNCTION(BlueprintCallable, Category = "Aivido|Menu")
	void CloseMenu();

	UFUNCTION(BlueprintCallable, Category = "Aivido|Conversation")
	void OpenConversation();

	UFUNCTION(BlueprintCallable, Category = "Aivido|Conversation")
	void CloseConversation();

	UFUNCTION(BlueprintCallable, Category = "Aivido|Conversation")
	bool IsConversationOpen() const { return UIState == EAividoUIState::Conversation; }

	/** Submit a chat line to the real backend; reply arrives via OnDirectorReply. */
	UFUNCTION(BlueprintCallable, Category = "Aivido|Chat")
	void SubmitChatLine(const FString& Message);

	/** Ask the backend for the live worker roster/state (async, result via OnWorkerStates). */
	UFUNCTION(BlueprintCallable, Category = "Aivido|Workers")
	void RequestWorkerStates();

	/** Director reply payload from the last completed chat round-trip. */
	UFUNCTION(BlueprintPure, Category = "Aivido|Chat")
	FString GetLastReply() const { return LastReply; }

	/** True while a chat round-trip is in flight. */
	UFUNCTION(BlueprintPure, Category = "Aivido|Chat")
	bool IsWaitingForReply() const { return bWaitingReply; }

	/** Fired when the director's reply text changes. */
	DECLARE_MULTICAST_DELEGATE_OneParam(FOnReply, const FString& /*Reply*/);
	FOnReply OnReplyChanged;

	/** Fired when worker states arrive from the backend. */
	DECLARE_MULTICAST_DELEGATE_OneParam(FOnStates, const TArray<FString>& /*StateLines*/);
	FOnStates OnWorkerStatesChanged;

	/** Fired when the conversation panel opens/closes. */
	DECLARE_MULTICAST_DELEGATE_OneParam(FOnConversation, bool /*bOpen*/);
	FOnConversation OnConversationChanged;

	/** Path of the conversation widget class (native class; set in constructor). */
	TSubclassOf<UUserWidget> GetConversationWidgetClass() const { return ConversationWidgetClass; }
	TSubclassOf<UUserWidget> GetMenuWidgetClass() const { return MenuWidgetClass; }

protected:
	virtual void BeginPlay() override;

	UPROPERTY(EditDefaultsOnly, Category = "Aivido|Classes")
	TSubclassOf<AAividoCharacter> PlayerCharacterClass;

	UPROPERTY(EditDefaultsOnly, Category = "Aivido|Classes")
	TSubclassOf<AAividoDirector> DirectorClass;

	UPROPERTY(EditDefaultsOnly, Category = "Aivido|Classes")
	TSubclassOf<AAividoWorkerDirector> WorkerDirectorClass;

	UPROPERTY(EditDefaultsOnly, Category = "Aivido|Classes")
	TSubclassOf<UUserWidget> ConversationWidgetClass;

	UPROPERTY(EditDefaultsOnly, Category = "Aivido|Classes")
	TSubclassOf<UUserWidget> MenuWidgetClass;

private:
	void OpenPauseMenu();

	/** The ONLY place input mode / cursor / movement locks / camera transitions are applied. */
	void SetUIState(EAividoUIState NewState);

	UPROPERTY()
	TObjectPtr<AAividoDirector> Director;

	UPROPERTY()
	TObjectPtr<AAividoWorkerDirector> WorkerDirector;

	UPROPERTY()
	TObjectPtr<UUserWidget> ConversationWidget;

	UPROPERTY()
	TObjectPtr<UUserWidget> MenuWidget;

	EAividoUIState UIState = EAividoUIState::Gameplay;
	EAividoCameraMode CameraMode = EAividoCameraMode::Gameplay;

	/** Blend duration for camera transitions (conversation open/close). */
	float CameraBlendTime = 0.6f;

	bool bWaitingReply = false;
	FString LastReply;

	/** Chat endpoint of the Aivido backend (overridable per-project in DefaultGame.ini). */
	UPROPERTY(Config, EditDefaultsOnly, Category = "Aivido|Backend")
	FString ChatUrl = TEXT("http://127.0.0.1:8765/api/chat");
};