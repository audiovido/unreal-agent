// Aivido V2 — native UMG HUD (state banner + interaction prompt).

#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "AividoHUD.generated.h"

class AAividoGameMode;
class UTextBlock;
class UBorder;

/**
 * Production HUD, pure native UMG (no editor-authored WBP dependency):
 *  - top-left: AIVIDO HQ banner + director link state + worker activity lines
 *  - bottom-center: interaction prompt when the director is in focus range
 */
UCLASS()
class AIVIDOV2_API UAividoHUD : public UUserWidget
{
	GENERATED_BODY()

public:
	virtual void NativeConstruct() override;
	virtual void NativeDestruct() override;
	virtual void NativeTick(const FGeometry& MyGeometry, float InDeltaTime) override;

	void BindGameMode(AAividoGameMode* InGameMode);

private:
	void RebuildBanner(const TArray<FString>& StateLines);
	void RefreshPrompt();

	TObjectPtr<UTextBlock> TitleText;
	TObjectPtr<UTextBlock> LinkText;
	TObjectPtr<UTextBlock> WorkersText;
	TObjectPtr<UTextBlock> PromptText;

	TWeakObjectPtr<AAividoGameMode> GameMode;
	FString LastWorkersJoined;
	float BannerRefreshTimer = 0.f;
};
