// Aivido V2 — player character implementation.

#include "AividoCharacter.h"

#include "AividoGameMode.h"
#include "Camera/CameraComponent.h"
#include "Components/CapsuleComponent.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/Controller.h"
#include "GameFramework/SpringArmComponent.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "InputMappingContext.h"
#include "InputActionValue.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/OverlapResult.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "TimerManager.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "AividoGameMode.h"

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
	CameraBoom->TargetArmLength = 320.f;
	CameraBoom->SocketOffset = FVector(0.f, 55.f, 70.f);
	CameraBoom->bUsePawnControlRotation = true;

	FollowCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("FollowCamera"));
	FollowCamera->SetupAttachment(CameraBoom, USpringArmComponent::SocketName);
	FollowCamera->bUsePawnControlRotation = false;

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
	// between steps. Everything is logged under AIVIDO_PROOF.
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
	auto Next = [this, Step, W]()
	{
		W->GetTimerManager().SetTimerForNextTick([this, Step]() { ProofStep(Step + 1); });
	};

	switch (Step)
	{
	case 0: // start of walk phase
		ProofWalkStart = GetActorLocation();
		UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: walk_start %s"), *ProofWalkStart.ToString());
		for (int32 i = 0; i < 30; ++i)
		{
			AddMovementInput(FVector(0.f, -1.f, 0.f), 1.f, false);
		}
		W->GetTimerManager().SetTimerForNextTick([this, Step]() { ProofStep(Step + 1); });
		break;
	case 1:
	case 2:
	case 3:
		for (int32 i = 0; i < 30; ++i)
		{
			AddMovementInput(FVector(0.f, -1.f, 0.f), 1.f, false);
		}
		Next();
		break;
	case 4: // walk done: log displacement
	{
		const FVector End = GetActorLocation();
		UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: walk_end %s disp=%.1f"), *End.ToString(),
			FVector::Dist2D(End, ProofWalkStart));
		if (APlayerController* PC = Cast<APlayerController>(Controller))
		{
			PC->ConsoleCommand(TEXT("HighResShot 2"), true);
		}
		Next();
		break;
	}
	case 5: // menu open via the real ESC handler path
		if (AAividoGameMode* GM = GetWorld()->GetAuthGameMode<AAividoGameMode>())
		{
			GM->ToggleMenu();
			UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: menu_open=%s"),
				GM->IsMenuOpen() ? TEXT("true") : TEXT("false"));
		}
		Next();
		break;
	case 6:
		if (APlayerController* PC = Cast<APlayerController>(Controller))
		{
			PC->ConsoleCommand(TEXT("HighResShot 2"), true);
		}
		Next();
		break;
	case 7: // menu close via the real handler path
		if (AAividoGameMode* GM = GetWorld()->GetAuthGameMode<AAividoGameMode>())
		{
			GM->ToggleMenu();
			UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: menu_closed=%s"),
				!GM->IsMenuOpen() ? TEXT("true") : TEXT("false"));
		}
		UE_LOG(LogTemp, Log, TEXT("AIVIDO_PROOF: done"));
		break;
	default:
		break;
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

void AAividoCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
	Super::SetupPlayerInputComponent(PlayerInputComponent);

	if (UEnhancedInputComponent* EIC = Cast<UEnhancedInputComponent>(PlayerInputComponent))
	{
		EIC->BindAction(JumpAction, ETriggerEvent::Started, this, &ACharacter::Jump);
		EIC->BindAction(JumpAction, ETriggerEvent::Completed, this, &ACharacter::StopJumping);
		EIC->BindAction(MoveAction, ETriggerEvent::Triggered, this, &AAividoCharacter::Move);
		EIC->BindAction(LookAction, ETriggerEvent::Triggered, this, &AAividoCharacter::Look);
		EIC->BindAction(RunAction, ETriggerEvent::Started, this, &AAividoCharacter::StartRun);
		EIC->BindAction(RunAction, ETriggerEvent::Completed, this, &AAividoCharacter::StopRun);
		EIC->BindAction(InteractAction, ETriggerEvent::Started, this, &AAividoCharacter::Interact);
		EIC->BindAction(MenuAction, ETriggerEvent::Started, this, &AAividoCharacter::ToggleMenu);
	}
	else
	{
		// Legacy input fallback (project ini defines axis + action mappings):
		// guarantees WASD + mouse look even with no Enhanced Input assets.
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
}

void AAividoCharacter::Interact()
{
	if (CurrentInteractTarget.IsValid())
	{
		if (AAividoGameMode* GM = GetWorld() ? GetWorld()->GetAuthGameMode<AAividoGameMode>() : nullptr)
		{
			GM->HandleInteract(this, CurrentInteractTarget.Get());
		}
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
