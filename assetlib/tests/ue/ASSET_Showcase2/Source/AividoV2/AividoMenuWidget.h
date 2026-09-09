// Aivido V2 — ESC menu (native UMG).

#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "AividoMenuWidget.generated.h"

class AAividoGameMode;
class UButton;
class UTextBlock;
class UBorder;
class UVerticalBox;

/**
 * Menu overlay shared by the boot start screen and the ESC pause menu:
 *  - main menu mode: Start Session / Quit Session (first button focused)
 *  - pause mode: Resume / Refresh Worker States / Quit Session
 *  - full keyboard navigation (arrows + Tab + Enter/Space) and mouse clicks
 *  - deterministic button feedback (hover / focus / pressed brushes)
 *  - every button is wired to a real action — no dead production buttons
 */
UCLASS()
class AIVIDOV2_API UAividoMenuWidget : public UUserWidget
{
	GENERATED_BODY()

public:
	virtual TSharedRef<SWidget> RebuildWidget() override;
	virtual void NativeDestruct() override;

	void NotifyOpened();

	/** Switch between the boot start screen and the ESC pause overlay. */
	void SetMainMenuMode(bool bMainMenu);

protected:
	UFUNCTION()
	void OnResumeClicked();

	UFUNCTION()
	void OnWorkerStatesClicked();

	UFUNCTION()
	void OnQuitClicked();

	void OnStatesChanged(const TArray<FString>& StateLines);

private:
	UButton* MakeMenuButton(const FString& Label);
	void ApplyNavigation();

	TObjectPtr<UBorder> PanelBorder;
	TObjectPtr<UTextBlock> TitleText;
	TObjectPtr<UTextBlock> ResumeLabel;
	TObjectPtr<UButton> ResumeButton;
	TObjectPtr<UButton> WorkerStatesButton;
	TObjectPtr<UButton> QuitButton;
	TObjectPtr<UTextBlock> StatusText;

	FTimerHandle MenuGeoLogHandle;

	bool bMainMenuMode = false;

	TWeakObjectPtr<AAividoGameMode> GameMode;
};