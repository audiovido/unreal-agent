// Aivido V2 runtime module implementation.

#include "AividoV2.h"

DEFINE_LOG_CATEGORY_STATIC(LogAividoV2, Log, All);

void FAividoV2Module::StartupModule()
{
	UE_LOG(LogAividoV2, Log, TEXT("AividoV2 module started (Aivido V2 playable runtime)."));
}

void FAividoV2Module::ShutdownModule()
{
	UE_LOG(LogAividoV2, Log, TEXT("AividoV2 module stopped."));
}

// Primary game module: required for standalone game targets (defines the
// project globals the Launch module links against).
IMPLEMENT_PRIMARY_GAME_MODULE(FAividoV2Module, AividoV2, "AividoV2");
