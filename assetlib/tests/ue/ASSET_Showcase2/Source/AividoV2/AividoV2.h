// Aivido V2 runtime module.

#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

class FAividoV2Module : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};
