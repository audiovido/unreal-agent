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

IMPLEMENT_MODULE(FAividoV2Module, AividoV2)
