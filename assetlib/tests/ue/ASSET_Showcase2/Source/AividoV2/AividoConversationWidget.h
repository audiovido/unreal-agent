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

/**
 * Master Director conversation panel.
 *  - transcript of the session (user + director bubbles as text lines)
 *  - input box + Send button + Enter submit (real round-trip to backend)
 *  - Close button + ESC both close; input mode handled by the GameMode
 */
UCLASS()
class AIVIDOV2_API UAividoConversationWidget : public UUserWidget
{
	GENERATED_BODY()

public:
	virtual void NativeConstruct() override;
	virtual void NativeDestruct() override;

	/** Called by the GameMode right after the panel is added to the viewport. */
	void NotifyOpened();

protected:
	void AppendLine(const FString& Speaker, const FString& Text);
	void OnSendClicked();
	void OnCloseClicked();
	void OnCommitted(const FText& Text, ETextCommit::Type Method);
	void OnReply(const FString& Reply);

	TObjectPtr<UBorder> PanelBorder;
	TObjectPtr<UTextBlock> TitleText;
	TObjectPtr<UScrollBox> Transcript;
	TObjectPtr<UEditableTextBox> InputBox;
	TObjectPtr<UButton> SendButton;
	TObjectPtr<UButton> CloseButton;

	TWeakObjectPtr<AAividoGameMode> GameMode;
};
