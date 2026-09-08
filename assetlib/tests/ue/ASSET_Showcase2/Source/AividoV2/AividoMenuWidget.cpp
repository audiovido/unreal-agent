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
#include "Kismet/KismetSystemLibrary.h"

static UButton* MakeMenuButton(UUserWidget* Owner, const FString& Label)
{
	UButton* Btn = NewObject<UButton>(Owner);
	UTextBlock* L = NewObject<UTextBlock>(Owner);
	L->SetText(FText::FromString(Label));
	L->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(230, 230, 230))));
	L->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 14));
	Btn->AddChild(L);
	return Btn;
}

void UAividoMenuWidget::NativeConstruct()
{
	Super::NativeConstruct();

	UCanvasPanel* Canvas = NewObject<UCanvasPanel>(this);
	WidgetTree->RootWidget = Canvas;

	PanelBorder = NewObject<UBorder>(this);
	PanelBorder->SetPadding(FMargin(28.f, 24.f));
	PanelBorder->SetBrushColor(FLinearColor(0.02f, 0.03f, 0.06f, 0.9f));

	UTextBlock* Title = NewObject<UTextBlock>(this);
	Title->SetText(FText::FromString(TEXT("AIVIDO HQ — PAUSED")));
	Title->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(140, 200, 255))));
	Title->SetFont(FCoreStyle::GetDefaultFontStyle("Bold", 20));

	ResumeButton = MakeMenuButton(this, TEXT("Resume"));
	WorkerStatesButton = MakeMenuButton(this, TEXT("Refresh Worker States"));
	QuitButton = MakeMenuButton(this, TEXT("Quit Session"));

	StatusText = NewObject<UTextBlock>(this);
	StatusText->SetText(FText::GetEmpty());
	StatusText->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(190, 190, 190))));
	StatusText->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 12));

	ResumeButton->OnClicked.AddDynamic(this, &UAividoMenuWidget::OnResumeClicked);
	WorkerStatesButton->OnClicked.AddDynamic(this, &UAividoMenuWidget::OnWorkerStatesClicked);
	QuitButton->OnClicked.AddDynamic(this, &UAividoMenuWidget::OnQuitClicked);

	UVerticalBox* Body = NewObject<UVerticalBox>(this);
	Body->AddChildToVerticalBox(Title)->SetPadding(FMargin(0, 0, 0, 14));
	Body->AddChildToVerticalBox(ResumeButton)->SetPadding(FMargin(0, 3));
	Body->AddChildToVerticalBox(WorkerStatesButton)->SetPadding(FMargin(0, 3));
	Body->AddChildToVerticalBox(QuitButton)->SetPadding(FMargin(0, 3));
	Body->AddChildToVerticalBox(StatusText)->SetPadding(FMargin(0, 10, 0, 0));
	PanelBorder->SetContent(Body);

	if (UCanvasPanelSlot* CS = Canvas->AddChildToCanvas(PanelBorder))
	{
		CS->SetAnchors(FAnchors(0.5f, 0.5f, 0.5f, 0.5f));
		CS->SetAlignment(FVector2D(0.5f, 0.5f));
		CS->SetAutoSize(true);
		CS->SetZOrder(30);
	}
}

void UAividoMenuWidget::NativeDestruct()
{
	if (AAividoGameMode* GM = GameMode.Get())
	{
		// (No persistent delegates from the menu; nothing to clear today.)
	}
	Super::NativeDestruct();
}

void UAividoMenuWidget::NotifyOpened()
{
	UWorld* World = GetWorld();
	if (World)
	{
		GameMode = World->GetAuthGameMode<AAividoGameMode>();
	}
}

void UAividoMenuWidget::OnResumeClicked()
{
	if (AAividoGameMode* GM = GameMode.Get())
	{
		GM->ToggleMenu(); // closes
	}
}

void UAividoMenuWidget::OnWorkerStatesClicked()
{
	if (AAividoGameMode* GM = GameMode.Get())
	{
		GM->RequestWorkerStates();
		if (StatusText)
		{
			StatusText->SetText(FText::FromString(TEXT("Requested fresh worker states from backend…")));
		}
	}
}

void UAividoMenuWidget::OnQuitClicked()
{
	UKismetSystemLibrary::QuitGame(GetWorld(), GetWorld()->GetFirstPlayerController(),
		EQuitPreference::Quit, false);
}
