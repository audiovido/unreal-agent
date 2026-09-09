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
#include "Camera/PlayerCameraManager.h"
#include "HttpModule.h"
#include "Interfaces/IHttpRequest.h"
#include "Interfaces/IHttpResponse.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/Scene.h"
#include "Engine/DirectionalLight.h"
#include "Engine/SkyLight.h"
#include "Engine/PointLight.h"
#include "Components/LightComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/PointLightComponent.h"

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
	UIState = EAividoUIState::Gameplay;
	CameraMode = EAividoCameraMode::Gameplay;

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

	// 4) Presentation pass: the shipped AividoHQ map has no post-process and
	//    no light rig of its own, so the packaged game rendered raw engine
	//    defaults — auto-exposure blew the room out to white and everything
	//    read as a flat test level. This rig gives the intended interior HQ
	//    presentation deterministically, in editor and packaged builds.
	if (HasAuthority())
	{
		FActorSpawnParameters SP;
		SP.ObjectFlags |= RF_Transient;
		SP.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;

		// Exposure lock: MANUAL exposure (fixed EV) so the room can no longer
		// blow out to white. Manual also skips the eye-adaptation histogram
		// downsample chain entirely — that chain GPU-hung on this machine's
		// D3D12 driver (38s stall -> engine force-exit).
		if (APostProcessVolume* PPV = World->SpawnActor<APostProcessVolume>(
			APostProcessVolume::StaticClass(), FVector(0.f, 3200.f, 200.f), FRotator::ZeroRotator, SP))
		{
			PPV->bUnbound = true;
			FPostProcessSettings& S = PPV->Settings;
			S.bOverride_AutoExposureMethod = true;
			S.AutoExposureMethod = EAutoExposureMethod::AEM_Manual;
			S.bOverride_AutoExposureBias = true;
			S.AutoExposureBias = 4.0f;
			S.bOverride_MotionBlurAmount = true;
			S.MotionBlurAmount = 0.f;
			S.bOverride_VignetteIntensity = true;
			S.VignetteIntensity = 0.35f;
		}

		// Key light: a sun-angle directional through the room, warm neutral.
		if (ADirectionalLight* Sun = World->SpawnActor<ADirectionalLight>(
			ADirectionalLight::StaticClass(), FVector(0.f, 3200.f, 600.f), FRotator(-42.f, 35.f, 0.f), SP))
		{
			if (ULightComponent* LC = Sun->GetLightComponent())
			{
				LC->SetMobility(EComponentMobility::Movable);
				LC->SetIntensity(16.0f);
				LC->SetLightColor(FLinearColor(1.0f, 0.96f, 0.90f));
				LC->SetCastShadows(true);
			}
		}

		// Fill: soft ambient so shadows are not crushed black. Recaptured at the
		// end of this rig — capturing before the practical lights exist would
		// bake a black hemisphere and leave the room permanently dark.
		ASkyLight* SkyActor = nullptr;
		if (ASkyLight* Sky = World->SpawnActor<ASkyLight>(
			ASkyLight::StaticClass(), FVector(0.f, 3200.f, 500.f), FRotator::ZeroRotator, SP))
		{
			if (USkyLightComponent* SC = Sky->GetLightComponent())
			{
				SC->SetMobility(EComponentMobility::Movable);
				SC->SetIntensity(8.0f);
				SC->SetLightColor(FLinearColor(0.75f, 0.82f, 1.0f));
				SC->SetCastShadows(false);
				SkyActor = Sky;
			}
		}

		// Practical interior lights over the four stations (cool console,
		// warm desk, cyan and violet accents from the room's material palette).
		const struct FStationLight { FVector Pos; FLinearColor C; } Stations[] =
		{
			{ FVector(   0.f,  700.f, 420.f), FLinearColor(0.55f, 0.75f, 1.0f) },
			{ FVector(1400.f, 3200.f, 420.f), FLinearColor(1.0f, 0.75f, 0.40f) },
			{ FVector(-1400.f, 3200.f, 420.f), FLinearColor(0.45f, 0.85f, 1.0f) },
			{ FVector(   0.f, 4900.f, 420.f), FLinearColor(0.90f, 0.80f, 1.0f) },
		};
		for (const FStationLight& Station : Stations)
		{
			if (APointLight* PL = World->SpawnActor<APointLight>(
				APointLight::StaticClass(), Station.Pos, FRotator::ZeroRotator, SP))
			{
				if (UPointLightComponent* PLC = Cast<UPointLightComponent>(PL->GetLightComponent()))
				{
					PLC->SetMobility(EComponentMobility::Movable);
					PLC->SetIntensity(12000.f);
					PLC->SetLightColor(Station.C);
					PLC->SetAttenuationRadius(2800.f);
					PLC->SetCastShadows(true);
				}
			}
		}

		// Recapture the sky/ambient AFTER the practical lights exist so the
		// fill hemisphere holds real room light instead of a baked black void.
		if (SkyActor)
		{
			SkyActor->GetLightComponent()->RecaptureSky();
		}

		// Presentation: face the player into the room interior (director at
		// ~Y=700) so the first frame frames the room, not the void. Deferred —
		// GameMode BeginPlay runs before the pawn possesses.
		TWeakObjectPtr<UWorld> WorldWeak(World);
		FTimerHandle FaceTimer;
		World->GetTimerManager().SetTimer(FaceTimer, FTimerDelegate::CreateLambda([WorldWeak]()
		{
			if (!WorldWeak.IsValid()) return;
			if (APlayerController* PC = WorldWeak->GetFirstPlayerController())
			{
				if (APawn* P = PC->GetPawn())
				{
					FVector ToRoom = FVector(0.f, 700.f, 0.f) - P->GetActorLocation();
					ToRoom.Z = 0.f;
					if (ToRoom.SizeSquared() > 1.f)
					{
						PC->SetControlRotation(ToRoom.Rotation());
					}
				}
			}
		}), 1.0f, false);
	}

	// 5) Boot start screen. Standard production flow: the experience opens on
	//    the main menu (Start Session / Quit); ESC also starts the session.
	//    Deferred a short beat out of BeginPlay: widgets added to the viewport
	//    during world bring-up can miss their first paint (the pause re-add
	//    renders fine, the boot-time add did not), so let the viewport settle
	//    one frame before AddToViewport.
	TWeakObjectPtr<AAividoGameMode> WeakThis(this);
	FTimerHandle MenuTimer;
	World->GetTimerManager().SetTimer(MenuTimer, FTimerDelegate::CreateWeakLambda(this, [WeakThis]()
	{
		if (WeakThis.IsValid())
		{
			WeakThis->ShowMainMenu();
		}
	}), 0.5f, false);
}

// ---------------------------------------------------------------------------
// UI / camera state machine — the single place transitions are applied.
// ---------------------------------------------------------------------------

void AAividoGameMode::SetUIState(EAividoUIState NewState)
{
	if (UIState == NewState) return;
	const EAividoUIState Prev = UIState;
	UIState = NewState;

	UWorld* World = GetWorld();
	APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;

	// ---- Camera transitions ----
	if (NewState == EAividoUIState::Conversation && CameraMode != EAividoCameraMode::ConversationFocus)
	{
		if (PC && Director)
		{
			if (APawn* Pawn = PC->GetPawn())
			{
				Director->FacePlayer(Pawn);
				Director->PlaceConversationCamera(Pawn);
				PC->SetViewTargetWithBlend(Director, CameraBlendTime,
					EViewTargetBlendFunction::VTBlend_Cubic, 1.f, false);
			}
		}
		CameraMode = EAividoCameraMode::ConversationFocus;
	}
	else if (NewState == EAividoUIState::Gameplay && CameraMode == EAividoCameraMode::ConversationFocus)
	{
		// Always restore to the player camera when leaving a conversation —
		// never leave the view target stuck on the director.
		if (PC)
		{
			if (APawn* Pawn = PC->GetPawn())
			{
				PC->SetViewTargetWithBlend(Pawn, CameraBlendTime,
					EViewTargetBlendFunction::VTBlend_Cubic, 1.f, false);
			}
		}
		CameraMode = EAividoCameraMode::Gameplay;
	}

	// ---- Input mode / cursor / movement locks ----
	const bool bUI = (NewState != EAividoUIState::Gameplay);
	if (PC)
	{
		PC->bShowMouseCursor = bUI;
		PC->SetIgnoreMoveInput(bUI);
		PC->SetIgnoreLookInput(bUI);
		if (bUI)
		{
			FInputModeGameAndUI Mode;
			Mode.SetLockMouseToViewportBehavior(EMouseLockMode::DoNotLock);
			Mode.SetHideCursorDuringCapture(false);
			PC->SetInputMode(Mode);
		}
		else
		{
			PC->SetInputMode(FInputModeGameOnly());
		}
	}

	// ---- Notify listeners (HUD hides prompts when menus/conversation open) ----
	const bool bMenuNow = (NewState == EAividoUIState::MainMenu || NewState == EAividoUIState::Pause);
	const bool bMenuPrev = (Prev == EAividoUIState::MainMenu || Prev == EAividoUIState::Pause);
	if (bMenuNow != bMenuPrev)
	{
		OnMenuStateChanged.Broadcast(bMenuNow);
	}

	const bool bConvNow = (NewState == EAividoUIState::Conversation);
	const bool bConvPrev = (Prev == EAividoUIState::Conversation);
	if (bConvNow != bConvPrev)
	{
		OnConversationChanged.Broadcast(bConvNow);
	}

	UE_LOG(LogTemp, Log, TEXT("AIVIDO_STATE: %d -> %d (camera=%d, cursor=%d)"),
		static_cast<int32>(Prev), static_cast<int32>(NewState),
		static_cast<int32>(CameraMode), bUI ? 1 : 0);
}

// ---------------------------------------------------------------------------
// Interaction
// ---------------------------------------------------------------------------

void AAividoGameMode::HandleInteract(AActor* InstigatorActor, AActor* Target)
{
	if (UIState != EAividoUIState::Gameplay) return; // no interaction while paused / menu / typing
	if (!Target) return;

	AAividoDirector* TargetDirector = Cast<AAividoDirector>(Target);
	if (TargetDirector)
	{
		TargetDirector->Focus();
		OpenConversation();
	}
}

// ---------------------------------------------------------------------------
// Menus (main menu at boot + ESC pause overlay share the same widget)
// ---------------------------------------------------------------------------

void AAividoGameMode::ShowMainMenu()
{
	UWorld* World = GetWorld();
	APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	if (!PC) return;

	if (!MenuWidget && MenuWidgetClass)
	{
		MenuWidget = CreateWidget<UUserWidget>(PC, MenuWidgetClass);
	}

	if (MenuWidget)
	{
		if (UAividoMenuWidget* Menu = Cast<UAividoMenuWidget>(MenuWidget))
		{
			Menu->SetMainMenuMode(true);
		}
		if (!MenuWidget->IsInViewport())
		{
			MenuWidget->AddToViewport(30);
		}
		if (UAividoMenuWidget* Menu = Cast<UAividoMenuWidget>(MenuWidget))
		{
			Menu->NotifyOpened();
		}
		UE_LOG(LogTemp, Log, TEXT("AIVIDO_UI: main_menu vp=%d vis=%d geo=%s"),
			MenuWidget->IsInViewport() ? 1 : 0,
			MenuWidget->GetIsVisible() ? 1 : 0,
			*MenuWidget->GetCachedGeometry().GetLocalSize().ToString());
	}

	SetUIState(EAividoUIState::MainMenu);
}

void AAividoGameMode::OpenPauseMenu()
{
	UWorld* World = GetWorld();
	APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	if (!PC) return;

	if (!MenuWidget && MenuWidgetClass)
	{
		MenuWidget = CreateWidget<UUserWidget>(PC, MenuWidgetClass);
	}

	if (MenuWidget)
	{
		if (UAividoMenuWidget* Menu = Cast<UAividoMenuWidget>(MenuWidget))
		{
			Menu->SetMainMenuMode(false);
		}
		if (!MenuWidget->IsInViewport())
		{
			MenuWidget->AddToViewport(30);
		}
		if (UAividoMenuWidget* Menu = Cast<UAividoMenuWidget>(MenuWidget))
		{
			Menu->NotifyOpened();
		}
		UE_LOG(LogTemp, Log, TEXT("AIVIDO_UI: pause_menu vp=%d vis=%d geo=%s"),
			MenuWidget->IsInViewport() ? 1 : 0,
			MenuWidget->GetIsVisible() ? 1 : 0,
			*MenuWidget->GetCachedGeometry().GetLocalSize().ToString());
	}

	SetUIState(EAividoUIState::Pause);
}

void AAividoGameMode::CloseMenu()
{
	if (MenuWidget && MenuWidget->IsInViewport())
	{
		MenuWidget->RemoveFromParent();
	}
	SetUIState(EAividoUIState::Gameplay);
}

void AAividoGameMode::ToggleMenu()
{
	// ESC steps down one UI level at a time: conversation -> pause -> gameplay.
	switch (UIState)
	{
	case EAividoUIState::Conversation:
		CloseConversation();
		break;
	case EAividoUIState::MainMenu:
	case EAividoUIState::Pause:
		CloseMenu();
		break;
	case EAividoUIState::Gameplay:
		OpenPauseMenu();
		break;
	}
}

// ---------------------------------------------------------------------------
// Conversation
// ---------------------------------------------------------------------------

void AAividoGameMode::OpenConversation()
{
	if (UIState != EAividoUIState::Gameplay) return; // never stack over menus

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
		UE_LOG(LogTemp, Log, TEXT("AIVIDO_UI: conversation vp=%d vis=%d geo=%s"),
			ConversationWidget->IsInViewport() ? 1 : 0,
			ConversationWidget->GetIsVisible() ? 1 : 0,
			*ConversationWidget->GetCachedGeometry().GetLocalSize().ToString());
	}

	// Camera blend + input lock + cursor happen inside SetUIState.
	SetUIState(EAividoUIState::Conversation);
}

void AAividoGameMode::CloseConversation()
{
	if (UIState != EAividoUIState::Conversation) return;

	if (ConversationWidget && ConversationWidget->IsInViewport())
	{
		ConversationWidget->RemoveFromParent();
	}

	// Camera restore + input restore happen inside SetUIState.
	SetUIState(EAividoUIState::Gameplay);
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