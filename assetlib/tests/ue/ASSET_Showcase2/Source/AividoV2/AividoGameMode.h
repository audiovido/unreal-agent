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
 * Aivido HQ GameMode.
 *
 * Owns the production flow:
 *  - spawns the playable character at the PlayerStart
 *  - creates the native UMG HUD (state banner + interaction prompt)
 *  - handles [E] interaction with the master director (opens conversation)
 *  - owns the conversation panel (open/close, submit, real backend reply)
 *  - drives background worker runtime states via AAividoWorkerDirector
 *  - ESC toggles the pause/menu overlay (GameOnly <-> GameAndUI input)
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

	/** Handle [E]: open conversation with the focused actor. */
	void HandleInteract(AActor* InstigatorActor, AActor* Target);

	/** ESC menu open/close. */
	UFUNCTION(BlueprintCallable, Category = "Aivido|Menu")
	void ToggleMenu();
	UFUNCTION(BlueprintCallable, Category = "Aivido|Menu")
	bool IsMenuOpen() const { return bMenuOpen; }

	UFUNCTION(BlueprintCallable, Category = "Aivido|Conversation")
	void OpenConversation();

	UFUNCTION(BlueprintCallable, Category = "Aivido|Conversation")
	void CloseConversation();

	UFUNCTION(BlueprintCallable, Category = "Aivido|Conversation")
	bool IsConversationOpen() const { return bConversationOpen; }

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
	void ApplyInputMode(bool bGameAndUI);

	UPROPERTY()
	TObjectPtr<AAividoDirector> Director;

	UPROPERTY()
	TObjectPtr<AAividoWorkerDirector> WorkerDirector;

	UPROPERTY()
	TObjectPtr<UUserWidget> ConversationWidget;

	UPROPERTY()
	TObjectPtr<UUserWidget> MenuWidget;

	bool bConversationOpen = false;
	bool bMenuOpen = false;
	bool bWaitingReply = false;
	FString LastReply;
};
