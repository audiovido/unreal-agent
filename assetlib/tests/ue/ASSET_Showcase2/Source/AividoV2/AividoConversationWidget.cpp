// Aivido V2 — conversation panel implementation.

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
#include "Components/VerticalBoxSlot.h"
#include "Components/HorizontalBoxSlot.h"
#include "Styling/CoreStyle.h"
#include "Styling/SlateColor.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"

namespace AividoConversationStyle
{
	const FLinearColor Panel(0.006f, 0.014f, 0.030f, 0.97f);
	const FLinearColor TranscriptPanel(0.012f, 0.028f, 0.050f, 0.90f);
	const FLinearColor InputPanel(0.015f, 0.040f, 0.070f, 1.0f);
	const FLinearColor Cyan(0.55f, 0.84f, 1.0f, 1.0f);
	const FLinearColor Body(0.88f, 0.92f, 0.97f, 1.0f);
	const FLinearColor Muted(0.60f, 0.70f, 0.80f, 1.0f);
	const FLinearColor User(0.70f, 0.86f, 1.0f, 1.0f);
	const FLinearColor Director(0.95f, 0.88f, 0.66f, 1.0f);
}

static UTextBlock* AividoLabel(UWidgetTree* Tree, const FString& Text,
	const FLinearColor& Color, const FSlateFontInfo& Font)
{
	UTextBlock* Label = Tree->ConstructWidget<UTextBlock>();
	Label->SetText(FText::FromString(Text));
	Label->SetColorAndOpacity(FSlateColor(Color));
	Label->SetFont(Font);
	return Label;
}

TSharedRef<SWidget> UAividoConversationWidget::RebuildWidget()
{
	UCanvasPanel* Canvas = WidgetTree->ConstructWidget<UCanvasPanel>();
	WidgetTree->RootWidget = Canvas;

	PanelBorder = WidgetTree->ConstructWidget<UBorder>();
	PanelBorder->SetPadding(FMargin(28.f, 25.f, 28.f, 26.f));
	PanelBorder->SetBrushColor(AividoConversationStyle::Panel);

	UTextBlock* Eyebrow = AividoLabel(WidgetTree, TEXT("AIVIDO  /  SECURE DIRECTOR LINK"),
		AividoConversationStyle::Muted, FCoreStyle::GetDefaultFontStyle("Regular", 10));
	TitleText = AividoLabel(WidgetTree, TEXT("MASTER DIRECTOR"),
		AividoConversationStyle::Cyan, FCoreStyle::GetDefaultFontStyle("Bold", 23));
	SessionText = AividoLabel(WidgetTree, TEXT("LIVE SESSION  ·  ENCRYPTED CHANNEL"),
		AividoConversationStyle::Muted, FCoreStyle::GetDefaultFontStyle("Regular", 11));

	Transcript = WidgetTree->ConstructWidget<UScrollBox>();
	Transcript->SetScrollBarVisibility(ESlateVisibility::Visible);
	Transcript->SetAlwaysShowScrollbar(false);
	Transcript->SetAnimateWheelScrolling(true);
	Transcript->SetConsumeMouseWheel(EConsumeMouseWheel::WhenScrollingPossible);
	UBorder* TranscriptBorder = WidgetTree->ConstructWidget<UBorder>();
	TranscriptBorder->SetPadding(FMargin(18.f, 15.f, 18.f, 15.f));
	TranscriptBorder->SetBrushColor(AividoConversationStyle::TranscriptPanel);
	TranscriptBorder->SetContent(Transcript);

	InputBox = WidgetTree->ConstructWidget<UEditableTextBox>();
	InputBox->SetHintText(FText::FromString(TEXT("Direct a question or describe the next move…")));
	InputBox->SetForegroundColor(AividoConversationStyle::Body);
	InputBox->SetHintColor(FSlateColor(AividoConversationStyle::Muted));
	InputBox->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 13));
	InputBox->SetPadding(FMargin(14.f, 11.f));
	InputBox->OnTextCommitted.AddUniqueDynamic(this, &UAividoConversationWidget::OnCommitted);
	UBorder* InputBorder = WidgetTree->ConstructWidget<UBorder>();
	InputBorder->SetPadding(FMargin(0.f));
	InputBorder->SetBrushColor(AividoConversationStyle::InputPanel);
	InputBorder->SetContent(InputBox);

	SendButton = WidgetTree->ConstructWidget<UButton>();
	SendButton->SetColorAndOpacity(FLinearColor(0.08f, 0.30f, 0.48f, 1.0f));
	SendButton->SetForegroundColor(AividoConversationStyle::Body);
	SendButton->SetContentPadding(FMargin(16.f, 11.f));
	UTextBlock* SendLabel = AividoLabel(WidgetTree, TEXT("SEND"),
		AividoConversationStyle::Body, FCoreStyle::GetDefaultFontStyle("Bold", 12));
	SendLabel->SetJustification(ETextJustify::Center);
	SendButton->AddChild(SendLabel);
	SendButton->OnClicked.AddDynamic(this, &UAividoConversationWidget::OnSendClicked);

	CloseButton = WidgetTree->ConstructWidget<UButton>();
	CloseButton->SetColorAndOpacity(FLinearColor(0.06f, 0.10f, 0.16f, 1.0f));
	CloseButton->SetForegroundColor(AividoConversationStyle::Muted);
	CloseButton->SetContentPadding(FMargin(14.f, 11.f));
	UTextBlock* CloseLabel = AividoLabel(WidgetTree, TEXT("CLOSE  [ESC]"),
		AividoConversationStyle::Muted, FCoreStyle::GetDefaultFontStyle("Regular", 11));
	CloseLabel->SetJustification(ETextJustify::Center);
	CloseButton->AddChild(CloseLabel);
	CloseButton->OnClicked.AddDynamic(this, &UAividoConversationWidget::OnCloseClicked);

	UHorizontalBox* Row = WidgetTree->ConstructWidget<UHorizontalBox>();
	Row->AddChildToHorizontalBox(InputBorder)->SetSize(FSlateChildSize(ESlateSizeRule::Fill));
	Row->AddChildToHorizontalBox(SendButton)->SetPadding(FMargin(10.f, 0.f, 0.f, 0.f));
	Row->AddChildToHorizontalBox(CloseButton)->SetPadding(FMargin(8.f, 0.f, 0.f, 0.f));

	UVerticalBox* Body = WidgetTree->ConstructWidget<UVerticalBox>();
	Body->AddChildToVerticalBox(Eyebrow)->SetPadding(FMargin(0, 0, 0, 6));
	Body->AddChildToVerticalBox(TitleText)->SetPadding(FMargin(0, 0, 0, 3));
	Body->AddChildToVerticalBox(SessionText)->SetPadding(FMargin(0, 0, 0, 20));
	Body->AddChildToVerticalBox(TranscriptBorder)->SetSize(FSlateChildSize(ESlateSizeRule::Fill));
	Body->AddChildToVerticalBox(Row)->SetPadding(FMargin(0, 16.f, 0, 0));
	PanelBorder->SetContent(Body);

	if (UCanvasPanelSlot* CS = Canvas->AddChildToCanvas(PanelBorder))
	{
		CS->SetAnchors(FAnchors(0.5f, 0.5f, 0.5f, 0.5f));
		CS->SetAlignment(FVector2D(0.5f, 0.5f));
		CS->SetPosition(FVector2D(-360.f, -220.f));
		CS->SetSize(FVector2D(720.f, 440.f));
		CS->SetAutoSize(false);
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
			GM->OnReplyChanged.RemoveAll(this);
			GM->OnReplyChanged.AddUObject(this, &UAividoConversationWidget::OnReply);
		}
	}
	if (!bWelcomeShown)
	{
		AppendLine(TEXT("Director"), TEXT("Welcome to Aivido HQ. What are we building today?"));
		bWelcomeShown = true;
	}
	if (InputBox)
	{
		InputBox->SetKeyboardFocus();
	}
}

void UAividoConversationWidget::AppendLine(const FString& Speaker, const FString& Text)
{
	if (!Transcript) return;

	UBorder* Bubble = WidgetTree->ConstructWidget<UBorder>();
	Bubble->SetPadding(FMargin(12.f, 9.f, 12.f, 10.f));
	Bubble->SetBrushColor(Speaker == TEXT("You")
		? FLinearColor(0.04f, 0.12f, 0.20f, 0.92f)
		: FLinearColor(0.16f, 0.12f, 0.06f, 0.86f));

	UTextBlock* Line = WidgetTree->ConstructWidget<UTextBlock>();
	Line->SetText(FText::FromString(FString::Printf(TEXT("%s\n%s"), *Speaker.ToUpper(), *Text)));
	Line->SetColorAndOpacity(FSlateColor(Speaker == TEXT("You")
		? AividoConversationStyle::User : AividoConversationStyle::Director));
	Line->SetFont(FCoreStyle::GetDefaultFontStyle("Regular", 13));
	Line->SetAutoWrapText(true);
	Line->SetWrapTextAt(610.f);
	Bubble->SetContent(Line);

	if (Transcript->GetChildrenCount() > 0)
	{
		if (UVerticalBox* Existing = Cast<UVerticalBox>(Transcript->GetChildAt(0)))
		{
			Existing->AddChildToVerticalBox(Bubble)->SetPadding(FMargin(0.f, 0.f, 0.f, 9.f));
		}
	}
	else
	{
		UVerticalBox* Stack = WidgetTree->ConstructWidget<UVerticalBox>();
		Stack->AddChildToVerticalBox(Bubble)->SetPadding(FMargin(0.f, 0.f, 0.f, 9.f));
		Transcript->AddChild(Stack);
	}
	Transcript->ScrollToEnd();
}

void UAividoConversationWidget::OnSendClicked()
{
	if (!InputBox) return;
	const FString Msg = InputBox->GetText().ToString().TrimStartAndEnd();
	if (Msg.IsEmpty()) return;

	AAividoGameMode* GM = GetWorld() ? GetWorld()->GetAuthGameMode<AAividoGameMode>() : nullptr;
	if (!GM || GM->IsWaitingForReply()) return;

	AppendLine(TEXT("You"), Msg);
	InputBox->SetText(FText::GetEmpty());
	GM->SubmitChatLine(Msg);
	AppendLine(TEXT("Director"), TEXT("…THINKING"));
}

void UAividoConversationWidget::OnCloseClicked()
{
	if (AAividoGameMode* GM = GetWorld() ? GetWorld()->GetAuthGameMode<AAividoGameMode>() : nullptr)
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
	if (Transcript && Transcript->GetChildrenCount() > 0)
	{
		if (UVerticalBox* Stack = Cast<UVerticalBox>(Transcript->GetChildAt(0)))
		{
			const int32 Num = Stack->GetChildrenCount();
			if (Num > 0)
			{
				if (UBorder* Last = Cast<UBorder>(Stack->GetChildAt(Num - 1)))
				{
					if (UTextBlock* Label = Cast<UTextBlock>(Last->GetContent()))
					{
						if (Label->GetText().ToString().EndsWith(TEXT("…THINKING")))
						{
							Stack->RemoveChild(Last);
						}
					}
				}
			}
		}
	}
	AppendLine(TEXT("Director"), Reply);
	if (SessionText)
	{
		SessionText->SetText(FText::FromString(TEXT("LIVE SESSION  ·  DIRECTOR REPLIED")));
	}
}
