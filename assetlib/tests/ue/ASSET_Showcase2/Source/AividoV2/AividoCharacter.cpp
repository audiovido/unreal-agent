// Aivido V2 — player character implementation.

#include "AividoCharacter.h"

#include "AividoGameMode.h"
#include "AividoDirector.h"
#include "Camera/CameraComponent.h"
#include "Components/CapsuleComponent.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/Controller.h"
#include "GameFramework/SpringArmComponent.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "InputMappingContext.h"
#include "EnhancedActionKeyMapping.h"
#include "InputAction.h"
#include "InputModifiers.h"
#include "InputActionValue.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/OverlapResult.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "TimerManager.h"
#include "Kismet/GameplayStatics.h"
#include "GameFramework/CharacterMovementComponent.h"

AAividoCharacter::AAividoCharacter()
{
	PrimaryActorTick.bCanEverTick = true;

	GetCapsuleComponent()->InitCapsuleSize(34.f, 90.f);

	bUseControllerRotationPitch = false;
	bUseControllerRotationYaw = true;
	bUseControllerRotationRoll = false;

	GetCharacterMovement()->bOrientRotationToMovement = false;
	GetCharacterMovement()->RotationRate = FRotator(0.f, 420.f, 0.f);
	GetCharacterMovement()->JumpZVelocity = 380.f;
	GetCharacterMovement()->AirControl = 0.25f;
	GetCharacterMovement()->MaxWalkSpeed = 260.f;
	GetCharacterMovement()->BrakingDecelerationWalking = 1400.f;
	GetCharacterMovement()->MaxAcceleration = 1400.f;

	CameraBoom = CreateDefaultSubobject<USpringArmComponent>(TEXT("CameraBoom"));
	CameraBoom->SetupAttachment(RootComponent);
	// Composition: over-the-right-shoulder third person. The pawn occupies
	// the left-center of frame at a comfortable distance instead of filling
	// the camera.
	CameraBoom->TargetArmLength = 420.f;
	CameraBoom->SocketOffset = FVector(70.f, 60.f, 85.f);
	CameraBoom->bUsePawnControlRotation = true;
	CameraBoom->bEnableCameraLag = true;
	CameraBoom->CameraLagSpeed = 12.f;
	CameraBoom->CameraLagMaxDistance = 160.f;
	CameraBoom->ProbeChannel = ECC_Camera;
	CameraBoom->bDoCollisionTest = true;

	FollowCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("FollowCamera"));
	FollowCamera->SetupAttachment(CameraBoom, USpringArmComponent::SocketName);
	FollowCamera->bUsePawnControlRotation = false;
	// Cinematic focal length (natural perspective, no wide-angle distortion).
	FollowCamera->SetFieldOfView(65.f);

	// Real third-person locomotion: attach the project's mannequin +
	// ThirdPerson AnimBP when present so walking is a real walk cycle
	// (velocity-driven, no T-pose). Capsule is the guaranteed fallback.
	if (USkeletalMeshComponent* SkelMesh = GetMesh())
	{
		if (USkeletalMesh* Mannequin = LoadObject<USkeletalMesh>(nullptr,
			TEXT("/Game/Mannequin/Character/Mesh/SK_Mannequin.SK_Mannequin")))
		{
			SkelMesh->SetSkeletalMesh(Mannequin);
			if (UClass* AnimBP = LoadObject<UClass>(nullptr,
				TEXT("/Game/Mannequin/Animations/ThirdPerson_AnimBP.ThirdPerson_AnimBP_C")))
			{
				SkelMesh->SetAnimInstanceClass(AnimBP);
			}
		}
	}
}

void AAividoCharacter::BeginPlay()
{
	Super::BeginPlay();
	CurrentTargetName = TEXT("");

	// Deterministic playable spawn: the map's legacy PlayerStart sits far
	// outside the playable floor, and the room's visual floor (top at Z~63.5)
	// does not give the movement component a valid walkable surface. So the
	// character is fully self-sufficient: it spawns a transient walkable floor
	// box whose top sits at Z=200 (clear of all room geometry) and lands the
	// capsule just above it. No tracing, no map dependency; identical in PIE
	// and packaged builds.
	FloorTopZ = 200.f;
	if (HasAuthority())
	{
		if (UWorld* W = GetWorld())
		{
			if (UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube")))
			{
				FActorSpawnParameters P;
				P.ObjectFlags |= RF_Transient;
				// Box spans Z 120..200 (center 160, half-thickness 40 at scale 0.8).
				AStaticMeshActor* Floor = W->SpawnActor<AStaticMeshActor>(
					AStaticMeshActor::StaticClass(),
					FVector(0.f, 3200.f, 160.f), FRotator::ZeroRotator, P);
				if (Floor)
				{
					if (UStaticMeshComponent* SMC = Floor->GetStaticMeshComponent())
					{
						// Must be Movable BEFORE scale/location transforms, otherwise
						// SetActorScale3D/SetActorLocation silently no-op on a Static
						// component and the un-scaled 100cm cube intersects the capsule,
						// causing endless depenetration drift after spawn.
						SMC->SetMobility(EComponentMobility::Movable);
						SMC->SetStaticMesh(Cube);
						SMC->SetCollisionProfileName(TEXT("BlockAll"));
						SMC->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
						// Visual: the support box must be invisible (collision stays) —
						// otherwise the pawn visibly walks on a raw gray cube floating
						// above the room's real floor.
						SMC->SetHiddenInGame(true);
						SMC->SetCastShadow(false);
					}
					Floor->SetActorScale3D(FVector(80.f, 80.f, 0.8f));
					Floor->SetActorLocation(FVector(0.f, 3200.f, 160.f));
#if WITH_EDITOR
					Floor->SetActorLabel(TEXT("Aivido_RuntimeFloor"));
#endif
				}
			}
		}
	}
	FallingStuckTime = 0.f;
}

void AAividoCharacter::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	// First-tick reposition: land the capsule a few cm ABOVE the walkable box
	// top (FloorTopZ=200). No interpenetration -> the downward floor sweep
	// actually hits the box -> valid floor -> Walking sticks.
	if (!bSpawnRepositioned)
	{
		bSpawnRepositioned = true;
		RestZ = FloorTopZ + GetCapsuleComponent()->GetUnscaledCapsuleHalfHeight() + 1.f;
		bRestZInit = true;
		SetActorLocationAndRotation(
			FVector(0.f, 3200.f, RestZ),
			FRotator(0.f, -90.f, 0.f),
			false, nullptr, ETeleportType::TeleportPhysics);
		UE_LOG(LogTemp, Log, TEXT("AIVIDO_SPAWN: %s rest_z=%.1f"), *GetName(), RestZ);

		// Standalone validation: -AividoAutoProof schedules the proof sequence
		// shortly after spawn (boot ExecCmds run before the pawn exists).
		if (FParse::Param(FCommandLine::Get(), TEXT("AividoAutoProof")))
		{
			if (UWorld* W2 = GetWorld())
			{
				FTimerHandle AutoProofHandle;
				W2->GetTimerManager().SetTimer(AutoProofHandle, FTimerDelegate::CreateWeakLambda(this, [this]() { AividoProof(); }), 3.f, false);
			}
		}
	}

	// Deterministic spawn: no falling phase at all. This level's legacy
	// colliders interplay badly with the fall/floor pipeline (phantom
	// floors, upward rides). Flying + zero gravity + the movement
	// anchor below gives a fully deterministic pawn: idle stays put,
	// WASD walks at normal speed with the real walk animation.
	if (UCharacterMovementComponent* CMC = GetCharacterMovement())
	{
		CMC->Velocity = FVector::ZeroVector;
		CMC->GravityScale = 0.f;
		CMC->BrakingDecelerationFlying = 1400.f;
		// Walk-speed feel: same top speed as walking, so the velocity-driven
		// walk animation looks correct.
		CMC->MaxFlySpeed = 260.f;
		CMC->SetMovementMode(MOVE_Flying);
	}

	// Unstick guard: when the capsule is fully supported (zero velocity) but
	// the movement mode is still Falling (stuck floor/volume edge case),
	// re-ground it so WASD locomotion works.
	UCharacterMovementComponent* CMC = GetCharacterMovement();
	if (CMC && CMC->MovementMode == MOVE_Falling)
	{
		if (GetVelocity().IsNearlyZero(1.f))
		{
			FallingStuckTime += DeltaSeconds;
			if (FallingStuckTime > 0.25f)
			{
				CMC->SetMovementMode(MOVE_Walking);
				FallingStuckTime = 0.f;
			}
		}
		else
		{
			FallingStuckTime = 0.f;
		}
	}
	else
	{
		FallingStuckTime = 0.f;
	}

	// Anti-drift anchor: this level pushes the fresh pawn every frame with
	// ZERO reported velocity (kinematic mesh-body depenetration). The
	// zero-velocity signature separates the pusher from legitimate motion
	// (falls/jumps always have real velocity), so: no input + no velocity +
	// displacement => snap back to the anchor, all three axes.
	const FVector NowLoc = GetActorLocation();
	if (!bAnchorInit)
	{
		MovementAnchor = NowLoc;
		bAnchorInit = true;
	}
	else if (bInputThisFrame)
	{
		MovementAnchor = NowLoc;
		NoInputTime = 0.f;
	}
	else
	{
		NoInputTime += DeltaSeconds;
		const bool bZeroVel = GetVelocity().IsNearlyZero(1.f);
		// Full-XYZ enforcement: with zero gravity there is no settling phase,
		// so any uncommanded displacement (the level's zero-velocity pusher)
		// is undone on all axes while idle.
		if (NoInputTime > 0.2f && bZeroVel &&
			(FVector::Dist2D(NowLoc, MovementAnchor) > 2.f || FMath::Abs(NowLoc.Z - MovementAnchor.Z) > 2.f))
		{
			TeleportTo(MovementAnchor, GetActorRotation(), false, true);
			if (UCharacterMovementComponent* CMC2 = GetCharacterMovement())
			{
				CMC2->Velocity = FVector::ZeroVector;
			}
		}
	}
	bInputThisFrame = false;

	// Sticky deterministic mode; the level's colliders keep flipping the
	// pawn into Falling.
	if (UCharacterMovementComponent* CMC3 = GetCharacterMovement())
	{
		if (CMC3->MovementMode != MOVE_Flying)
		{
			CMC3->SetMovementMode(MOVE_Flying);
		}
	}

	UpdateInteractTarget();
}

void AAividoCharacter::AddMovementInput(FVector WorldDirection, float ScaleValue,
	bool bForceNormalAccel)
{
	Super::AddMovementInput(WorldDirection, ScaleValue, bForceNormalAccel);
	if (ScaleValue != 0.f)
	{
		bInputThisFrame = true;
	}
}

void AAividoCharacter::AividoDrive(float DirX, float DirY, int32 Frames)
{
	// Standalone validation drive: repeat AddMovementInput for N frames by
	// scheduling a lightweight timer; identical code path to WASD input.
	if (Frames <= 0)
	{
		return;
	}
	const FVector Dir = FVector(DirX, DirY, 0.f).GetSafeNormal();
	AddMovementInput(Dir, 1.f, false);
	if (UWorld* W = GetWorld())
	{
		FTimerHandle DriveHandle;
		FTimerDelegate DriveDel;
		TWeakObjectPtr<AAividoCharacter> WeakThis(this);
		DriveDel.BindWeakLambda(this, [WeakThis, Dir, Frames]()
		{
			if (WeakThis.IsValid())
			{
				WeakThis->AividoDrive(Dir.X, Dir.Y, Frames - 1);
			}
		});
		W->GetTimerManager().SetTimer(DriveHandle, DriveDel, 0.016f, false);
	}
}

void AAividoCharacter::AividoProof()
{
	// Standalone validation sequence, spaced with timers so frames render
	// between steps. Everything is logged under AIVIDO_PROOF: main menu start,
	// walk unlock check, pause open/close, conversation open/close and camera
	// restore are all driven through the real handlers and logged for the log
	// file to prove deterministic state transitions. Screenshots are taken in
	// before/after pairs at the SAME camera position so the menu/conversation
	// overlay paint is verifiable by direct pixel comparison.
	UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: begin"));
	ProofStep(0);
}

void AAividoCharacter::ProofStep(int32 Step)
{
	UWorld* W = GetWorld();
	if (!W)
	{
		return;
	}
	auto Next = [this, W, Step]()
	{
		W->GetTimerManager().SetTimerForNextTick([this, Step]() { ProofStep(Step + 1); });
	};
	auto Delay = [this, W](float Seconds, int32 NextStep)
	{
		FTimerHandle H;
		W->GetTimerManager().SetTimer(H, FTimerDelegate::CreateWeakLambda(this,
			[this, NextStep]() { ProofStep(NextStep); }), Seconds, false);
	};
	// Deterministic rest height for teleports (capsule above the walkable box).
	const float TeleportZ = bRestZInit ? RestZ : 291.f;

	switch (Step)
	{
	case 0: // boot: main menu open — capture, then close at the same position
		if (AAividoGameMode* GM = W->GetAuthGameMode<AAividoGameMode>())
		{
			UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: boot menu_open=%s"),
				GM->IsMenuOpen() ? TEXT("true") : TEXT("false"));
		}
		if (APlayerController* PC = Cast<APlayerController>(Controller))
		{
			PC->ConsoleCommand(TEXT("HighResShot 2"), true);
		}
		Delay(0.8f, 1);
		break;

	case 1: // start the session through the real ESC handler; same-position control shot
	{
		if (AAividoGameMode* GM = W->GetAuthGameMode<AAividoGameMode>())
		{
			if (GM->IsMenuOpen())
			{
				GM->ToggleMenu();
			}
			UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: started menu_open=%s"),
				GM->IsMenuOpen() ? TEXT("true") : TEXT("false"));
		}
		if (APlayerController* PC = Cast<APlayerController>(Controller))
		{
			PC->ConsoleCommand(TEXT("HighResShot 2"), true);
		}
		ProofWalkStart = GetActorLocation();
		UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: walk_start %s"), *ProofWalkStart.ToString());
		for (int32 i = 0; i < 30; ++i)
		{
			AddMovementInput(FVector(0.f, -1.f, 0.f), 1.f, false);
		}
		Next();
		break;
	}
	case 2:
		for (int32 i = 0; i < 30; ++i)
		{
			AddMovementInput(FVector(0.f, -1.f, 0.f), 1.f, false);
		}
		Next();
		break;
	case 3: // walk done: log displacement (proves input is NOT stuck locked)
	{
		const FVector End = GetActorLocation();
		UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: walk_end %s disp=%.1f"), *End.ToString(),
			FVector::Dist2D(End, ProofWalkStart));
		Delay(0.3f, 4);
		break;
	}
	case 4: // park the pawn in the lit room, then capture a no-UI control frame
	{
		SetActorLocation(FVector(0.f, 2600.f, TeleportZ), false, nullptr, ETeleportType::TeleportPhysics);
		MovementAnchor = GetActorLocation();
		bAnchorInit = false;
		if (UCharacterMovementComponent* CMC2 = GetCharacterMovement())
		{
			CMC2->Velocity = FVector::ZeroVector;
		}
		Delay(0.6f, 5);
		break;
	}
	case 5: // gameplay control shot at the parked position (no menu)
		if (APlayerController* PC = Cast<APlayerController>(Controller))
		{
			PC->ConsoleCommand(TEXT("HighResShot 2"), true);
		}
		Delay(0.5f, 6);
		break;
	case 6: // open the pause menu via the real ESC handler
		if (AAividoGameMode* GM = W->GetAuthGameMode<AAividoGameMode>())
		{
			GM->ToggleMenu();
			UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: pause_open=%s"),
				GM->IsMenuOpen() ? TEXT("true") : TEXT("false"));
		}
		Delay(0.8f, 7);
		break;
	case 7: // capture the pause menu (same position as the control shot)
		if (APlayerController* PC = Cast<APlayerController>(Controller))
		{
			PC->ConsoleCommand(TEXT("HighResShot 2"), true);
		}
		Delay(0.8f, 8);
		break;
	case 8: // resume via the real handler
		if (AAividoGameMode* GM = W->GetAuthGameMode<AAividoGameMode>())
		{
			GM->ToggleMenu();
			UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: paused_closed=%s"),
				GM->IsMenuOpen() ? TEXT("true") : TEXT("false"));
		}
		Delay(0.6f, 9);
		break;
	case 9: // stand in front of the director (teleport + re-anchor at rest height)
	{
		AActor* Dir = UGameplayStatics::GetActorOfClass(W, AAividoDirector::StaticClass());
		if (Dir)
		{
			const FVector Target = Dir->GetActorLocation() + FVector(0.f, 260.f, 0.f);
			const FVector Final(Target.X, Target.Y, TeleportZ);
			SetActorLocation(Final, false, nullptr, ETeleportType::TeleportPhysics);
			MovementAnchor = Final;
			bAnchorInit = false; // re-anchor on the next tick
			UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: teleport %s dir=%s"),
				*Final.ToString(), *Dir->GetActorLocation().ToString());
		}
		else
		{
			UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: DIRECTOR NOT FOUND"));
		}
		Delay(0.6f, 10);
		break;
	}
	case 10: // open the conversation through the real interaction path
	{
		AActor* Dir = UGameplayStatics::GetActorOfClass(W, AAividoDirector::StaticClass());
		if (AAividoGameMode* GM = W->GetAuthGameMode<AAividoGameMode>())
		{
			if (Dir)
			{
				GM->HandleInteract(this, Dir);
			}
			UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: conv_open=%s camera=%d"),
				GM->IsConversationOpen() ? TEXT("true") : TEXT("false"),
				static_cast<int32>(GM->GetCameraMode()));
		}
		Delay(1.5f, 11); // wait for the camera blend to finish
		break;
	}
	case 11: // verify the view target is the director conversation camera
	{
		if (APlayerController* PC = Cast<APlayerController>(Controller))
		{
			AActor* VT = PC->GetViewTarget();
			UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: conv_camera_target=%s"),
				VT ? *VT->GetName() : TEXT("none"));
			PC->ConsoleCommand(TEXT("HighResShot 2"), true);
		}
		Delay(1.0f, 12);
		break;
	}
	case 12: // ESC closes the conversation first
	{
		if (AAividoGameMode* GM = W->GetAuthGameMode<AAividoGameMode>())
		{
			GM->ToggleMenu();
			UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: conv_closed=%s menu_open=%s"),
				GM->IsConversationOpen() ? TEXT("true") : TEXT("false"),
				GM->IsMenuOpen() ? TEXT("true") : TEXT("false"));
		}
		Delay(1.5f, 13); // wait for the restore blend
		break;
	}
	case 13: // verify the camera restored to the pawn
	{
		if (APlayerController* PC = Cast<APlayerController>(Controller))
		{
			AActor* VT = PC->GetViewTarget();
			APawn* Pawn = PC->GetPawn();
			UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: restored_camera=%s is_pawn=%s"),
				VT ? *VT->GetName() : TEXT("none"),
				(Pawn && VT == Pawn) ? TEXT("true") : TEXT("false"));
			PC->ConsoleCommand(TEXT("HighResShot 2"), true);
		}
		UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: done"));
		break;
	}
	default:
		break;
	}
}

void AAividoCharacter::PossessedBy(AController* NewController)
{
	Super::PossessedBy(NewController);
	// Presentation only: first frame must frame the room interior (director
	// sits at ~Y=700), not the void wall behind the spawn point.
	if (APlayerController* PC = Cast<APlayerController>(NewController))
	{
		FVector ToRoom = FVector(0.f, 700.f, 0.f) - GetActorLocation();
		ToRoom.Z = 0.f;
		if (ToRoom.SizeSquared() > 1.f)
		{
			PC->SetControlRotation(ToRoom.Rotation());
			UE_LOG(LogTemp, Log, TEXT("AIVIDO_FACE: yaw=%.0f pitch=%.0f"),
				ToRoom.Rotation().Yaw, ToRoom.Rotation().Pitch);
		}
	}
}

void AAividoCharacter::NotifyControllerChanged()
{
	Super::NotifyControllerChanged();

	if (const APlayerController* PC = Cast<APlayerController>(Controller))
	{
		if (UEnhancedInputLocalPlayerSubsystem* Subsystem =
			ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(PC->GetLocalPlayer()))
		{
			if (DefaultMappingContext)
			{
				Subsystem->AddMappingContext(DefaultMappingContext, 0);
			}
		}
	}
}

// REAL INPUT FIX: the project ships no Enhanced Input assets (no IMC / no
// UInputAction uassets), but the Enhanced Input plugin is enabled — so
// PlayerInputComponent IS an UEnhancedInputComponent and Enhanced Input
// IGNORES the legacy DefaultInput.ini mappings entirely. Result: real
// WASD/mouse/ESC/E never reached the character in any build; every earlier
// "pass" was handler-driven. Fix: author the real Enhanced Input mapping
// programmatically at possession (no editor, no uassets needed).
void AAividoCharacter::EnsureEnhancedInput()
{
	if (MoveAction) return; // built once

	MoveAction = NewObject<UInputAction>(this, TEXT("IA_Aivido_Move"));
	MoveAction->ValueType = EInputActionValueType::Axis2D;
	LookAction = NewObject<UInputAction>(this, TEXT("IA_Aivido_Look"));
	LookAction->ValueType = EInputActionValueType::Axis2D;
	JumpAction = NewObject<UInputAction>(this, TEXT("IA_Aivido_Jump"));
	RunAction = NewObject<UInputAction>(this, TEXT("IA_Aivido_Run"));
	InteractAction = NewObject<UInputAction>(this, TEXT("IA_Aivido_Interact"));
	MenuAction = NewObject<UInputAction>(this, TEXT("IA_Aivido_Menu"));

	DefaultMappingContext = NewObject<UInputMappingContext>(this, TEXT("IMC_Aivido"));

	auto Map = [this](UInputAction* Action, const FKey& Key, const TArray<UInputModifier*>& Mods)
	{
		if (FEnhancedActionKeyMapping* M = &DefaultMappingContext->MapKey(Action, Key))
		{
			M->Modifiers = Mods;
		}
	};

	// WASD -> 2D move (W/S swizzled into Y, A/D on X; S/A negated)
	UInputModifierSwizzleAxis* SwizW = NewObject<UInputModifierSwizzleAxis>(DefaultMappingContext);
	SwizW->Order = EInputAxisSwizzle::YXZ;
	UInputModifierSwizzleAxis* SwizS = NewObject<UInputModifierSwizzleAxis>(DefaultMappingContext);
	SwizS->Order = EInputAxisSwizzle::YXZ;
	UInputModifierNegate* NegS = NewObject<UInputModifierNegate>(DefaultMappingContext);
	UInputModifierNegate* NegA = NewObject<UInputModifierNegate>(DefaultMappingContext);
	Map(MoveAction, EKeys::W, { SwizW });
	Map(MoveAction, EKeys::S, { SwizS, NegS });
	Map(MoveAction, EKeys::D, {});
	Map(MoveAction, EKeys::A, { NegA });

	// Mouse look: X yaw; Y pitch (swizzled + negated for natural invert)
	UInputModifierSwizzleAxis* SwizLook = NewObject<UInputModifierSwizzleAxis>(DefaultMappingContext);
	SwizLook->Order = EInputAxisSwizzle::YXZ;
	UInputModifierNegate* NegLook = NewObject<UInputModifierNegate>(DefaultMappingContext);
	Map(LookAction, EKeys::Mouse2D, {});
	Map(LookAction, EKeys::MouseX, {});
	Map(LookAction, EKeys::MouseY, { SwizLook, NegLook });

	Map(JumpAction, EKeys::SpaceBar, {});
	Map(RunAction, EKeys::LeftShift, {});
	Map(InteractAction, EKeys::E, {});
	Map(MenuAction, EKeys::Escape, {});
}

void AAividoCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
	Super::SetupPlayerInputComponent(PlayerInputComponent);

	if (UEnhancedInputComponent* EIC = Cast<UEnhancedInputComponent>(PlayerInputComponent))
	{
		EnsureEnhancedInput();
		EIC->BindAction(MoveAction, ETriggerEvent::Triggered, this, &AAividoCharacter::Move);
		EIC->BindAction(LookAction, ETriggerEvent::Triggered, this, &AAividoCharacter::Look);
		EIC->BindAction(JumpAction, ETriggerEvent::Started, this, &ACharacter::Jump);
		EIC->BindAction(JumpAction, ETriggerEvent::Completed, this, &ACharacter::StopJumping);
		EIC->BindAction(RunAction, ETriggerEvent::Started, this, &AAividoCharacter::StartRun);
		EIC->BindAction(RunAction, ETriggerEvent::Completed, this, &AAividoCharacter::StopRun);
		EIC->BindAction(InteractAction, ETriggerEvent::Started, this, &AAividoCharacter::Interact);
		EIC->BindAction(MenuAction, ETriggerEvent::Started, this, &AAividoCharacter::ToggleMenu);

		// Register the programmatic IMC with the local player's input stack.
		if (const APlayerController* PC = Cast<APlayerController>(Controller))
		{
			if (UEnhancedInputLocalPlayerSubsystem* Subsystem =
				ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(PC->GetLocalPlayer()))
			{
				Subsystem->AddMappingContext(DefaultMappingContext, 0);
			}
		}
	}
	else
	{
		// Non-Enhanced builds: the project ini fully defines these mappings.
		PlayerInputComponent->BindAxis("MoveForward", this, &AAividoCharacter::MoveForward);
		PlayerInputComponent->BindAxis("MoveRight", this, &AAividoCharacter::MoveRight);
		PlayerInputComponent->BindAxis("Turn", this, &AAividoCharacter::LookYaw);
		PlayerInputComponent->BindAxis("LookUp", this, &AAividoCharacter::LookPitch);
		PlayerInputComponent->BindAction("Jump", IE_Pressed, this, &ACharacter::Jump);
		PlayerInputComponent->BindAction("Jump", IE_Released, this, &ACharacter::StopJumping);
		PlayerInputComponent->BindAction("Run", IE_Pressed, this, &AAividoCharacter::StartRun);
		PlayerInputComponent->BindAction("Run", IE_Released, this, &AAividoCharacter::StopRun);
		PlayerInputComponent->BindAction("Interact", IE_Pressed, this, &AAividoCharacter::Interact);
		PlayerInputComponent->BindAction("Menu", IE_Pressed, this, &AAividoCharacter::ToggleMenu);
	}
}

void AAividoCharacter::Move(const FInputActionValue& Value)
{
	const FVector2D Axis = Value.Get<FVector2D>();
	if (Controller)
	{
		const FRotator YawRotation(0.f, Controller->GetControlRotation().Yaw, 0.f);
		const FVector Forward = FRotationMatrix(YawRotation).GetUnitAxis(EAxis::X);
		const FVector Right = FRotationMatrix(YawRotation).GetUnitAxis(EAxis::Y);
		AddMovementInput(Forward, Axis.Y);
		AddMovementInput(Right, Axis.X);
		bInputThisFrame = true;
	}
}

void AAividoCharacter::Look(const FInputActionValue& Value)
{
	const FVector2D Axis = Value.Get<FVector2D>();
	AddControllerYawInput(Axis.X);
	AddControllerPitchInput(Axis.Y);
	// Standard third-person pitch limits: never flip over the top.
	if (Controller)
	{
		FRotator R = Controller->GetControlRotation();
		R.Pitch = FMath::Clamp(FRotator::NormalizeAxis(R.Pitch), -89.f, 89.f);
		Controller->SetControlRotation(R);
	}
}

void AAividoCharacter::StartRun()
{
	GetCharacterMovement()->MaxWalkSpeed = 520.f;
}

void AAividoCharacter::StopRun()
{
	GetCharacterMovement()->MaxWalkSpeed = 260.f;
}

void AAividoCharacter::MoveForward(float V)
{
	if (Controller && V != 0.f)
	{
		const FRotator YawRotation(0.f, Controller->GetControlRotation().Yaw, 0.f);
		AddMovementInput(FRotationMatrix(YawRotation).GetUnitAxis(EAxis::X), V);
		bInputThisFrame = true;
	}
}

void AAividoCharacter::MoveRight(float V)
{
	if (Controller && V != 0.f)
	{
		const FRotator YawRotation(0.f, Controller->GetControlRotation().Yaw, 0.f);
		AddMovementInput(FRotationMatrix(YawRotation).GetUnitAxis(EAxis::Y), V);
		bInputThisFrame = true;
	}
}

void AAividoCharacter::LookYaw(float V)
{
	AddControllerYawInput(V);
}

void AAividoCharacter::LookPitch(float V)
{
	AddControllerPitchInput(V);
	if (Controller)
	{
		FRotator R = Controller->GetControlRotation();
		R.Pitch = FMath::Clamp(FRotator::NormalizeAxis(R.Pitch), -89.f, 89.f);
		Controller->SetControlRotation(R);
	}
}

void AAividoCharacter::Interact()
{
	// Interaction is a gameplay-only action: never while paused, at the main
	// menu or while the conversation panel is open (E must not stack panels).
	UWorld* World = GetWorld();
	AAividoGameMode* GM = World ? World->GetAuthGameMode<AAividoGameMode>() : nullptr;
	if (!GM || GM->GetUIState() != EAividoUIState::Gameplay) return;

	if (CurrentInteractTarget.IsValid())
	{
		GM->HandleInteract(this, CurrentInteractTarget.Get());
	}
}

void AAividoCharacter::ToggleMenu()
{
	if (AAividoGameMode* GM = GetWorld() ? GetWorld()->GetAuthGameMode<AAividoGameMode>() : nullptr)
	{
		GM->ToggleMenu();
	}
}

void AAividoCharacter::UpdateInteractTarget()
{
	UWorld* World = GetWorld();
	if (!World) return;

	FCollisionQueryParams Params(FName(TEXT("AividoInteract")), false, this);
	TArray<FOverlapResult> Overlaps;
	const FVector Start = GetActorLocation();
	const FVector ProbeCenter = Start + GetActorForwardVector() * (InteractRange * 0.55f);

	// Radial overlap in front of the player: approaching (not exactly staring
	// at) the director counts, which is how people actually walk up to talk.
	World->OverlapMultiByChannel(Overlaps, ProbeCenter, FQuat::Identity, ECC_Visibility,
		FCollisionShape::MakeSphere(InteractRange * 0.55f), Params);

	AActor* Best = nullptr;
	float BestDist = TNumericLimits<float>::Max();
	// Labels are editor-only; the packaged game falls back to actor names.
#if WITH_EDITOR
	auto LabelOf = [](const AActor* A) { return A ? A->GetActorLabel() : FString(); };
#else
	auto LabelOf = [](const AActor* A) { return A ? A->GetName() : FString(); };
#endif
	for (const FOverlapResult& Overlap : Overlaps)
	{
		AActor* HitActor = Overlap.GetActor();
		if (!HitActor || HitActor == this) continue;
		const FString Name = HitActor->GetName();
		const FString Label = LabelOf(HitActor);
		if (!(Name.StartsWith(TEXT("AVIDO_Human")) || Name.StartsWith(TEXT("AVIDO_Agent")) ||
			Label.StartsWith(TEXT("AVIDO_Human")) || Label.StartsWith(TEXT("AVIDO_Agent")) ||
			Name.StartsWith(TEXT("Aivido_Interactable")) || Label.StartsWith(TEXT("Aivido_Interactable"))))
		{
			continue;
		}
		const float Dist = FVector::Dist(Start, HitActor->GetActorLocation());
		if (Dist < BestDist)
		{
			BestDist = Dist;
			Best = HitActor;
		}
	}

	if (Best != CurrentInteractTarget.Get())
	{
		CurrentInteractTarget = Best;
		const FString NewName = Best ? LabelOf(Best) : FString(TEXT(""));
		if (CurrentTargetName != NewName)
		{
			CurrentTargetName = NewName;
			OnInteractTargetChanged.Broadcast(CurrentTargetName);
		}
	}
}