// Aivido V2 — native UMG HUD implementation (widget tree built in C++).

#include "AividoHUD.h"
#include "Blueprint/WidgetTree.h"
#include "AividoGameMode.h"
#include "AividoCharacter.h"
#include "AividoWorkerDirector.h"
#include "Components/TextBlock.h"
#include "Components/Border.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/VerticalBox.h"
#include "Styling/CoreStyle.h"
#include "Styling/SlateColor.h"
#include "Styling/SlateBrush.h"
#include "Components/VerticalBoxSlot.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"

void UAividoHUD::NativeConstruct()
{
	Super::NativeConstruct();

	UCanvasPanel* Canvas = NewObject<UCanvasPanel>(this);
	WidgetTree->RootWidget = Canvas;

	// --- Banner (top-left) ---
	UBorder* BannerBorder = NewObject<UBorder>(this);
	BannerBorder->SetPadding(FMargin(14.f, 10.f));
	BannerBorder->SetBrushColor(FLinearColor(0.02f, 0.03f, 0.05f, 0.55f));

	TitleText = NewObject<UTextBlock>(this);
	TitleText->SetText(FText::FromString(TEXT("AIVIDO HQ — V2")));
	TitleText->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(140, 200, 255))));
	TitleText->SetFont(FCoreStyle::GetDefaultFontStyle("Bold", 20));

	LinkText = NewObject<UTextBlock>(this);
	LinkText->SetText(FText::FromString(TEXT("director link: ready")));
	LinkText->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(190, 190, 190))));
	LinkText->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 11));

	WorkersText = NewObject<UTextBlock>(this);
	WorkersText->SetText(FText::GetEmpty());
	WorkersText->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(200, 200, 210))));
	WorkersText->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 11));

	UVerticalBox* Left = NewObject<UVerticalBox>(this);
	Left->AddChildToVerticalBox(TitleText)->SetPadding(FMargin(0, 0, 0, 2));
	Left->AddChildToVerticalBox(LinkText)->SetPadding(FMargin(0, 0, 0, 6));
	Left->AddChildToVerticalBox(WorkersText);
	BannerBorder->SetContent(Left);

	if (UCanvasPanelSlot* BS = Canvas->AddChildToCanvas(BannerBorder))
	{
		BS->SetAutoSize(true);
		BS->SetPosition(FVector2D(16, 16));
	}

	// --- Interaction prompt (bottom-center) ---
	PromptText = NewObject<UTextBlock>(this);
	PromptText->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(255, 220, 140))));
	PromptText->SetFont(FCoreStyle::GetDefaultFontStyle("Bold", 16));
	PromptText->SetVisibility(ESlateVisibility::Collapsed);

	if (UCanvasPanelSlot* PS = Canvas->AddChildToCanvas(PromptText))
	{
		PS->SetAutoSize(true);
		PS->SetAnchors(FAnchors(0.5f, 1.f, 0.5f, 1.f));
		PS->SetAlignment(FVector2D(0.5f, 1.f));
		PS->SetPosition(FVector2D(0, -48));
	}
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
		InGameMode->OnWorkerStatesChanged.AddUObject(this, &UAividoHUD::RebuildBanner); // exact-signature bind
	}
}

void UAividoHUD::RebuildBanner(const TArray<FString>& StateLines)
{
	AAividoGameMode* GM = GameMode.Get();
	UWorld* World = GetWorld();
	if (!GM || !World || !WorkersText) return;

	// Real worker activity lines pushed from the worker state director.
	const FString WorkersJoined = FString::Join(StateLines, TEXT("\n"));

	if (!WorkersJoined.Equals(LastWorkersJoined))
	{
		LastWorkersJoined = WorkersJoined;
		WorkersText->SetText(FText::FromString(WorkersJoined));
	}

	const bool bWaiting = GM->IsWaitingForReply();
	LinkText->SetText(FText::FromString(bWaiting
		? TEXT("director link: waiting for reply…")
		: TEXT("director link: ready — [E] to talk to the Master Director")));
}

void UAividoHUD::RefreshPrompt()
{
	UWorld* World = GetWorld();
	if (!World || !PromptText) return;

	APlayerController* PC = World->GetFirstPlayerController();
	AAividoCharacter* Ch = PC ? Cast<AAividoCharacter>(PC->GetPawn()) : nullptr;
	if (!Ch) return;

	if (Ch->CurrentTargetName.IsEmpty())
	{
		PromptText->SetVisibility(ESlateVisibility::Collapsed);
	}
	else
	{
		PromptText->SetText(FText::FromString(
			FString::Printf(TEXT("[E]  Talk to %s"), *Ch->CurrentTargetName)));
		PromptText->SetVisibility(ESlateVisibility::HitTestInvisible);
	}
}

void UAividoHUD::NativeTick(const FGeometry& MyGeometry, float InDeltaTime)
{
	Super::NativeTick(MyGeometry, InDeltaTime);

	RefreshPrompt();

	// Banner refresh at ~2 Hz (cheap; keeps truthful state current).
	BannerRefreshTimer += InDeltaTime;
	if (BannerRefreshTimer >= 0.5f)
	{
		BannerRefreshTimer = 0.f;
		UWorld* World = GetWorld();
		// Pull the current worker state lines (cached on the director;
		// the push path uses the OnWorkerStatesChanged delegate).
		TArray<AActor*> Found;
		UGameplayStatics::GetAllActorsOfClass(World, AAividoWorkerDirector::StaticClass(), Found);
		if (AAividoWorkerDirector* WD = Found.Num() ? Cast<AAividoWorkerDirector>(Found[0]) : nullptr)
		{
			RebuildBanner(WD->GetStateLines());
		}
	}
}
