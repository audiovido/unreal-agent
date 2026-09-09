// Aivido V2 — ESC menu implementation.

#include "AividoMenuWidget.h"
#include "Blueprint/WidgetTree.h"
#include "AividoGameMode.h"
#include "Components/Button.h"
#include "Components/TextBlock.h"
#include "Components/Border.h"
#include "Components/VerticalBox.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/VerticalBoxSlot.h"
#include "Styling/CoreStyle.h"
#include "Styling/SlateColor.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/KismetSystemLibrary.h"

namespace AividoMenuStyle
{
	const FLinearColor Panel(0.008f, 0.016f, 0.032f, 0.96f);
	const FLinearColor PanelEdge(0.10f, 0.42f, 0.70f, 0.72f);
	const FLinearColor Cyan(0.55f, 0.84f, 1.0f, 1.0f);
	const FLinearColor Body(0.86f, 0.90f, 0.96f, 1.0f);
	const FLinearColor Muted(0.60f, 0.69f, 0.78f, 1.0f);
	const FLinearColor Accent(0.08f, 0.24f, 0.40f, 1.0f);
}

UButton* UAividoMenuWidget::MakeMenuButton(const FString& Label)
{
	UButton* Btn = WidgetTree->ConstructWidget<UButton>();
	Btn->SetColorAndOpacity(AividoMenuStyle::Accent);
	Btn->SetForegroundColor(AividoMenuStyle::Body);
	Btn->SetContentPadding(FMargin(18.f, 13.f));

	UTextBlock* L = WidgetTree->ConstructWidget<UTextBlock>();
	L->SetText(FText::FromString(Label));
	L->SetColorAndOpacity(FSlateColor(AividoMenuStyle::Body));
	L->SetFont(FCoreStyle::GetDefaultFontStyle("Medium", 14));
	L->SetJustification(ETextJustify::Center);
	Btn->AddChild(L);
	return Btn;
}

TSharedRef<SWidget> UAividoMenuWidget::RebuildWidget()
{
	UCanvasPanel* Canvas = WidgetTree->ConstructWidget<UCanvasPanel>();
	WidgetTree->RootWidget = Canvas;

	PanelBorder = WidgetTree->ConstructWidget<UBorder>();
	PanelBorder->SetPadding(FMargin(34.f, 30.f, 34.f, 32.f));
	PanelBorder->SetBrushColor(AividoMenuStyle::Panel);

	UTextBlock* Eyebrow = WidgetTree->ConstructWidget<UTextBlock>();
	Eyebrow->SetText(FText::FromString(TEXT("AIVIDO  /  DIRECTOR'S BOOTH")));
	Eyebrow->SetColorAndOpacity(FSlateColor(AividoMenuStyle::Muted));
	Eyebrow->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 10));

	UTextBlock* Title = WidgetTree->ConstructWidget<UTextBlock>();
	Title->SetText(FText::FromString(TEXT("SESSION PAUSED")));
	Title->SetColorAndOpacity(FSlateColor(AividoMenuStyle::Cyan));
	Title->SetFont(FCoreStyle::GetDefaultFontStyle("Bold", 24));

	UTextBlock* Subtitle = WidgetTree->ConstructWidget<UTextBlock>();
	Subtitle->SetText(FText::FromString(TEXT("The room is waiting for the next direction.")));
	Subtitle->SetColorAndOpacity(FSlateColor(AividoMenuStyle::Muted));
	Subtitle->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 12));

	ResumeButton = MakeMenuButton(TEXT("RESUME SESSION"));
	WorkerStatesButton = MakeMenuButton(TEXT("REFRESH WORKER STATES"));
	QuitButton = MakeMenuButton(TEXT("QUIT SESSION"));

	StatusText = WidgetTree->ConstructWidget<UTextBlock>();
	StatusText->SetText(FText::FromString(TEXT("ESC  ·  close menu")));
	StatusText->SetColorAndOpacity(FSlateColor(AividoMenuStyle::Muted));
	StatusText->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 11));
	StatusText->SetAutoWrapText(true);
	StatusText->SetWrapTextAt(460.f);

	ResumeButton->OnClicked.AddDynamic(this, &UAividoMenuWidget::OnResumeClicked);
	WorkerStatesButton->OnClicked.AddDynamic(this, &UAividoMenuWidget::OnWorkerStatesClicked);
	QuitButton->OnClicked.AddDynamic(this, &UAividoMenuWidget::OnQuitClicked);

	UVerticalBox* Body = WidgetTree->ConstructWidget<UVerticalBox>();
	Body->AddChildToVerticalBox(Eyebrow)->SetPadding(FMargin(0, 0, 0, 7));
	Body->AddChildToVerticalBox(Title)->SetPadding(FMargin(0, 0, 0, 5));
	Body->AddChildToVerticalBox(Subtitle)->SetPadding(FMargin(0, 0, 0, 24));
	Body->AddChildToVerticalBox(ResumeButton)->SetPadding(FMargin(0, 0, 0, 9));
	Body->AddChildToVerticalBox(WorkerStatesButton)->SetPadding(FMargin(0, 0, 0, 9));
	Body->AddChildToVerticalBox(QuitButton)->SetPadding(FMargin(0, 0, 0, 17));
	Body->AddChildToVerticalBox(StatusText);
	PanelBorder->SetContent(Body);

	if (UCanvasPanelSlot* CS = Canvas->AddChildToCanvas(PanelBorder))
	{
		// Center anchor keeps this intentional card centered at 16:9, 16:10,
		// ultrawide, and windowed viewports. Clamped logical extents avoid
		// viewport-edge clipping on compact packaged windows.
		CS->SetAnchors(FAnchors(0.5f, 0.5f, 0.5f, 0.5f));
		CS->SetAlignment(FVector2D(0.5f, 0.5f));
		CS->SetPosition(FVector2D(0.f, 0.f));
		CS->SetSize(FVector2D(560.f, 440.f));
		CS->SetAutoSize(false);
		CS->SetZOrder(30);
	}

	return Super::RebuildWidget();
}

void UAividoMenuWidget::NativeDestruct()
{
	if (AAividoGameMode* GM = GameMode.Get())
	{
		GM->OnWorkerStatesChanged.RemoveAll(this);
	}
	Super::NativeDestruct();
}

void UAividoMenuWidget::NotifyOpened()
{
	UWorld* World = GetWorld();
	if (World)
	{
		GameMode = World->GetAuthGameMode<AAividoGameMode>();
		if (AAividoGameMode* GM = GameMode.Get())
		{
			GM->OnWorkerStatesChanged.RemoveAll(this);
			GM->OnWorkerStatesChanged.AddUObject(this, &UAividoMenuWidget::OnStatesChanged);
		}
	}
	if (ResumeButton)
	{
		ResumeButton->SetKeyboardFocus();
	}
}

void UAividoMenuWidget::OnWorkerStatesClicked()
{
	if (StatusText)
	{
		StatusText->SetText(FText::FromString(TEXT("WORKER LINK  ·  REFRESHING…")));
	}
	if (AAividoGameMode* GM = GameMode.Get())
	{
		GM->RequestWorkerStates();
	}
}

void UAividoMenuWidget::OnQuitClicked()
{
	if (UWorld* World = GetWorld())
	{
		UKismetSystemLibrary::QuitGame(World, World->GetFirstPlayerController(),
			EQuitPreference::Quit, false);
	}
}

void UAividoMenuWidget::OnStatesChanged(const TArray<FString>& StateLines)
{
	if (StatusText)
	{
		StatusText->SetText(FText::FromString(
			StateLines.Num()
				? FString::Join(StateLines, TEXT("\n"))
				: TEXT("No worker sessions reported.")));
	}
}

void UAividoMenuWidget::OnResumeClicked()
{
	if (AAividoGameMode* GM = GameMode.Get())
	{
		GM->ToggleMenu();
	}
}
