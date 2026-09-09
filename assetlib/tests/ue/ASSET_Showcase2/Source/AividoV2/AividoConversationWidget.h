// Aivido V2 — conversation panel (native UMG).

#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "AividoConversationWidget.generated.h"

class AAividoGameMode;
class UTextBlock;
class UEditableTextBox;
class UButton;
class UScrollBox;
class UBorder;

/** Premium in-world Master Director conversation panel, built with C++ UMG. */
UCLASS()
class AIVIDOV2_API UAividoConversationWidget : public UUserWidget
{
	GENERATED_BODY()

public:
	virtual TSharedRef<SWidget> RebuildWidget() override;
	virtual void NativeDestruct() override;

	void NotifyOpened();

protected:
	void AppendLine(const FString& Speaker, const FString& Text);
	void OnSendClicked();
	void OnCloseClicked();
	void OnCommitted(const FText& Text, ETextCommit::Type Method);
	void OnReply(const FString& Reply);

	TObjectPtr<UBorder> PanelBorder;
	TObjectPtr<UTextBlock> TitleText;
	TObjectPtr<UTextBlock> SessionText;
	TObjectPtr<UScrollBox> Transcript;
	TObjectPtr<UEditableTextBox> InputBox;
	TObjectPtr<UButton> SendButton;
	TObjectPtr<UButton> CloseButton;

	TWeakObjectPtr<AAividoGameMode> GameMode;
	bool bWelcomeShown = false;
};
