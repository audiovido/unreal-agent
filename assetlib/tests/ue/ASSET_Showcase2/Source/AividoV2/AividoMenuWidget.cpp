// Aivido V2 — ESC menu implementation.
// Widget tree is built in RebuildWidget() with WidgetTree->ConstructWidget<>()
// children: children created that way take their Slate widgets immediately, so
// the panel actually paints. (A NativeConstruct-built tree via NewObject() on
// `this` produces an empty viewport widget — vp=1/vis=1/geo=0.)

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
#include "Kismet/KismetSystemLibrary.h"

UButton* UAividoMenuWidget::MakeMenuButton(const FString& Label)
{
	UButton* Btn = WidgetTree->ConstructWidget<UButton>();
	UTextBlock* L = WidgetTree->ConstructWidget<UTextBlock>();
	L->SetText(FText::FromString(Label));
	L->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(230, 230, 230))));
	L->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 14));
	Btn->AddChild(L);
	return Btn;
}

TSharedRef<SWidget> UAividoMenuWidget::RebuildWidget()
{
	// Build the tree first; Super::RebuildWidget() takes the root ONCE at the
	// end. (Taking the root twice — Super first + own TakeWidget — creates two
	// SWidgets around one UWidget and spins Slate forever.)
	UCanvasPanel* Canvas = WidgetTree->ConstructWidget<UCanvasPanel>();
	WidgetTree->RootWidget = Canvas;

	PanelBorder = WidgetTree->ConstructWidget<UBorder>();
	PanelBorder->SetPadding(FMargin(28.f, 24.f));
	PanelBorder->SetBrushColor(FLinearColor(0.02f, 0.03f, 0.06f, 0.9f));

	UTextBlock* Title = WidgetTree->ConstructWidget<UTextBlock>();
	Title->SetText(FText::FromString(TEXT("AIVIDO HQ — PAUSED")));
	Title->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(140, 200, 255))));
	Title->SetFont(FCoreStyle::GetDefaultFontStyle("Bold", 20));

	ResumeButton = MakeMenuButton(TEXT("Resume"));
	WorkerStatesButton = MakeMenuButton(TEXT("Refresh Worker States"));
	QuitButton = MakeMenuButton(TEXT("Quit Session"));

	StatusText = WidgetTree->ConstructWidget<UTextBlock>();
	StatusText->SetText(FText::GetEmpty());
	StatusText->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(190, 190, 190))));
	StatusText->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 12));

	ResumeButton->OnClicked.AddDynamic(this, &UAividoMenuWidget::OnResumeClicked);
	WorkerStatesButton->OnClicked.AddDynamic(this, &UAividoMenuWidget::OnWorkerStatesClicked);
	QuitButton->OnClicked.AddDynamic(this, &UAividoMenuWidget::OnQuitClicked);

	UVerticalBox* Body = WidgetTree->ConstructWidget<UVerticalBox>();
	Body->AddChildToVerticalBox(Title)->SetPadding(FMargin(0, 0, 0, 14));
	Body->AddChildToVerticalBox(ResumeButton)->SetPadding(FMargin(0, 3));
	Body->AddChildToVerticalBox(WorkerStatesButton)->SetPadding(FMargin(0, 3));
	Body->AddChildToVerticalBox(QuitButton)->SetPadding(FMargin(0, 3));
	Body->AddChildToVerticalBox(StatusText)->SetPadding(FMargin(0, 10, 0, 0));
	PanelBorder->SetContent(Body);

	if (UCanvasPanelSlot* CS = Canvas->AddChildToCanvas(PanelBorder))
	{
		// Use explicit center extents rather than relying on the widget's
		// desired-size pass.  This keeps the overlay in logical Slate units
		// after viewport DPI scaling and avoids the packaged-game
		// lower-right displacement seen with an auto-sized centered slot.
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
			// Live result text: the click visibly updates this menu's status line.
			// RemoveAll first — the widget survives open/close cycles.
			GM->OnWorkerStatesChanged.RemoveAll(this);
			GM->OnWorkerStatesChanged.AddUObject(this, &UAividoMenuWidget::OnStatesChanged);
		}
	}
}

void UAividoMenuWidget::OnWorkerStatesClicked()
{
	if (StatusText)
	{
		StatusText->SetText(FText::FromString(TEXT("Refreshing worker states…")));
	}
	if (AAividoGameMode* GM = GameMode.Get())
	{
		GM->RequestWorkerStates();
	}
}

void UAividoMenuWidget::OnQuitClicked()
{
	UKismetSystemLibrary::QuitGame(GetWorld(), GetWorld()->GetFirstPlayerController(),
		EQuitPreference::Quit, false);
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
		GM->ToggleMenu(); // closes
	}
}
