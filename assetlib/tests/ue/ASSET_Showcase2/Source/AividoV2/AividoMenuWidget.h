// Aivido V2 — ESC menu (native UMG).

#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "AividoMenuWidget.generated.h"

class AAividoGameMode;
class UButton;
class UTextBlock;
class UBorder;

/** Production pause/menu overlay built entirely with native C++ UMG. */
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
