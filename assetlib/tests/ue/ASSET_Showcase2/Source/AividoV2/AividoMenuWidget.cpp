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
#include "Styling/SlateTypes.h"
#include "Engine/World.h"
#include "Kismet/KismetSystemLibrary.h"

UButton* UAividoMenuWidget::MakeMenuButton(const FString& Label)
{
	UButton* Btn = WidgetTree->ConstructWidget<UButton>();
	UTextBlock* L = WidgetTree->ConstructWidget<UTextBlock>();
	L->SetText(FText::FromString(Label));
	L->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(230, 230, 230))));
	L->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 14));
	// Uniform button width: the label defines the button's desired width, so
	// all rows read as one aligned list regardless of label length.
	L->SetMinDesiredWidth(260.f);
	Btn->AddChild(L);

	// Deterministic hover/focus/pressed feedback: rounded solid-color brushes
	// that render in any build (no editor-authored style assets exist).
	FButtonStyle Style;
	auto Rounded = [](const FLinearColor& C)
	{
		FSlateBrush B;
		B.DrawAs = ESlateBrushDrawType::RoundedBox;
		B.TintColor = FSlateColor(C);
		B.OutlineSettings.CornerRadii = FVector4(4.f, 4.f, 4.f, 4.f);
		return B;
	};
	Style.SetNormal(Rounded(FLinearColor(0.10f, 0.13f, 0.20f, 0.95f)));
	Style.SetHovered(Rounded(FLinearColor(0.22f, 0.30f, 0.46f, 1.f)));
	Style.SetPressed(Rounded(FLinearColor(0.34f, 0.46f, 0.68f, 1.f)));
	Style.SetDisabled(Rounded(FLinearColor(0.07f, 0.08f, 0.10f, 0.55f)));
	Style.SetNormalPadding(FMargin(16.f, 10.f));
	Style.SetPressedPadding(FMargin(16.f, 12.f, 16.f, 8.f));
	Btn->SetStyle(Style);
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

	TitleText = WidgetTree->ConstructWidget<UTextBlock>();
	TitleText->SetText(FText::FromString(TEXT("AIVIDO HQ")));
	TitleText->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(140, 200, 255))));
	TitleText->SetFont(FCoreStyle::GetDefaultFontStyle("Bold", 20));

	ResumeButton = MakeMenuButton(TEXT("Resume"));
	ResumeLabel = Cast<UTextBlock>(ResumeButton->GetContent());

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
	Body->AddChildToVerticalBox(TitleText)->SetPadding(FMargin(0, 0, 0, 14));
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

	// Deterministic keyboard navigation between the buttons (arrows + Tab).
	ApplyNavigation();

	return Super::RebuildWidget();
}

void UAividoMenuWidget::ApplyNavigation()
{
	if (!ResumeButton || !WorkerStatesButton || !QuitButton) return;

	// Arrow navigation with wraparound. In main-menu mode the Worker States
	// button is collapsed and Slate navigation skips non-focusable widgets,
	// so Resume<->Quit wraps correctly in both modes.
	ResumeButton->SetNavigationRuleExplicit(EUINavigation::Down, WorkerStatesButton);
	ResumeButton->SetNavigationRuleExplicit(EUINavigation::Up, QuitButton);
	WorkerStatesButton->SetNavigationRuleExplicit(EUINavigation::Down, QuitButton);
	WorkerStatesButton->SetNavigationRuleExplicit(EUINavigation::Up, ResumeButton);
	QuitButton->SetNavigationRuleExplicit(EUINavigation::Down, ResumeButton);
	QuitButton->SetNavigationRuleExplicit(EUINavigation::Up, WorkerStatesButton);

	// Tab / Shift+Tab traversal in list order.
	ResumeButton->SetNavigationRuleExplicit(EUINavigation::Next, WorkerStatesButton);
	WorkerStatesButton->SetNavigationRuleExplicit(EUINavigation::Next, QuitButton);
	QuitButton->SetNavigationRuleExplicit(EUINavigation::Next, ResumeButton);
	ResumeButton->SetNavigationRuleExplicit(EUINavigation::Previous, QuitButton);
	WorkerStatesButton->SetNavigationRuleExplicit(EUINavigation::Previous, ResumeButton);
	QuitButton->SetNavigationRuleExplicit(EUINavigation::Previous, WorkerStatesButton);
}

void UAividoMenuWidget::NativeDestruct()
{
	if (AAividoGameMode* GM = GameMode.Get())
	{
		GM->OnWorkerStatesChanged.RemoveAll(this);
	}
	Super::NativeDestruct();
}

void UAividoMenuWidget::SetMainMenuMode(bool bMainMenu)
{
	bMainMenuMode = bMainMenu;
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

	if (TitleText)
	{
		TitleText->SetText(FText::FromString(
			bMainMenuMode ? TEXT("AIVIDO HQ") : TEXT("AIVIDO HQ — PAUSED")));
	}
	if (ResumeLabel)
	{
		ResumeLabel->SetText(FText::FromString(
			bMainMenuMode ? TEXT("Start Session") : TEXT("Resume")));
	}
	if (WorkerStatesButton)
	{
		WorkerStatesButton->SetVisibility(
			bMainMenuMode ? ESlateVisibility::Collapsed : ESlateVisibility::Visible);
	}
	if (StatusText)
	{
		StatusText->SetText(FText::GetEmpty());
	}

	// First-button focus, deferred one tick so Slate focus is ready even at
	// boot (widget added to viewport the same frame the window appears).
	// Also logs the panel geometry shortly after open so the log file proves
	// the overlay is laid out and painted (deterministic paint evidence).
	if (UWorld* W = World)
	{
		TWeakObjectPtr<UAividoMenuWidget> WeakThis(this);
		W->GetTimerManager().SetTimerForNextTick(FTimerDelegate::CreateWeakLambda(this, [WeakThis]()
		{
			if (WeakThis.IsValid() && WeakThis->ResumeButton)
			{
				WeakThis->ResumeButton->SetKeyboardFocus();
			}
		}));
		W->GetTimerManager().SetTimer(MenuGeoLogHandle, FTimerDelegate::CreateWeakLambda(this, [WeakThis]()
		{
			if (!WeakThis.IsValid()) return;
			const FVector2D PanelSize = WeakThis->PanelBorder
				? WeakThis->PanelBorder->GetCachedGeometry().GetLocalSize()
				: FVector2D::ZeroVector;
			UE_LOG(LogTemp, Log, TEXT("AIVIDO_UI: menu_geo=%s vp=%d vis=%d"),
				*PanelSize.ToString(),
				WeakThis->IsInViewport() ? 1 : 0,
				WeakThis->GetIsVisible() ? 1 : 0);
		}), 0.6f, false);
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
		GM->CloseMenu(); // Resume (pause) or Start Session (main menu)
	}
}