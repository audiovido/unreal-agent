#include "Modules/ModuleManager.h"

class FUnrealAgentBridgeModule : public IModuleInterface
{
public:
    virtual void StartupModule() override
    {
    }

    virtual void ShutdownModule() override
    {
    }
};

IMPLEMENT_MODULE(FUnrealAgentBridgeModule, UnrealAgentBridge)
