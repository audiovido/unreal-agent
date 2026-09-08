// Aivido V2 — production GameMode implementation.

#include "AividoGameMode.h"
#include "AividoCharacter.h"
#include "AividoDirector.h"
#include "AividoWorkerDirector.h"
#include "AividoConversationWidget.h"
#include "AividoMenuWidget.h"
#include "AividoHUD.h"
#include "Blueprint/UserWidget.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerStart.h"
#include "Kismet/GameplayStatics.h"
#include "HttpModule.h"
#include "Interfaces/IHttpRequest.h"
#include "Interfaces/IHttpResponse.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

AAividoGameMode::AAividoGameMode()
{
	// Native classes (no Blueprints required for boot).
	PlayerCharacterClass = AAividoCharacter::StaticClass();
	DirectorClass = AAividoDirector::StaticClass();
	WorkerDirectorClass = AAividoWorkerDirector::StaticClass();
	ConversationWidgetClass = UAividoConversationWidget::StaticClass();
	MenuWidgetClass = UAividoMenuWidget::StaticClass();

	DefaultPawnClass = AAividoCharacter::StaticClass();
	PlayerControllerClass = APlayerController::StaticClass();
	bStartPlayersAsSpectators = false;
	PrimaryActorTick.bCanEverTick = false;
}

void AAividoGameMode::BeginPlay()
{
	Super::BeginPlay();

	UWorld* World = GetWorld();
	if (!World) return;

	APlayerController* PC = World->GetFirstPlayerController();
	ApplyInputMode(false);

	// 1) The master director — primary conversation character, standing at his
	//    station from the Worker 2 handoff (0, 700, 0), facing the room.
	if (DirectorClass && !Director)
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride =
			ESpawnActorCollisionHandlingMethod::AdjustIfPossibleButAlwaysSpawn;
		Director = World->SpawnActor<AAividoDirector>(
			DirectorClass, FVector(0.f, 700.f, 96.f), FRotator(0.f, 0.f, 0.f), Params);
		if (Director)
		{
#if WITH_EDITOR
			Director->SetActorLabel(TEXT("AVIDO_Master_Director"));
#endif
		}
	}

	// 2) Worker state director — drives the 8 SkeletalMeshActor workers from
	//    their real runtime states (backend roster when reachable).
	if (WorkerDirectorClass && !WorkerDirector)
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride =
			ESpawnActorCollisionHandlingMethod::AdjustIfPossibleButAlwaysSpawn;
		WorkerDirector = World->SpawnActor<AAividoWorkerDirector>(
			WorkerDirectorClass, FVector::ZeroVector, FRotator::ZeroRotator, Params);
		if (WorkerDirector)
		{
#if WITH_EDITOR
			WorkerDirector->SetActorLabel(TEXT("Aivido_WorkerDirector"));
#endif
		}
	}

	// 3) Native HUD (state banner + interaction prompt).
	if (PC && PC->IsLocalController())
	{
		if (UAividoHUD* Hud = CreateWidget<UAividoHUD>(PC, UAividoHUD::StaticClass()))
		{
			Hud->AddToViewport(10);
			Hud->BindGameMode(this);
		}
	}
}

void AAividoGameMode::HandleInteract(AActor* InstigatorActor, AActor* Target)
{
	if (!Target) return;

	AAividoDirector* TargetDirector = Cast<AAividoDirector>(Target);
	if (TargetDirector)
	{
		TargetDirector->Focus();
		OpenConversation();
	}
}

void AAividoGameMode::OpenConversation()
{
	if (bConversationOpen) return;

	UWorld* World = GetWorld();
	APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	if (!PC) return;

	if (!ConversationWidget && ConversationWidgetClass)
	{
		ConversationWidget = CreateWidget<UUserWidget>(PC, ConversationWidgetClass);
	}

	if (ConversationWidget)
	{
		if (!ConversationWidget->IsInViewport())
		{
			ConversationWidget->AddToViewport(20);
		}
		if (UAividoConversationWidget* Conv = Cast<UAividoConversationWidget>(ConversationWidget))
		{
			Conv->NotifyOpened();
		}
	}

	bConversationOpen = true;
	ApplyInputMode(true); // GameAndUI while typing
	OnConversationChanged.Broadcast(true);
}

void AAividoGameMode::CloseConversation()
{
	if (!bConversationOpen) return;

	if (ConversationWidget && ConversationWidget->IsInViewport())
	{
		ConversationWidget->RemoveFromParent();
	}

	bConversationOpen = false;
	ApplyInputMode(false); // back to GameOnly
	OnConversationChanged.Broadcast(false);
}

void AAividoGameMode::ToggleMenu()
{
	UWorld* World = GetWorld();
	APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	if (!PC) return;

	// Conversation takes precedence: ESC closes chat first.
	if (bConversationOpen)
	{
		CloseConversation();
		return;
	}

	bMenuOpen = !bMenuOpen;

	if (bMenuOpen)
	{
		if (!MenuWidget && MenuWidgetClass)
		{
			MenuWidget = CreateWidget<UUserWidget>(PC, MenuWidgetClass);
		}
		if (MenuWidget && !MenuWidget->IsInViewport())
		{
			MenuWidget->AddToViewport(30);
		}
		if (UAividoMenuWidget* Menu = Cast<UAividoMenuWidget>(MenuWidget))
		{
			Menu->NotifyOpened();
		}
		ApplyInputMode(true);
	}
	else
	{
		if (MenuWidget && MenuWidget->IsInViewport())
		{
			MenuWidget->RemoveFromParent();
		}
		ApplyInputMode(false);
	}

	OnMenuStateChanged.Broadcast(bMenuOpen);
}

void AAividoGameMode::SubmitChatLine(const FString& Message)
{
	const FString Trimmed = Message.TrimStartAndEnd();
	if (Trimmed.IsEmpty() || bWaitingReply) return;

	bWaitingReply = true;
	LastReply = TEXT("");

	// Keep the request alive across frames.
	TWeakObjectPtr<AAividoGameMode> WeakThis(this);

	FHttpModule* Http = &FHttpModule::Get();
	TSharedRef<IHttpRequest, ESPMode::ThreadSafe> Req = Http->CreateRequest();
	Req->SetVerb(TEXT("POST"));
	Req->SetURL(ChatUrl);
	Req->SetHeader(TEXT("Content-Type"), TEXT("application/json"));
	const FString Payload =
		FString::Printf(TEXT("{\"message\":\"%s\"}"), *Trimmed.ReplaceCharWithEscapedChar());
	Req->SetContentAsString(Payload);
	Req->SetTimeout(120.f);
	Req->OnProcessRequestComplete().BindLambda(
		[WeakThis](FHttpRequestPtr, FHttpResponsePtr Response, bool bConnected)
		{
			if (!WeakThis.IsValid()) return;
			WeakThis->bWaitingReply = false;

			FString Reply;
			if (bConnected && Response.IsValid() && EHttpResponseCodes::IsOk(Response->GetResponseCode()))
			{
				TSharedPtr<FJsonObject> JsonObject;
				const FString Body = Response->GetContentAsString();
				const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Body);
				if (FJsonSerializer::Deserialize(Reader, JsonObject) && JsonObject.IsValid())
				{
					// Backend replies use "message" (state/mode/message envelope);
					// accept "reply" too for older gateways.
					Reply = JsonObject->GetStringField(TEXT("message"));
					if (Reply.IsEmpty())
					{
						Reply = JsonObject->GetStringField(TEXT("reply"));
					}
				}
			}
			if (Reply.IsEmpty())
			{
				Reply = TEXT("[link offline] The Aivido backend did not answer. Check the gateway service.");
			}

			WeakThis->LastReply = Reply;
			WeakThis->OnReplyChanged.Broadcast(Reply);
		});
	Req->ProcessRequest();
}

void AAividoGameMode::RequestWorkerStates()
{
	if (WorkerDirector)
	{
		WorkerDirector->RequestStates();
	}
}

void AAividoGameMode::ApplyInputMode(bool bGameAndUI)
{
	UWorld* World = GetWorld();
	APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	if (!PC) return;

	PC->bShowMouseCursor = bGameAndUI;
	if (bGameAndUI)
	{
		FInputModeGameAndUI Mode;
		Mode.SetLockMouseToViewportBehavior(EMouseLockMode::DoNotLock);
		PC->SetInputMode(Mode);
	}
	else
	{
		PC->SetInputMode(FInputModeGameOnly());
	}
}
