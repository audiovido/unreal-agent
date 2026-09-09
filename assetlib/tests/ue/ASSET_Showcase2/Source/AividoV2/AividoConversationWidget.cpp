// Aivido V2 — conversation panel implementation.
// Tree built in RebuildWidget() with WidgetTree->ConstructWidget<>() children
// so every child takes its Slate widget and the panel actually renders.

#include "AividoConversationWidget.h"
#include "Blueprint/WidgetTree.h"
#include "AividoGameMode.h"
#include "Components/TextBlock.h"
#include "Components/EditableTextBox.h"
#include "Components/Button.h"
#include "Components/ScrollBox.h"
#include "Components/Border.h"
#include "Components/VerticalBox.h"
#include "Components/HorizontalBox.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Styling/CoreStyle.h"
#include "Styling/SlateColor.h"
#include "Styling/SlateBrush.h"
#include "Styling/StyleColors.h"
#include "Components/VerticalBoxSlot.h"
#include "Components/HorizontalBoxSlot.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"

TSharedRef<SWidget> UAividoConversationWidget::RebuildWidget()
{
	// Build the tree first; Super::RebuildWidget() takes the root ONCE.
	UCanvasPanel* Canvas = WidgetTree->ConstructWidget<UCanvasPanel>();
	WidgetTree->RootWidget = Canvas;

	PanelBorder = WidgetTree->ConstructWidget<UBorder>();
	PanelBorder->SetPadding(FMargin(16.f));
	PanelBorder->SetBrushColor(FLinearColor(0.02f, 0.03f, 0.06f, 0.88f));

	// Title
	TitleText = WidgetTree->ConstructWidget<UTextBlock>();
	TitleText->SetText(FText::FromString(TEXT("Master Director — Aivido HQ")));
	TitleText->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(140, 200, 255))));
	TitleText->SetFont(FCoreStyle::GetDefaultFontStyle("Bold", 18));

	// Transcript
	Transcript = WidgetTree->ConstructWidget<UScrollBox>();

	// Input row
	InputBox = WidgetTree->ConstructWidget<UEditableTextBox>();
	InputBox->SetHintText(FText::FromString(TEXT("Ask the Master Director… (Enter to send)")));
	InputBox->SetForegroundColor(FLinearColor::White);
	InputBox->OnTextCommitted.AddUniqueDynamic(this, &UAividoConversationWidget::OnCommitted);

	SendButton = WidgetTree->ConstructWidget<UButton>();
	UTextBlock* SendLabel = WidgetTree->ConstructWidget<UTextBlock>();
	SendLabel->SetText(FText::FromString(TEXT("Send")));
	SendLabel->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(230, 230, 230))));
	SendLabel->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 12));
	SendButton->AddChild(SendLabel);
	SendButton->OnClicked.AddDynamic(this, &UAividoConversationWidget::OnSendClicked);

	CloseButton = WidgetTree->ConstructWidget<UButton>();
	UTextBlock* CloseLabel = WidgetTree->ConstructWidget<UTextBlock>();
	CloseLabel->SetText(FText::FromString(TEXT("Close (Esc)")));
	CloseLabel->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(230, 230, 230))));
	CloseLabel->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 12));
	CloseButton->AddChild(CloseLabel);
	CloseButton->OnClicked.AddDynamic(this, &UAividoConversationWidget::OnCloseClicked);

	UHorizontalBox* Row = WidgetTree->ConstructWidget<UHorizontalBox>();
	Row->AddChildToHorizontalBox(InputBox);
	Row->AddChildToHorizontalBox(SendButton);
	Row->AddChildToHorizontalBox(CloseButton);

	UVerticalBox* Body = WidgetTree->ConstructWidget<UVerticalBox>();
	Body->AddChildToVerticalBox(TitleText)->SetPadding(FMargin(0, 0, 0, 8));
	Body->AddChildToVerticalBox(Transcript)->SetSize(FSlateChildSize(ESlateSizeRule::Fill));
	Body->AddChildToVerticalBox(Row)->SetPadding(FMargin(0, 8, 0, 0));
	PanelBorder->SetContent(Body);

	if (UCanvasPanelSlot* CS = Canvas->AddChildToCanvas(PanelBorder))
	{
		CS->SetAnchors(FAnchors(0.5f, 0.5f, 0.5f, 0.5f));
		CS->SetAlignment(FVector2D(0.5f, 0.5f));
		CS->SetSize(FVector2D(720, 440));
		CS->SetZOrder(20);
	}

	return Super::RebuildWidget();
}

void UAividoConversationWidget::NativeDestruct()
{
	if (AAividoGameMode* GM = GameMode.Get())
	{
		GM->OnReplyChanged.RemoveAll(this);
	}
	Super::NativeDestruct();
}

void UAividoConversationWidget::NotifyOpened()
{
	UWorld* World = GetWorld();
	if (World)
	{
		GameMode = World->GetAuthGameMode<AAividoGameMode>();
		if (AAividoGameMode* GM = GameMode.Get())
		{
			GM->OnReplyChanged.AddUObject(this, &UAividoConversationWidget::OnReply);
		}
	}
	AppendLine(TEXT("Director"), TEXT("Welcome to Aivido HQ. What are we building today?"));
	if (InputBox)
	{
		InputBox->SetKeyboardFocus();
	}
}

void UAividoConversationWidget::AppendLine(const FString& Speaker, const FString& Text)
{
	if (!Transcript) return;

	UTextBlock* Line = WidgetTree->ConstructWidget<UTextBlock>();
	Line->SetText(FText::FromString(FString::Printf(TEXT("%s: %s"), *Speaker, *Text)));
	Line->SetColorAndOpacity(FSlateColor(FLinearColor(FColor(
		Speaker == TEXT("You") ? 210 : 255,
		Speaker == TEXT("You") ? 225 : 220,
		Speaker == TEXT("You") ? 255 : 150))));
	Line->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 13));
	Line->SetAutoWrapText(true);
	Transcript->AddChild(Line);
	Transcript->ScrollToEnd();
}

void UAividoConversationWidget::OnSendClicked()
{
	if (!InputBox) return;
	const FString Msg = InputBox->GetText().ToString().TrimStartAndEnd();
	if (Msg.IsEmpty()) return;

	AAividoGameMode* GM = GameMode.Get();
	if (!GM || GM->IsWaitingForReply()) return;

	AppendLine(TEXT("You"), Msg);
	InputBox->SetText(FText::GetEmpty());
	GM->SubmitChatLine(Msg);
	AppendLine(TEXT("Director"), TEXT("…thinking"));
}

void UAividoConversationWidget::OnCloseClicked()
{
	if (AAividoGameMode* GM = GameMode.Get())
	{
		GM->CloseConversation();
	}
}

void UAividoConversationWidget::OnCommitted(const FText& Text, ETextCommit::Type Method)
{
	if (Method == ETextCommit::OnEnter)
	{
		OnSendClicked();
	}
}

void UAividoConversationWidget::OnReply(const FString& Reply)
{
	// Replace the trailing "…thinking" placeholder with the real reply.
	if (Transcript)
	{
		const int32 Num = Transcript->GetChildrenCount();
		if (Num > 0)
		{
			if (UTextBlock* Last = Cast<UTextBlock>(Transcript->GetChildAt(Num - 1)))
			{
				if (Last->GetText().ToString().EndsWith(TEXT("…thinking")))
				{
					Transcript->RemoveChild(Last);
				}
			}
		}
	}
	AppendLine(TEXT("Director"), Reply);
}
