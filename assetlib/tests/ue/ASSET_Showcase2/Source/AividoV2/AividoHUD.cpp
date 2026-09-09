// Aivido V2 — native UMG HUD implementation (widget tree built in C++).

#include "AividoHUD.h"
#include "Blueprint/WidgetTree.h"
#include "Misc/Parse.h"
#include "Misc/CommandLine.h"
#include "AividoGameMode.h"
#include "AividoCharacter.h"
#include "AividoWorkerDirector.h"
#include "Components/TextBlock.h"
#include "Components/Border.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/VerticalBox.h"
#include "Components/VerticalBoxSlot.h"
#include "Styling/CoreStyle.h"
#include "Styling/SlateColor.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"

namespace AividoHUDStyle
{
	const FLinearColor Panel(0.008f, 0.016f, 0.032f, 0.78f);
	const FLinearColor PanelAccent(0.10f, 0.42f, 0.70f, 0.75f);
	const FLinearColor Cyan(0.55f, 0.84f, 1.0f, 1.0f);
	const FLinearColor Muted(0.64f, 0.72f, 0.80f, 1.0f);
	const FLinearColor Body(0.82f, 0.88f, 0.94f, 1.0f);
	const FLinearColor Gold(1.0f, 0.78f, 0.38f, 1.0f);
}

TSharedRef<SWidget> UAividoHUD::RebuildWidget()
{
	UE_LOG(LogTemp, Log, TEXT("AIVIDO_HUD: rebuild start"));
	if (!FParse::Param(FCommandLine::Get(), TEXT("AividoNoHUD")))
	{
		UCanvasPanel* Canvas = WidgetTree->ConstructWidget<UCanvasPanel>();
		WidgetTree->RootWidget = Canvas;

		// Compact status module.  It stays in the safe top-left corner, away
		// from the crosshair and the usual gameplay focus area.
		UBorder* BannerBorder = WidgetTree->ConstructWidget<UBorder>();
		BannerBorder->SetPadding(FMargin(16.f, 13.f, 16.f, 14.f));
		BannerBorder->SetBrushColor(AividoHUDStyle::Panel);

		TitleText = WidgetTree->ConstructWidget<UTextBlock>();
		TitleText->SetText(FText::FromString(TEXT("AIVIDO  /  HQ OPERATIONS")));
		TitleText->SetColorAndOpacity(FSlateColor(AividoHUDStyle::Cyan));
		TitleText->SetFont(FCoreStyle::GetDefaultFontStyle("Bold", 17));

		LinkText = WidgetTree->ConstructWidget<UTextBlock>();
		LinkText->SetText(FText::FromString(TEXT("DIRECTOR LINK  ·  READY")));
		LinkText->SetColorAndOpacity(FSlateColor(AividoHUDStyle::Muted));
		LinkText->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 11));

		WorkersText = WidgetTree->ConstructWidget<UTextBlock>();
		WorkersText->SetText(FText::FromString(TEXT("WORKER NETWORK  ·  STANDBY")));
		WorkersText->SetColorAndOpacity(FSlateColor(AividoHUDStyle::Body));
		WorkersText->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 11));
		WorkersText->SetAutoWrapText(true);
		WorkersText->SetWrapTextAt(380.f);

		UVerticalBox* Left = WidgetTree->ConstructWidget<UVerticalBox>();
		Left->AddChildToVerticalBox(TitleText)->SetPadding(FMargin(0, 0, 0, 4));
		Left->AddChildToVerticalBox(LinkText)->SetPadding(FMargin(0, 0, 0, 7));
		Left->AddChildToVerticalBox(WorkersText);
		BannerBorder->SetContent(Left);

		if (UCanvasPanelSlot* BS = Canvas->AddChildToCanvas(BannerBorder))
		{
			BS->SetAnchors(FAnchors(0.f, 0.f, 0.f, 0.f));
			BS->SetAlignment(FVector2D::ZeroVector);
			BS->SetPosition(FVector2D(24.f, 24.f));
			BS->SetSize(FVector2D(420.f, 148.f));
			BS->SetAutoSize(false);
			BS->SetZOrder(10);
		}

		// The prompt is its own hit-test-invisible panel and never intercepts
		// movement, mouse-look, or interaction input.
		PromptBorder = WidgetTree->ConstructWidget<UBorder>();
		PromptBorder->SetPadding(FMargin(20.f, 10.f, 20.f, 11.f));
		PromptBorder->SetBrushColor(FLinearColor(0.015f, 0.025f, 0.045f, 0.88f));
		PromptText = WidgetTree->ConstructWidget<UTextBlock>();
		PromptText->SetColorAndOpacity(FSlateColor(AividoHUDStyle::Gold));
		PromptText->SetFont(FCoreStyle::GetDefaultFontStyle("Bold", 15));
		PromptText->SetJustification(ETextJustify::Center);
		PromptBorder->SetContent(PromptText);
		PromptBorder->SetVisibility(ESlateVisibility::Collapsed);

		if (UCanvasPanelSlot* PS = Canvas->AddChildToCanvas(PromptBorder))
		{
			PS->SetAnchors(FAnchors(0.5f, 1.f, 0.5f, 1.f));
			PS->SetAlignment(FVector2D(0.5f, 1.f));
			PS->SetPosition(FVector2D(0.f, -36.f));
			PS->SetSize(FVector2D(410.f, 56.f));
			PS->SetAutoSize(false);
			PS->SetZOrder(11);
		}

		UE_LOG(LogTemp, Log, TEXT("AIVIDO_HUD: tree built, taking root"));
	}
	return Super::RebuildWidget();
}

void UAividoHUD::NativeDestruct()
{
	if (AAividoGameMode* GM = GameMode.Get())
	{
		GM->OnWorkerStatesChanged.RemoveAll(this);
	}
	Super::NativeDestruct();
}

void UAividoHUD::BindGameMode(AAividoGameMode* InGameMode)
{
	GameMode = InGameMode;
	if (InGameMode)
	{
		InGameMode->OnWorkerStatesChanged.RemoveAll(this);
		InGameMode->OnWorkerStatesChanged.AddUObject(this, &UAividoHUD::RebuildBanner);
	}
}

void UAividoHUD::RebuildBanner(const TArray<FString>& StateLines)
{
	AAividoGameMode* GM = GameMode.Get();
	UWorld* World = GetWorld();
	if (!GM || !World || !WorkersText) return;

	const FString WorkersJoined = FString::Join(StateLines, TEXT("\n"));
	if (!WorkersJoined.Equals(LastWorkersJoined))
	{
		LastWorkersJoined = WorkersJoined;
		WorkersText->SetText(FText::FromString(
			WorkersJoined.IsEmpty() ? TEXT("WORKER NETWORK  ·  STANDBY") : WorkersJoined));
	}

	const bool bWaiting = GM->IsWaitingForReply();
	LinkText->SetText(FText::FromString(bWaiting
		? TEXT("DIRECTOR LINK  ·  WAITING FOR REPLY")
		: TEXT("DIRECTOR LINK  ·  READY   /   [E] TALK")));
}

void UAividoHUD::RefreshPrompt()
{
	UWorld* World = GetWorld();
	if (!World || !PromptText || !PromptBorder) return;

	APlayerController* PC = World->GetFirstPlayerController();
	AAividoCharacter* Ch = PC ? Cast<AAividoCharacter>(PC->GetPawn()) : nullptr;
	if (!Ch || Ch->CurrentTargetName.IsEmpty())
	{
		PromptBorder->SetVisibility(ESlateVisibility::Collapsed);
	}
	else
	{
		PromptText->SetText(FText::FromString(
			FString::Printf(TEXT("[ E ]   CONNECT TO  %s"), *Ch->CurrentTargetName.ToUpper())));
		PromptBorder->SetVisibility(ESlateVisibility::HitTestInvisible);
	}
}

void UAividoHUD::NativeTick(const FGeometry& MyGeometry, float InDeltaTime)
{
	Super::NativeTick(MyGeometry, InDeltaTime);
	RefreshPrompt();

	BannerRefreshTimer += InDeltaTime;
	if (BannerRefreshTimer >= 0.5f)
	{
		BannerRefreshTimer = 0.f;
		UWorld* World = GetWorld();
		TArray<AActor*> Found;
		UGameplayStatics::GetAllActorsOfClass(World, AAividoWorkerDirector::StaticClass(), Found);
		if (AAividoWorkerDirector* WD = Found.Num() ? Cast<AAividoWorkerDirector>(Found[0]) : nullptr)
		{
			RebuildBanner(WD->GetStateLines());
		}
	}
}
