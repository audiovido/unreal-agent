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
 * Pause/menu overlay opened with ESC:
 *  - Resume (closes the menu)
 *  - Worker States (requests fresh roster; result shows in HUD banner)
 *  - Quit Session (exits the game)
 * Every button is wired to a real action — no dead production buttons.
 */
UCLASS()
class AIVIDOV2_API UAividoMenuWidget : public UUserWidget
{
	GENERATED_BODY()

public:
	virtual TSharedRef<SWidget> RebuildWidget() override;
	virtual void NativeDestruct() override;

	void NotifyOpened();

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

	TObjectPtr<UBorder> PanelBorder;
	TObjectPtr<UButton> ResumeButton;
	TObjectPtr<UButton> WorkerStatesButton;
	TObjectPtr<UButton> QuitButton;
	TObjectPtr<UTextBlock> StatusText;

	TWeakObjectPtr<AAividoGameMode> GameMode;
};
