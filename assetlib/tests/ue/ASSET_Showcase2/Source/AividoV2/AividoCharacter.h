// Aivido V2 — player character with real locomotion + interaction traces.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "AividoCharacter.generated.h"

class UInputMappingContext;
class UInputAction;
struct FInputActionValue;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnInteractTargetChanged, const FString&, TargetName);

/**
 * Playable player character for Aivido HQ.
 *
 * - Enhanced Input driven movement (WASD + mouse look, Shift run, Space jump)
 * - Interaction trace every frame; nearest Aivido interactable becomes the
 *   current interaction target (used for the HUD prompt + [E] interaction).
 * - Locomotion comes from the project's ThirdPerson AnimBP via the
 *   default anim instance class set by the GameMode, so walk/run transitions
 *   are driven by real character velocity.
 */
UCLASS()
class AIVIDOV2_API AAividoCharacter : public ACharacter
{
	GENERATED_BODY()

public:
	AAividoCharacter();

	/** Camera boom (third-person follow). */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Aivido|Camera")
	class USpringArmComponent* CameraBoom;

	/** Follow camera. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Aivido|Camera")
	class UCameraComponent* FollowCamera;

	/** Interaction range in cm. */
	UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Aivido|Interaction")
	float InteractRange = 420.f;

	/** Current interactable focus (director or prop), updated per tick. */
	UPROPERTY(BlueprintReadOnly, Category = "Aivido|Interaction")
	FString CurrentTargetName;

	/** Fired whenever the interaction focus changes. */
	UPROPERTY(BlueprintAssignable, Category = "Aivido|Interaction")
	FOnInteractTargetChanged OnInteractTargetChanged;

	/** Actor the player should interact with via E (director support lives in GameMode/HUD). */
	UPROPERTY(BlueprintReadOnly, Category = "Aivido|Interaction")
	TWeakObjectPtr<AActor> CurrentInteractTarget;

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;
	virtual void NotifyControllerChanged() override;
	virtual void PossessedBy(AController* NewController) override;
	virtual void SetupPlayerInputComponent(class UInputComponent* PlayerInputComponent) override;

	/** Authors the real Enhanced Input actions + mapping context (no uassets exist). */
	void EnsureEnhancedInput();

	void Move(const FInputActionValue& Value);
	void Look(const FInputActionValue& Value);

	// Legacy input fallback handlers (non-Enhanced path).
	void MoveForward(float V);
	void MoveRight(float V);
	void LookYaw(float V);
	void LookPitch(float V);
	void StartRun();
	void StopRun();
	void Interact();
	void ToggleMenu();

	// Debug exec: programmatic WASD drive for standalone validation
	// (exercises the same AddMovementInput path as keyboard input).
	UFUNCTION(Exec)
	void AividoDrive(float DirX, float DirY, int32 Frames = 30);

	// Debug exec: full standalone validation sequence (main menu start, walk
	// displacement, pause open/close, conversation open/close, camera restore).
	UFUNCTION(Exec)
	void AividoProof();

private:
	void ProofStep(int32 Step);

private:
	void UpdateInteractTarget();

	/** Seconds spent in Falling with zero velocity (unstick guard). */
	float FallingStuckTime = 0.f;

	/** True after the first-tick spawn reposition ran. */
	bool bSpawnRepositioned = false;

	/** Anti-drift anchor: last player-commanded position; uncommanded pushes are undone. */
	FVector MovementAnchor = FVector::ZeroVector;
	FVector ProofWalkStart = FVector::ZeroVector;
	bool bAnchorInit = false;
	bool bInputThisFrame = false;
	float NoInputTime = 0.f;

	// Any movement input (keyboard OR programmatic) refreshes the anchor.
	virtual void AddMovementInput(FVector WorldDirection, float ScaleValue = 1.f,
		bool bForceNormalAccel = false) override;

	/** Z of the walkable support surface placed under the spawn point. */
	float FloorTopZ = 0.f;

	/** Deterministic rest height (capsule center) enforced when idle. */
	float RestZ = 0.f;
	bool bRestZInit = false;

	UPROPERTY(EditDefaultsOnly, Category = "Aivido|Input")
	TObjectPtr<UInputMappingContext> DefaultMappingContext;

	UPROPERTY(EditDefaultsOnly, Category = "Aivido|Input")
	TObjectPtr<UInputAction> JumpAction;

	UPROPERTY(EditDefaultsOnly, Category = "Aivido|Input")
	TObjectPtr<UInputAction> MoveAction;

	UPROPERTY(EditDefaultsOnly, Category = "Aivido|Input")
	TObjectPtr<UInputAction> LookAction;

	UPROPERTY(EditDefaultsOnly, Category = "Aivido|Input")
	TObjectPtr<UInputAction> RunAction;

	UPROPERTY(EditDefaultsOnly, Category = "Aivido|Input")
	TObjectPtr<UInputAction> InteractAction;

	UPROPERTY(EditDefaultsOnly, Category = "Aivido|Input")
	TObjectPtr<UInputAction> MenuAction;
};